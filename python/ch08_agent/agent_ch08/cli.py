"""第八章命令行入口：在前七章能力上增加按需加载 Skill。

这是什么：CLI 程序的主入口模块
Java 类比：类似包含 main 方法的 Application 类
为什么需要：将命令行解析、配置加载、Agent 组装和执行流程整合在一起
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
from .core.profiles import P08


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。

    这是什么：基于终端交互的权限审批实现
    Java 类比：类似 class ConsoleApprovalProvider implements ApprovalProvider
    为什么需要：在 CLI 环境中让真人用户确认工具调用，避免自动执行危险操作
    """

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """提示用户并收集 y/N 响应。

        这是什么：通过标准输入让用户决定是否允许工具调用
        Java 类比：类似 Scanner.nextLine() 后解析用户输入
        为什么需要：实现 ApprovalProvider 接口，将权限决策权交给真人用户
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
        return PermissionDecision(
            "allow" if allowed else "deny",
            "用户批准了本次工具调用" if allowed else "用户拒绝了本次工具调用",
            "terminal-approval",
        )


class TerminalAuditSink:
    """把最终权限决定写到 stderr，避免污染模型最终回答。

    这是什么：将权限决策记录到标准错误流的审计实现
    Java 类比：类似 class StderrAuditSink implements AuditSink
    为什么需要：记录每次工具调用的授权结果，用于调试和合规审查
    """

    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        """将权限决策日志输出到 stderr。

        这是什么：记录一次权限决策的审计方法
        Java 类比：类似 logger.info("permission decision: {}", decision)
        为什么需要：实现 AuditSink 接口，提供可追溯的权限决策历史
        """
        definition = request.prepared.definition
        if definition is None:
            raise ValueError("审计请求不完整")
        print(
            f"[权限审计] {definition.name}: {decision.behavior} ({decision.source}) - {decision.reason}",
            file=sys.stderr,
        )


def terminal_hooks() -> HookRegistry:
    """创建不改变业务结果的演示 Hook，只输出生命周期日志。

    这是什么：创建并配置 Hook 注册表的工厂函数
    Java 类比：类似 HookRegistry createHooks() 配置方法
    为什么需要：为 CLI 环境提供可观测的生命周期事件日志
    """
    hooks = HookRegistry()
    hooks.register("UserPromptSubmit", lambda context: _log_hook(context.event))
    hooks.register("PreToolUse", lambda context: _log_hook(context.event))
    hooks.register("PostToolUse", lambda context: _log_hook(context.event))
    hooks.register("Stop", lambda context: _log_hook(context.event))
    return hooks


def _log_hook(event: str) -> HookResult:
    """输出 Hook 事件到 stderr 的简单日志函数。

    这是什么：Hook 回调函数的实现
    Java 类比：类似 Consumer<String> logHook = event -> logger.info(event)
    为什么需要：提供一个无副作用的 Hook 实现，用于观察 Agent 生命周期
    """
    print(f"[Hook] 触发事件: {event}", file=sys.stderr)
    return HookResult()


def main() -> int:
    """解析参数、读取共享 `python/.env`、装配 P08 Agent 并运行。

    这是什么：命令行程序的主入口函数
    Java 类比：类似 public static void main(String[] args) 方法
    为什么需要：整合所有启动逻辑，提供标准的 CLI 接口和错误处理
    """
    parser = argparse.ArgumentParser(description="第八章 Agent Skill 按需加载")
    parser.add_argument("--prompt", required=True, help="交给 Agent 的任务")
    args = parser.parse_args()
    try:
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
        settings = settings_from_env_file(env_file)
        file_system = LocalWorkspaceFileSystem()
        runner = build_agent(
            P08,
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
