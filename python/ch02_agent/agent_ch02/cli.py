"""第 2 章命令行入口。"""

import argparse
import sys
from pathlib import Path

from .adapters.openai_chat import OpenAIChatModel
from .bootstrap import build_agent
from .config import ConfigurationError, find_env_file, settings_from_env_file
from .core.loop import ToolAuthorizationDecision
from .core.profiles import P02
from .core.tools import PreparedToolCall, ToolContext


class TerminalAuthorizer:
    """执行 PowerShell 前要求人工确认；没有交互输入时默认拒绝。

    这个类只负责终端交互，不负责执行工具。相当于 Java 中一个权限确认适配器。
    """

    def authorize(self, prepared: PreparedToolCall, _context: ToolContext) -> ToolAuthorizationDecision:
        """在终端展示工具名称和参数，并读取用户批准结果。

        `_context` 前面的下划线表示当前方法暂时没有使用这个参数，
        但为了满足 ToolAuthorizer 接口仍然必须保留，类似 Java 实现接口时保留未使用参数。
        """
        if prepared.definition is None:
            raise ValueError("工具授权请求不完整")
        if prepared.definition.effect != "execute":
            return ToolAuthorizationDecision(True, "该工具类型不需要人工批准")
        print(f"\n工具调用需要批准: {prepared.definition.name}", file=sys.stderr)
        print(f"参数: {prepared.arguments}", file=sys.stderr)
        if not sys.stdin.isatty():
            print("无交互输入，默认拒绝。", file=sys.stderr)
            return ToolAuthorizationDecision(False, "没有可用的交互式批准输入")
        answer = input("允许本次调用? [y/N] ").strip().lower()
        return ToolAuthorizationDecision(answer in {"y", "yes"}, "用户批准了本次工具调用" if answer in {"y", "yes"} else "用户拒绝了本次工具调用")


def main() -> int:
    """解析命令行、读取配置、装配 Agent，然后执行一次用户请求。"""
    # argparse 类似 Spring Shell/CLI 的参数绑定器，会自动处理 --help 和缺失参数。
    parser = argparse.ArgumentParser(description="第 2 章 Agent Loop")
    parser.add_argument("--prompt", required=True)  # 声明必填命令行参数，类似定义一个 CLI DTO 字段。
    args = parser.parse_args()
    try:
        # 从当前章节目录向上找到共享的 python/.env。
        env_file = find_env_file(Path.cwd())
        if env_file is None:
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
        settings = settings_from_env_file(env_file)
        # CLI 是最外层，因此在这里创建真实模型适配器和终端授权器。
        runner = build_agent(P02, OpenAIChatModel(settings), str(Path.cwd()), authorizer=TerminalAuthorizer())
        result = runner.run(args.prompt)  # 真正进入 AgentRunner 核心循环。
        print(result.final_text)
        return 0
    except ConfigurationError as error:
        print(f"配置错误: {error}", file=sys.stderr)
        return 2
    # CLI 是最外层兜底边界：任何未分类异常都要转成中文提示和非零退出码。
    except Exception as error:  # noqa: BLE001
        print(f"运行失败: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # 只有 `python -m agent_ch02.cli` 直接运行本文件时才启动；被测试 import 时不会自动执行。
    raise SystemExit(main())
