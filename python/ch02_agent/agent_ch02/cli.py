"""第 2 章命令行入口。

这是什么：CLI 启动层，负责参数解析、配置加载和 Agent 启动
Java 类比：类似 Spring Boot 的 @SpringBootApplication 主类或 CLI 入口类
为什么需要：提供可执行的命令行接口，连接外部世界和 Agent 核心逻辑
"""

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

    这是什么：交互式命令授权器，通过终端获取人工批准
    Java 类比：类似 @Component class InteractiveAuthorizer implements ToolAuthorizer
    为什么需要：在 CLI 环境提供安全保护，防止 Agent 未经授权执行危险命令

    这个类只负责终端交互，不负责执行工具。相当于 Java 中一个权限确认适配器。
    """

    def authorize(self, prepared: PreparedToolCall, _context: ToolContext) -> ToolAuthorizationDecision:
        """在终端展示工具名称和参数，并读取用户批准结果。

        这是什么：授权决策方法，向用户展示请求并获取批准
        Java 类比：类似 AuthorizationDecision authorize(PreparedToolCall call, Context ctx)
        为什么需要：实现 ToolAuthorizer 接口契约，提供人工审核点

        `_context` 前面的下划线表示当前方法暂时没有使用这个参数，
        但为了满足 ToolAuthorizer 接口仍然必须保留，类似 Java 实现接口时保留未使用参数。
        """
        if prepared.definition is None:  # 工具定义缺失时拒绝
            raise ValueError("工具授权请求不完整")
        if prepared.definition.effect != "execute":  # 非执行类工具（如只读查询）无需批准
            return ToolAuthorizationDecision(True, "该工具类型不需要人工批准")
        print(f"\n工具调用需要批准: {prepared.definition.name}", file=sys.stderr)  # 显示工具名
        print(f"参数: {prepared.arguments}", file=sys.stderr)  # 显示参数
        if not sys.stdin.isatty():  # 非交互式环境（如管道、自动化脚本）默认拒绝
            print("无交互输入，默认拒绝。", file=sys.stderr)
            return ToolAuthorizationDecision(False, "没有可用的交互式批准输入")
        answer = input("允许本次调用? [y/N] ").strip().lower()  # 读取用户输入
        return ToolAuthorizationDecision(answer in {"y", "yes"}, "用户批准了本次工具调用" if answer in {"y", "yes"} else "用户拒绝了本次工具调用")  # 返回授权决策


def main() -> int:
    """解析命令行、读取配置、装配 Agent，然后执行一次用户请求。

    这是什么：CLI 主函数，程序入口点
    Java 类比：类似 public static void main(String[] args) 或 CommandLineRunner.run()
    为什么需要：串联配置加载、Agent 构建和执行流程，处理异常并返回退出码
    """
    # argparse 类似 Spring Shell/CLI 的参数绑定器，会自动处理 --help 和缺失参数。
    parser = argparse.ArgumentParser(description="第 2 章 Agent Loop")
    parser.add_argument("--prompt", required=True)  # 声明必填命令行参数，类似定义一个 CLI DTO 字段。
    args = parser.parse_args()  # 解析命令行参数
    try:
        # 从当前章节目录向上找到共享的 python/.env。
        env_file = find_env_file(Path.cwd())  # 向上查找配置文件
        if env_file is None:  # 配置文件不存在时抛出配置错误
            raise ConfigurationError(["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
        settings = settings_from_env_file(env_file)  # 从 .env 文件读取配置
        # CLI 是最外层，因此在这里创建真实模型适配器和终端授权器。
        runner = build_agent(P02, OpenAIChatModel(settings), str(Path.cwd()), authorizer=TerminalAuthorizer())  # 组装 Agent
        result = runner.run(args.prompt)  # 真正进入 AgentRunner 核心循环。
        print(result.final_text)  # 输出最终答案
        return 0  # 成功退出
    except ConfigurationError as error:  # 捕获配置错误
        print(f"配置错误: {error}", file=sys.stderr)
        return 2  # 配置错误返回退出码 2
    # CLI 是最外层兜底边界：任何未分类异常都要转成中文提示和非零退出码。
    except Exception as error:  # noqa: BLE001 | 捕获所有其他异常
        print(f"运行失败: {error}", file=sys.stderr)
        return 1  # 运行失败返回退出码 1


if __name__ == "__main__":
    # 只有 `python -m agent_ch02.cli` 直接运行本文件时才启动；被测试 import 时不会自动执行。
    raise SystemExit(main())  # 调用 main 并以其返回值作为进程退出码
