"""第四章命令行入口：人工审批、中文审计和示例 Hook。"""

import argparse
import sys
from pathlib import Path

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.openai_chat import OpenAIChatModel
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.hooks import HookRegistry, HookResult
from .core.permissions import PermissionDecision, PermissionRequest
from .core.profiles import P04


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。

    这是什么：终端交互式权限审批器
    Java 类比：类似 @Component class ConsoleApprovalService implements ApprovalProvider
    为什么需要：权限策略决定需要人工审批时，通过终端交互让用户确认或拒绝工具调用
    """
    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """在终端提示用户并等待输入。

        这是什么：审批决策的实现方法
        Java 类比：类似 public Decision promptUser(Request request)
        为什么需要：实现 ApprovalProvider 接口，将权限请求转换为终端交互流程
        """
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
        return PermissionDecision("allow" if allowed else "deny", "用户批准了本次工具调用" if allowed else "用户拒绝了本次工具调用", "terminal-approval")


class TerminalAuditSink:
    """把最终权限决定写到 stderr，避免污染模型最终回答。

    这是什么：权限审计日志记录器
    Java 类比：类似 @Component class StderrAuditLogger implements AuditSink
    为什么需要：记录所有权限决策以供事后审查，输出到 stderr 避免混入模型的正常输出
    """
    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        """记录一次权限决策到标准错误流。

        这是什么：审计记录的实现方法
        Java 类比：类似 public void log(Request request, Decision decision)
        为什么需要：实现 AuditSink 接口，满足合规和调试需求
        """
        definition = request.prepared.definition
        if definition is None:
            raise ValueError("审计请求不完整")
        print(f"[权限审计] {definition.name}: {decision.behavior} ({decision.source}) - {decision.reason}", file=sys.stderr)


def terminal_hooks() -> HookRegistry:
    """创建不改变业务结果的演示 Hook，只输出生命周期日志。

    这是什么：Hook 注册表工厂方法
    Java 类比：类似 @Bean HookRegistry demoHooks() { ... }
    为什么需要：为 CLI 环境提供可观测的生命周期事件日志，但不影响 Agent 实际行为
    """
    hooks = HookRegistry()
    hooks.register("UserPromptSubmit", lambda context: _log_hook(context.event))
    hooks.register("PreToolUse", lambda context: _log_hook(context.event))
    hooks.register("PostToolUse", lambda context: _log_hook(context.event))
    hooks.register("Stop", lambda context: _log_hook(context.event))
    return hooks


def _log_hook(event: str) -> HookResult:
    """输出 Hook 事件到 stderr 并返回空结果。

    这是什么：Hook 回调的日志实现
    Java 类比：类似 private HookResult logEvent(String event)
    为什么需要：提供简单的日志回调，演示 Hook 机制而不干预实际业务流程
    """
    print(f"[Hook] 触发事件: {event}", file=sys.stderr)
    return HookResult()


def main() -> int:
    """解析参数、读取共享 `python/.env`、装配 P04 Agent 并运行。

    这是什么：CLI 主入口函数
    Java 类比：类似 public static void main(String[] args)
    为什么需要：组装第四章的完整能力（工具+权限+Hook），提供可执行的命令行界面
    """
    parser = argparse.ArgumentParser(description="第四章 Agent Hook 生命周期")
    parser.add_argument("--prompt", required=True, help="交给 Agent 的任务")
    args = parser.parse_args()
    try:
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
        settings = settings_from_env_file(env_file)
        file_system = LocalWorkspaceFileSystem()
        runner = build_agent(P04, OpenAIChatModel(settings), str(Path.cwd()), file_system=file_system, approval_provider=TerminalApprovalProvider(), audit_sink=TerminalAuditSink(), hooks=terminal_hooks())
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
