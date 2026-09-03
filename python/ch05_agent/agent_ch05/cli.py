"""第五章命令行入口：人工审批、中文审计、Hook 和 TODO 计划。

Java 对照：这相当于 Spring Boot 的 main 方法所在类，负责参数解析、
依赖注入和启动应用。

这是什么：CLI 入口，组装第五章完整能力并提供交互式审批
为什么需要：演示 Hook、权限、TODO 三大特性的集成使用
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
from .core.profiles import P05


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。

    这是什么：命令行交互式审批实现
    Java 类比：class TerminalApprovalProvider implements ApprovalProvider
    为什么需要：演示人工审批流程，生产环境可替换为工单系统或 Slack 审批
    """

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """在终端显示工具调用详情，并等待用户输入 y/N。

        这是什么：ApprovalProvider 接口的实现方法
        Java 类比：@Override public PermissionDecision decide(PermissionRequest request)
        为什么需要：让用户看到工具调用细节并决定是否允许执行
        """
        definition = request.prepared.definition
        proposed = request.proposed_decision

        # 请求必须包含完整的工具定义和待审批决策
        if definition is None or proposed is None:
            raise ValueError("审批请求不完整")

        # 输出到 stderr，避免污染 stdout 中的模型最终答案
        print(f"\n工具调用需要批准: {definition.name}", file=sys.stderr)
        print(f"原因: {proposed.reason}", file=sys.stderr)
        print(f"参数: {dict(request.prepared.arguments or {})}", file=sys.stderr)

        # 非交互环境（如管道、后台任务）无法读取输入，直接拒绝
        if not sys.stdin.isatty():
            print("无交互输入，默认拒绝。", file=sys.stderr)
            return PermissionDecision("deny", "没有可用的交互式审批输入", "terminal-approval")

        # 等待用户输入，只有 y/yes 视为同意
        answer = input("允许本次调用? [y/N] ").strip().lower()
        allowed = answer in {"y", "yes"}

        return PermissionDecision(
            "allow" if allowed else "deny",
            "用户批准了本次工具调用" if allowed else "用户拒绝了本次工具调用",
            "terminal-approval"
        )


class TerminalAuditSink:
    """把最终权限决定写到 stderr，避免污染模型最终回答。

    这是什么：命令行审计日志实现
    Java 类比：class TerminalAuditSink implements AuditSink
    为什么需要：记录所有权限决定，便于事后审查和合规检查
    """

    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        """输出一行审计日志：工具名 + 决策结果 + 来源 + 原因。

        这是什么：AuditSink 接口的实现方法
        Java 类比：@Override public void record(PermissionRequest request, PermissionDecision decision)
        为什么需要：让管理员能追踪哪些工具被执行、哪些被拒绝
        """
        definition = request.prepared.definition
        if definition is None:
            raise ValueError("审计请求不完整")

        # 格式：[权限审计] 工具名: allow/deny (来源) - 原因
        print(
            f"[权限审计] {definition.name}: {decision.behavior} ({decision.source}) - {decision.reason}",
            file=sys.stderr
        )


def terminal_hooks() -> HookRegistry:
    """创建不改变业务结果的演示 Hook，只输出生命周期日志。

    这是什么：创建演示用的 Hook 注册表
    Java 类比：static HookRegistry createDemoHooks()
    为什么需要：让用户看到 Hook 触发时机，理解生命周期概念
    """
    hooks = HookRegistry()

    # 注册四个生命周期事件的日志 Hook，lambda 类似 Java 的函数式接口实现
    hooks.register("UserPromptSubmit", lambda context: _log_hook(context.event))
    hooks.register("PreToolUse", lambda context: _log_hook(context.event))
    hooks.register("PostToolUse", lambda context: _log_hook(context.event))
    hooks.register("Stop", lambda context: _log_hook(context.event))

    return hooks


def _log_hook(event: str) -> HookResult:
    """输出 Hook 触发日志，并返回空影响（不修改任何行为）。

    这是什么：Hook 回调的最简实现
    Java 类比：private static HookResult logHook(String event)
    为什么需要：演示 Hook 机制，实际生产可在此添加复杂逻辑
    """
    print(f"[Hook] 触发事件: {event}", file=sys.stderr)
    return HookResult()  # 返回空结果，表示不改变任何行为


def main() -> int:
    """解析参数、读取共享 `python/.env`、装配 P05 Agent 并运行。

    这是什么：CLI 主入口函数
    Java 类比：public static void main(String[] args)
    为什么需要：作为可执行脚本的入口点，协调所有组件
    """
    # 使用 argparse 解析命令行参数，类似 Java 的 Apache Commons CLI
    parser = argparse.ArgumentParser(description="第五章 Agent 会话级 TODO")
    parser.add_argument("--prompt", required=True, help="交给 Agent 的任务")
    args = parser.parse_args()

    try:
        # 从当前目录向上查找 .env 文件（通常在 python/.env）
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])

        # 加载配置并创建依赖对象
        settings = settings_from_env_file(env_file)
        file_system = LocalWorkspaceFileSystem()

        # 调用组合根装配第五章 Agent（包含 Hook、权限、TODO 三大特性）
        runner = build_agent(
            P05,  # 第五章能力配置
            OpenAIChatModel(settings),  # 真实模型客户端
            str(Path.cwd()),  # 工作目录
            file_system=file_system,  # 文件系统适配器
            approval_provider=TerminalApprovalProvider(),  # 交互式审批
            audit_sink=TerminalAuditSink(),  # 审计日志
            hooks=terminal_hooks()  # 演示用 Hook
        )

        # 执行 Agent 并输出最终答案到 stdout
        print(runner.run(args.prompt).final_text)
        return 0  # 成功退出码

    except ConfigurationError as error:
        # 配置错误返回退出码 2
        print(f"配置错误: {error}", file=sys.stderr)
        return 2

    except Exception as error:  # noqa: BLE001
        # 其他运行时错误返回退出码 1
        print(f"运行失败: {error}", file=sys.stderr)
        return 1


# Python 脚本直接执行时的入口点，类似 Java 的 public static void main
if __name__ == "__main__":
    raise SystemExit(main())
