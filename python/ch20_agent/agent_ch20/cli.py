"""第二十章命令行入口：完整 Harness 的真实运行边界。

这是 P20 唯一的真实组合根调用点，负责四件事，其他地方不重复实现：

1. 解析命令行参数与 `.env` 配置；
2. 创建全部真实运行时，并让跨能力对象共享同一份存储与事件流；
3. 提供终端审批与审计这两个人工边界；
4. 无论运行成功还是失败，都按统一顺序释放资源并归一错误码。

Java 对照：类似 Spring Boot 的 `main` 加上一个 `@Configuration`。区别是这里显式
写出装配顺序和关闭顺序，因为 Agent 持有子进程、后台线程和数据库这类必须回收的资源。
"""

import argparse
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .adapters.background_json import JsonBackgroundJobStore
from .adapters.cron_json import JsonCronStore
from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.git import SubprocessGitRunner
from .adapters.mailbox_json import FileMailboxStore
from .adapters.mcp_client import SubprocessMcpConnectionFactory
from .adapters.openai_chat import OpenAIChatModel
from .adapters.task_sqlite import SqliteTaskStore
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.events import EventInbox
from .core.hooks import HookRegistry, HookResult
from .core.permissions import PermissionDecision, PermissionRequest
from .core.profiles import P20
from .features.background import JobSupervisor
from .features.cron import CronRuntime
from .features.mcp_tools import McpRuntime, McpServerSpec, McpToolPolicy
from .features.protocol import JsonProtocolStore, ProtocolRuntime
from .features.recovery import RecoveryConfig
from .features.teammates import TeammateRuntime
from .features.work_stealing import WorkStealingRuntime
from .features.worktrees import WorktreeRuntime


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。"""

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        definition = request.prepared.definition
        proposed = request.proposed_decision
        if definition is None or proposed is None:
            raise ValueError("审批请求不完整")
        print(f"\n工具调用需要批准: {definition.name}", file=sys.stderr)
        print(f"原因: {proposed.reason}", file=sys.stderr)
        print(f"参数: {dict(request.prepared.arguments or {})}", file=sys.stderr)
        if not sys.stdin.isatty():
            print("无交互输入，默认拒绝。", file=sys.stderr)
            return PermissionDecision("deny", "没有可用的交互式审批输入", "terminal-approval")
        answer = input("允许本次调用? [y/N] ").strip().lower()
        allowed = answer in {"y", "yes"}
        return PermissionDecision(
            "allow" if allowed else "deny",
            "用户批准了本次工具调用" if allowed else "用户拒绝了本次工具调用",
            "terminal-approval",
        )


class TerminalAuditSink:
    """把最终权限决定写到 stderr，避免污染模型最终回答。"""

    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        definition = request.prepared.definition
        if definition is None:
            raise ValueError("审计请求不完整")
        print(
            f"[权限审计] {definition.name}: {decision.behavior} ({decision.source}) - {decision.reason}",
            file=sys.stderr,
        )


def terminal_hooks() -> HookRegistry:
    """创建不改变业务结果的演示 Hook，只输出生命周期日志。"""
    hooks = HookRegistry()
    hooks.register("UserPromptSubmit", lambda context: _log_hook(context.event))
    hooks.register("PreToolUse", lambda context: _log_hook(context.event))
    hooks.register("PostToolUse", lambda context: _log_hook(context.event))
    hooks.register("Stop", lambda context: _log_hook(context.event))
    return hooks


def _log_hook(event: str) -> HookResult:
    print(f"[Hook] 触发事件: {event}", file=sys.stderr)
    return HookResult()


@dataclass(frozen=True, slots=True)
class LiveRuntime:
    """真实运行所需的全部长生命周期对象。

    这是 P20 唯一的真实组合根产物：所有跨能力共享关系（同一个 EventInbox、
    同一个 JobSupervisor、同一个 SqliteTaskStore）都在 ``create_live_runtime``
    里建立好，``execute`` 只消费这份不可变快照。

    Java 对照：类似 Spring 启动完成后的 ApplicationContext——持有单例、
    维护关闭顺序，业务代码只从里面取，不再自己 new。

    字段说明：
        settings: 已校验的四项 OpenAI 配置。
        build_kwargs: 传给 ``build_agent`` 的关键字参数，装配与执行因此分离。
        cron_runtime / teammate_runtime: 需要显式 start() 的事件源。
        closables: 组装失败时按创建顺序兜底关闭的运行时。
    """

    settings: object
    build_kwargs: Mapping[str, object]
    cron_runtime: CronRuntime
    teammate_runtime: TeammateRuntime
    closables: tuple[object, ...]


def create_live_runtime(workspace: str, settings: object) -> LiveRuntime:
    """按 P20 能力创建真实运行时，并让各能力共享同一份状态。

    共享关系是硬要求，不是优化：``build_agent`` 会用对象身份校验它们，
    因此这里必须复用同一个 inbox、supervisor 和 task store。
    """
    inbox = EventInbox()
    # 后台 supervisor 与 EventInbox 是 Cron/Teammate 共用的单一事件源。
    supervisor = JobSupervisor(JsonBackgroundJobStore(workspace), inbox)
    cron_runtime = CronRuntime(JsonCronStore(workspace), inbox, supervisor=supervisor)
    mailbox_store = FileMailboxStore(workspace)
    teammate_runtime = TeammateRuntime(mailbox_store, inbox, supervisor, cron_runtime)
    # 协议运行时复用队友的 TeammateRuntime/MailboxStore，请求状态落在独立 JsonProtocolStore。
    protocol_runtime = ProtocolRuntime(JsonProtocolStore(workspace), teammate_runtime)
    # 单个 SqliteTaskStore 同时供 Lead、Subagent 和 Teammate 使用，避免数据库分叉。
    task_store = SqliteTaskStore(workspace)
    # WorktreeRuntime 同时实现 TaskClaimService 与 ToolContextProvider。
    worktree_runtime = WorktreeRuntime(workspace, task_store, SubprocessGitRunner())
    # 必须先验证仓库，失败时不能创建 .agent_tutorial 等运行状态。
    worktree_runtime.validate_repository()
    work_stealing = WorkStealingRuntime(task_store, claim_service=worktree_runtime)
    # 只有声明了 mcp 能力才创建运行时，避免低章节额外启动子进程。
    mcp_runtime = McpRuntime(
        (
            McpServerSpec(
                "demo",
                sys.executable,
                ("-m", "agent_ch20.mcp_servers.demo"),
                (McpToolPolicy("lookup", "read"),),
            ),
        ),
        SubprocessMcpConnectionFactory(),
    )
    build_kwargs: dict[str, object] = {
        "file_system": LocalWorkspaceFileSystem(),
        "approval_provider": TerminalApprovalProvider(),
        "audit_sink": TerminalAuditSink(),
        "hooks": terminal_hooks(),
        "subagent_model_factory": lambda: OpenAIChatModel(settings),  # type: ignore[arg-type]
        "recovery_config": RecoveryConfig(
            settings.model,  # type: ignore[attr-defined]
            settings.fallback_model,  # type: ignore[attr-defined]
        ),
        "task_store": task_store,
        "background_store": JsonBackgroundJobStore(workspace),
        "background_supervisor": supervisor,
        "cron_runtime": cron_runtime,
        "mailbox_store": mailbox_store,
        "teammate_runtime": teammate_runtime,
        "protocol_runtime": protocol_runtime,
        "work_stealing_runtime": work_stealing,
        "worktree_runtime": worktree_runtime,
        "mcp_runtime": mcp_runtime,
    }
    return LiveRuntime(
        settings=settings,
        build_kwargs=build_kwargs,
        cron_runtime=cron_runtime,
        teammate_runtime=teammate_runtime,
        # 逆创建顺序：MCP 最先关闭，后台 supervisor 最后关闭。
        closables=(mcp_runtime, teammate_runtime, cron_runtime, supervisor),
    )


def execute(prompt: str, workspace: str, settings: object) -> int:
    """运行一次 P20 会话，并保证成功与失败路径都释放资源。

    资源所有权分两段：``build_agent`` 成功后由 AgentRunner 统一逆序关闭；
    组装本身失败时没有 Runner，才按创建顺序用 ``closables`` 兜底。
    这样任何一条路径都不会遗留 stdio 子进程或后台线程。
    """
    runtime = create_live_runtime(workspace, settings)
    runner = None
    # failures 收集执行与清理阶段的全部异常，避免前一个错误掩盖后一个。
    failures: list[BaseException] = []
    exit_code: int | None = None
    try:
        runner = build_agent(P20, OpenAIChatModel(settings), workspace, **runtime.build_kwargs)  # type: ignore[arg-type]
        # 同步上游修复 79437ad：worker 线程只置位标志，事件回合由主线程
        # 串行消费，避免两个线程同时进入同一个 AgentRunner。
        wakeup = threading.Event()
        runtime.teammate_runtime.bind_wakeup(wakeup.set)
        runtime.cron_runtime.start()
        runtime.teammate_runtime.start()
        print(runner.run(prompt).final_text)
        # 主回合结束后继续消费队友/Cron 事件回合，队友汇报不再只落盘等下次运行。
        idle_rounds = 0
        while idle_rounds < 12:  # 连续 60 秒没有新事件就结束等待。
            event_result = runner.run_events()
            if event_result is not None:
                print(event_result.final_text)
                idle_rounds = 0
                continue
            if not runtime.teammate_runtime.has_pending_work:
                break
            if wakeup.wait(timeout=5):
                wakeup.clear()
            else:
                idle_rounds += 1
        exit_code = 0
    except BaseException as error:  # noqa: BLE001
        failures.append(error)
    if runner is not None:
        # Runner 持有统一 resources，逆序关闭 MCP、Teammate、Cron 和 Supervisor。
        try:
            runner.close()
        except BaseException as error:  # noqa: BLE001
            failures.append(error)
    else:
        # build_agent 失败时没有统一 resources，按创建顺序兜底关闭。
        for resource in runtime.closables:
            try:
                resource.close()  # type: ignore[attr-defined]
            except BaseException as error:  # noqa: BLE001
                failures.append(error)
    if len(failures) == 1:
        raise failures[0]
    if len(failures) > 1:
        # Python 的 ExceptionGroup 对应 TypeScript 的 AggregateError。
        raise BaseExceptionGroup("CLI 执行或清理失败", failures)
    if exit_code is None:
        raise RuntimeError("CLI 执行结束但没有产生退出码")
    return exit_code


def main() -> int:
    """解析参数、校验配置与 Git 仓库，再运行 P20 完整 Harness。"""
    parser = argparse.ArgumentParser(description="第二十章完整 Agent Harness")
    parser.add_argument("--prompt", required=True, help="交给 Agent 的任务")
    args = parser.parse_args()
    try:
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(
                ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_FALLBACK_MODEL"]
            )
        # 先读配置：缺失配置时直接失败，不创建模型、MCP 或 .agent_tutorial 状态。
        settings = settings_from_env_file(env_file)
        return execute(args.prompt, str(Path.cwd()), settings)
    except ConfigurationError as error:
        print(f"配置错误: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"运行失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
