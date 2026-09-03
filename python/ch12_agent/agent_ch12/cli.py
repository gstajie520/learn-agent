"""第十二章命令行入口：主模型请求带统一恢复策略，支持持久化任务 DAG。

这是什么：第十二章的命令行程序入口
Java 类比：类似 Spring Boot 的 Application 主类，负责装配和启动
为什么需要：提供完整的 P12 配置示例，包括任务存储、恢复策略和权限审批
"""

import argparse
import sys
from pathlib import Path

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.openai_chat import OpenAIChatModel
from .adapters.task_json import JsonTaskStore
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.hooks import HookRegistry, HookResult
from .core.permissions import PermissionDecision, PermissionRequest
from .core.profiles import P12
from .features.recovery import RecoveryConfig


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。

    这是什么：终端交互式权限审批提供者
    Java 类比：类似实现 ApprovalProvider 接口的控制台审批服务
    为什么需要：演示环境通过命令行与用户交互，生产环境可替换为 Web 审批流
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

    这是什么：终端审计日志记录器
    Java 类比：类似实现 AuditSink 接口的日志服务
    为什么需要：权限决策需要留下审计记录，便于安全审查和问题排查
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
    """创建不改变业务结果的演示 Hook，只输出生命周期日志。

    这是什么：创建终端 Hook 注册表的工厂函数
    Java 类比：类似 @Bean 方法，返回配置好的 HookRegistry 实例
    为什么需要：演示 Hook 机制，生产环境可注册真实的监控、日志和通知逻辑
    """
    hooks = HookRegistry()
    hooks.register("UserPromptSubmit", lambda context: _log_hook(context.event))
    hooks.register("PreToolUse", lambda context: _log_hook(context.event))
    hooks.register("PostToolUse", lambda context: _log_hook(context.event))
    hooks.register("Stop", lambda context: _log_hook(context.event))
    return hooks


def _log_hook(event: str) -> HookResult:
    """Hook 回调函数：输出事件名到 stderr 并返回空结果。

    这是什么：简单的 Hook 回调实现
    Java 类比：类似 Lambda 表达式 event -> { log(event); return empty(); }
    为什么需要：演示 Hook 机制不修改业务流程，只做观察和日志记录
    """
    print(f"[Hook] 触发事件: {event}", file=sys.stderr)
    return HookResult()


def main() -> int:
    """解析参数、读取共享配置、装配 P12 持久化任务 Agent 并运行。

    这是什么：命令行程序的主入口函数
    Java 类比：类似 public static void main(String[] args) 方法
    为什么需要：统一处理配置加载、依赖装配、异常捕获和退出码返回
    """
    parser = argparse.ArgumentParser(description="第十二章 JSON Task DAG")
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
        runner = build_agent(
            P12,
            OpenAIChatModel(settings),
            str(Path.cwd()),
            file_system=file_system,
            approval_provider=TerminalApprovalProvider(),
            audit_sink=TerminalAuditSink(),
            hooks=terminal_hooks(),
            subagent_model_factory=lambda: OpenAIChatModel(settings),
            recovery_config=RecoveryConfig(settings.model, settings.fallback_model),
            task_store=JsonTaskStore(str(Path.cwd())),
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
