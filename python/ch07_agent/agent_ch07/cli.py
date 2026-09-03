"""第七章命令行入口：在前六章能力上增加按需加载 Skill。

这是什么：
    命令行主程序，负责参数解析、配置读取、Agent 装配和任务执行。

Java 类比：
    类似 Spring Boot 的 main 方法 + CommandLineRunner，或标准 Java 的 Main 类。

为什么需要：
    - 提供可执行的命令行接口，便于快速测试和演示
    - 集成配置、组合根和终端交互，完成端到端流程
    - 第 7 章新增：展示如何使用 SkillRegistry 和 load_skill 工具
"""

import argparse
import sys
from pathlib import Path

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.openai_chat import OpenAIChatModel
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.hooks import HookRegistry, HookResult
from .core.permissions import PermissionDecision, PermissionRequest
from .core.profiles import P07


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。

    这是什么：
        终端交互式审批提供者，实现 ApprovalProvider 接口。

    Java 类比：
        class ConsoleApprovalProvider implements ApprovalProvider
        类似命令行交互的审批实现。

    为什么需要：
        - 将权限策略的 ask 决策转化为终端用户交互
        - 展示工具调用的参数和原因，让用户做出明智决策
        - 无交互输入时默认拒绝，保证安全性（fail-closed 原则）
    """

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
    """把最终权限决定写到 stderr，避免污染模型最终回答。

    这是什么：
        终端审计记录器，实现 AuditSink 接口。

    Java 类比：
        class ConsoleAuditSink implements AuditSink
        类似日志审计的实现。

    为什么需要：
        - 记录所有权限决策（允许/拒绝），便于审计和调试
        - 写入 stderr 而非 stdout，避免混入模型的最终回答
        - 展示决策来源（规则、审批器、边界检查），便于追踪决策路径
    """

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
    """解析参数、读取共享 `python/.env`、装配 P07 Agent 并运行。

    这是什么：
        命令行主入口函数，执行完整的启动和运行流程。

    Java 类比：
        public static void main(String[] args) 主方法
        类似 Spring Boot 的 SpringApplication.run()。

    为什么需要：
        - 集成配置读取、依赖装配、异常处理和退出码管理
        - 返回标准退出码（0=成功，1=运行失败，2=配置错误）
        - 展示如何使用 build_agent 创建完整配置的 Agent
    """
    parser = argparse.ArgumentParser(description="第七章 Agent Skill 按需加载")
    parser.add_argument("--prompt", required=True, help="交给 Agent 的任务")
    args = parser.parse_args()
    try:
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
        settings = settings_from_env_file(env_file)
        file_system = LocalWorkspaceFileSystem()
        runner = build_agent(
            P07,
            OpenAIChatModel(settings),
            str(Path.cwd()),
            file_system=file_system,
            approval_provider=TerminalApprovalProvider(),
            audit_sink=TerminalAuditSink(),
            hooks=terminal_hooks(),
            subagent_model_factory=lambda: OpenAIChatModel(settings),
        )
        print(runner.run(args.prompt).final_text)
        return 0
    except ConfigurationError as error:
        print(f"配置错误: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        print(f"运行失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
