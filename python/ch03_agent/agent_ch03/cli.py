"""第三章命令行入口：提供人工审批和终端审计适配器。

这是什么：main() 函数入口，装配 P03 Agent 并提供终端 y/N 审批和 stderr 审计。
Java 类比：类似 Spring Boot 的 @SpringBootApplication 主类。
为什么需要：命令行工具需要交互式审批，审计日志输出到 stderr 不污染模型回答。
"""

import argparse
import sys
from pathlib import Path

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.openai_chat import OpenAIChatModel
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.permissions import PermissionDecision, PermissionRequest
from .core.profiles import P03


class TerminalApprovalProvider:
    """把策略产生的 ask 决策交给终端用户确认。"""

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """只有明确输入 y/yes 才 allow，其余情况全部 deny。"""
        definition = request.prepared.definition
        proposed = request.proposed_decision
        if definition is None or proposed is None:
            raise ValueError("审批请求不完整")
        print(f"\n工具调用需要批准: {definition.name}", file=sys.stderr)
        print(f"原因: {proposed.reason}", file=sys.stderr)
        print(f"参数: {request.prepared.arguments}", file=sys.stderr)
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
        """输出工具名、最终行为、来源和中文原因。"""
        definition = request.prepared.definition
        if definition is None:
            raise ValueError("审计请求不完整")
        print(
            f"[权限审计] {definition.name}: {decision.behavior} "
            f"({decision.source}) - {decision.reason}",
            file=sys.stderr,
        )


def main() -> int:
    """解析参数、加载共享配置、装配 P03 Agent 并执行任务。"""
    parser = argparse.ArgumentParser(description="第三章 Agent 权限策略")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    try:
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
        settings = settings_from_env_file(env_file)
        file_system = LocalWorkspaceFileSystem()
        runner = build_agent(
            P03,
            OpenAIChatModel(settings),
            str(Path.cwd()),
            file_system=file_system,
            approval_provider=TerminalApprovalProvider(),
            audit_sink=TerminalAuditSink(),
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
