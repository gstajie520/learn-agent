"""第九章命令行入口：在前八章能力上增加长期记忆功能。

Java 角度：这是 Main 类，负责解析命令行参数、加载配置、装配依赖并启动应用。
类似 Spring Boot 的 @SpringBootApplication 启动类。

这是什么：命令行应用的主入口
Java 类比：类似带 public static void main(String[] args) 的启动类
为什么需要：作为用户与 Agent 交互的接口，处理配置和启动逻辑
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
from .core.profiles import P09


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。

    这是什么：终端交互式审批提供者
    Java 类比：类似 Scanner 交互式输入处理器
    为什么需要：在命令行环境中让用户决定是否允许工具调用
    """

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """向用户展示工具调用请求，等待审批决定。

        参数：
            request: 权限请求对象，包含工具信息和参数

        返回：
            PermissionDecision: 用户的审批决定（允许/拒绝）
        """
        definition = request.prepared.definition
        proposed = request.proposed_decision
        if definition is None or proposed is None:
            raise ValueError("审批请求不完整")

        # 在 stderr 输出，避免污染模型的最终答案（stdout）
        print(f"\n工具调用需要批准: {definition.name}", file=sys.stderr)
        print(f"原因: {proposed.reason}", file=sys.stderr)
        print(f"参数: {dict(request.prepared.arguments or {})}", file=sys.stderr)

        # 非交互式环境（如 CI/CD）默认拒绝，避免无限等待
        if not sys.stdin.isatty():
            print("无交互输入，默认拒绝。", file=sys.stderr)
            return PermissionDecision("deny", "没有可用的交互式审批输入", "terminal-approval")

        # 等待用户输入 y/yes 表示同意
        answer = input("允许本次调用? [y/N] ").strip().lower()
        allowed = answer in {"y", "yes"}
        return PermissionDecision(
            "allow" if allowed else "deny",
            "用户批准了本次工具调用" if allowed else "用户拒绝了本次工具调用",
            "terminal-approval",
        )


class TerminalAuditSink:
    """把最终权限决定写到 stderr，避免污染模型最终回答。

    这是什么：终端审计日志接收器
    Java 类比：类似 Logger 或 AuditEventListener
    为什么需要：记录所有权限决策，便于调试和审计追溯
    """

    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        """记录一次权限决策到终端。

        参数：
            request: 权限请求对象
            decision: 最终的权限决定
        """
        definition = request.prepared.definition
        if definition is None:
            raise ValueError("审计请求不完整")
        # 输出到 stderr，不影响 Agent 的最终答案（stdout）
        print(
            f"[权限审计] {definition.name}: {decision.behavior} ({decision.source}) - {decision.reason}",
            file=sys.stderr,
        )


def terminal_hooks() -> HookRegistry:
    """创建不改变业务结果的演示 Hook，只输出生命周期日志。

    这是什么：Hook 注册表工厂方法
    Java 类比：类似 Spring 的 ApplicationListener 注册
    为什么需要：让用户看到 Agent 的生命周期事件，用于教学和调试

    返回：
        HookRegistry: 配置好的 Hook 注册表
    """
    hooks = HookRegistry()
    # 注册四个关键生命周期事件的监听器
    hooks.register("UserPromptSubmit", lambda context: _log_hook(context.event))
    hooks.register("PreToolUse", lambda context: _log_hook(context.event))
    hooks.register("PostToolUse", lambda context: _log_hook(context.event))
    hooks.register("Stop", lambda context: _log_hook(context.event))
    return hooks


def _log_hook(event: str) -> HookResult:
    """记录 Hook 事件到终端。

    这是什么：Hook 回调函数的实现
    Java 类比：类似事件监听器的 onEvent(Event e) 方法
    为什么需要：统一的日志输出逻辑，避免重复代码

    参数：
        event: 事件名称

    返回：
        HookResult: 空结果，表示不修改 Agent 行为
    """
    print(f"[Hook] 触发事件: {event}", file=sys.stderr)
    return HookResult()


def main() -> int:
    """解析参数、读取共享 `python/.env`、装配 P09 Agent 并运行。

    这是什么：应用主函数，处理启动流程
    Java 类比：类似 SpringApplication.run(Application.class, args)
    为什么需要：集中处理配置加载、依赖注入和错误处理

    返回：
        int: 退出码（0=成功, 1=运行错误, 2=配置错误）
    """
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="第九章 Agent 长期记忆功能")
    parser.add_argument("--prompt", required=True, help="交给 Agent 的任务")
    args = parser.parse_args()

    try:
        # 向上查找共享的 .env 配置文件
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])

        # 加载配置并校验
        settings = settings_from_env_file(env_file)
        file_system = LocalWorkspaceFileSystem()

        # 装配第九章 Agent（包含所有累计功能）
        runner = build_agent(
            P09,  # 第九章配置
            OpenAIChatModel(settings),
            str(Path.cwd()),
            file_system=file_system,
            approval_provider=TerminalApprovalProvider(),  # 终端审批
            audit_sink=TerminalAuditSink(),  # 审计日志
            hooks=terminal_hooks(),  # 生命周期 Hook
            subagent_model_factory=lambda: OpenAIChatModel(settings),  # 子 Agent 模型
        )

        # 运行 Agent 并输出最终答案
        print(runner.run(args.prompt).final_text)
        return 0

    except ConfigurationError as error:
        # 配置错误：返回特定退出码 2
        print(f"配置错误: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001
        # 其他运行时错误：返回通用退出码 1
        print(f"运行失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Python 标准做法：通过 SystemExit 传递退出码
    raise SystemExit(main())
