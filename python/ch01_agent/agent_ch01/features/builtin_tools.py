"""第 1 章的 PowerShell 工具。"""

from ..core.commands import CommandRunner
from ..core.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)


def create_shell_tool(command_runner: CommandRunner) -> ToolDefinition:
    """构造 shell 工具；handler 只依赖 CommandRunner 接口，便于注入 Fake。

    这个函数类似 Spring `@Bean` 方法：它把工具元数据和真正执行逻辑组装在一起。
    """
    def handler(arguments: dict[str, object], context: ToolContext) -> ToolResult:
        # 这是函数内部定义的闭包：它记住外层传入的 command_runner。
        # Java 中通常会写一个 ShellHandler 类并把 runner 放进成员变量；
        # Python 用闭包就能表达同样的“保存依赖再执行”关系。
        # prepare() 已经检查过 command，因此这里可以直接读取。
        command = arguments["command"]
        try:
            # 真正启动 PowerShell 的是 CommandRunner 实现，不是这个业务函数。
            result = command_runner.run(str(command), context.workspace)
        # CommandRunner 可能由不同适配器实现，这里统一收敛所有启动异常。
        except Exception:  # noqa: BLE001
            # 不把操作系统的详细异常直接交给模型，避免泄漏本机路径等信息。
            return tool_error("shell_start_failed", "无法启动 PowerShell 进程")

        # 即使命令没有任何输出，也返回明确文本，避免模型误以为漏掉了结果。
        output = result.output or "(no output)"
        if result.truncated:
            output += "\n[output truncated]"
        if result.timed_out:
            return tool_error("shell_timeout", output)
        if result.exit_code != 0:
            return tool_error("shell_failed", f"PowerShell 退出码为 {result.exit_code}\n{output}")
        return tool_success(output)

    return ToolDefinition(
        name="shell",
        description="在当前工作目录执行 PowerShell 命令。",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string", "minLength": 1}},
            "required": ["command"],
            "additionalProperties": False,
        },
        effect="execute",
        handler=handler,
    )


def create_chapter_one_tools(command_runner: CommandRunner) -> ToolRegistry:
    """集中注册第 1 章允许模型使用的所有工具。目前只有 shell。"""
    registry = ToolRegistry()
    registry.register(create_shell_tool(command_runner))
    return registry
