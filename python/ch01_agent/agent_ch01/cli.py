"""第 1 章命令行入口。"""

import argparse
from pathlib import Path
import sys

from .adapters.openai_chat import OpenAIChatModel
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.profiles import P01
from .core.loop import ToolAuthorizationDecision
from .core.tools import PreparedToolCall, ToolContext


class TerminalAuthorizer:
    """执行 PowerShell 前要求人工确认；没有交互输入时默认拒绝。

    这个类只负责终端交互，不负责执行工具。相当于 Java 中一个权限确认适配器。
    """

    def authorize(self, prepared: PreparedToolCall, _context: ToolContext) -> ToolAuthorizationDecision:
        print(f"\n工具调用需要批准: {prepared.definition.name if prepared.definition else 'unknown'}", file=sys.stderr)
        print(f"参数: {prepared.arguments}", file=sys.stderr)
        if not sys.stdin.isatty():
            print("无交互输入，默认拒绝。", file=sys.stderr)
            return ToolAuthorizationDecision(False, "No interactive approval input was available")
        answer = input("允许本次调用? [y/N] ").strip().lower()
        return ToolAuthorizationDecision(answer in {"y", "yes"}, "User approved this tool call" if answer in {"y", "yes"} else "User denied this tool call")


def main() -> int:
    """解析命令行、读取配置、装配 Agent，然后执行一次用户请求。"""
    # argparse 类似 Spring Shell/CLI 的参数绑定器，会自动处理 --help 和缺失参数。
    parser = argparse.ArgumentParser(description="第 1 章 Agent Loop")
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    try:
        # 从当前章节目录向上找到共享的 python/.env。
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
        settings = settings_from_env_file(env_file)
        # CLI 是最外层，因此在这里创建真实模型适配器和终端授权器。
        runner = build_agent(P01, OpenAIChatModel(settings), str(Path.cwd()), authorizer=TerminalAuthorizer())
        result = runner.run(args.prompt)
        print(result.final_text)
        return 0
    except ConfigurationError as error:
        print(f"配置错误: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"运行失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # 只有 `python -m agent_ch01.cli` 直接运行本文件时才启动；被测试 import 时不会自动执行。
    raise SystemExit(main())
