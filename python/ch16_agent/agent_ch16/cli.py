"""第十六章命令行入口：增加计划审批协议与优雅关机。"""

import argparse
import sys
from pathlib import Path

from .adapters.background_json import JsonBackgroundJobStore
from .adapters.cron_json import JsonCronStore
from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.mailbox_json import FileMailboxStore
from .adapters.openai_chat import OpenAIChatModel
from .adapters.task_json import JsonTaskStore
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.events import EventInbox
from .core.hooks import HookRegistry, HookResult
from .core.permissions import PermissionDecision, PermissionRequest
from .core.profiles import P16
from .features.background import JobSupervisor
from .features.cron import CronRuntime
from .features.protocol import JsonProtocolStore, ProtocolRuntime
from .features.recovery import RecoveryConfig
from .features.teammates import TeammateRuntime


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


def main() -> int:
    """解析参数、读取共享配置、装配 P16 协议协作 Agent。"""
    parser = argparse.ArgumentParser(description="第十六章计划审批与优雅关机 Agent")
    parser.add_argument("--prompt", required=True, help="交给 Agent 的任务")
    args = parser.parse_args()
    try:
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(
                ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_FALLBACK_MODEL"]
            )
        settings = settings_from_env_file(env_file)
        file_system = LocalWorkspaceFileSystem()
        inbox = EventInbox()
        supervisor = JobSupervisor(JsonBackgroundJobStore(str(Path.cwd())), inbox)
        cron_runtime = CronRuntime(JsonCronStore(str(Path.cwd())), inbox, supervisor=supervisor)
        mailbox_store = FileMailboxStore(str(Path.cwd()))
        teammate_runtime = TeammateRuntime(mailbox_store, inbox, supervisor, cron_runtime)
        protocol_runtime = ProtocolRuntime(JsonProtocolStore(str(Path.cwd())), teammate_runtime)
        runner = build_agent(
            P16,
            OpenAIChatModel(settings),
            str(Path.cwd()),
            file_system=file_system,
            approval_provider=TerminalApprovalProvider(),
            audit_sink=TerminalAuditSink(),
            hooks=terminal_hooks(),
            subagent_model_factory=lambda: OpenAIChatModel(settings),
            recovery_config=RecoveryConfig(settings.model, settings.fallback_model),
            task_store=JsonTaskStore(str(Path.cwd())),
            background_store=JsonBackgroundJobStore(str(Path.cwd())),
            background_supervisor=supervisor,
            cron_runtime=cron_runtime,
            mailbox_store=mailbox_store,
            teammate_runtime=teammate_runtime,
            protocol_runtime=protocol_runtime,
        )
        cron_runtime.start()
        teammate_runtime.start()
        print(runner.run(args.prompt).final_text)
        runner.close()
        return 0
    except ConfigurationError as error:
        print(f"配置错误: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"运行失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
