"""第 1 章的 PowerShell 工具。"""

from ..core.commands import CommandRunner
from ..core.tools import ToolDefinition, ToolRegistry, ToolContext, ToolResult, tool_error, tool_success


def create_shell_tool(command_runner: CommandRunner) -> ToolDefinition:
    """构造 shell 工具；handler 只依赖 CommandRunner 接口，便于注入 Fake。

    这个函数类似 Spring `@Bean` 方法：它把工具元数据和真正执行逻辑组装在一起。
    """
    def handler(arguments: dict[str, object], context: ToolContext) -> ToolResult:
        # prepare() 已经检查过 command，因此这里可以直接读取。
        command = arguments["command"]
        try:
            # 真正启动 PowerShell 的是 CommandRunner 实现，不是这个业务函数。
            result = command_runner.run(str(command), context.workspace)
        except Exception:
            # 不把操作系统的详细异常直接交给模型，避免泄漏本机路径等信息。
            return tool_error("shell_start_failed", "PowerShell process could not be started")

        # 即使命令没有任何输出，也返回明确文本，避免模型误以为漏掉了结果。
        output = result.output or "(no output)"
        if result.truncated:
            output += "\n[output truncated]"
        if result.timed_out:
            return tool_error("shell_timeout", output)
        if result.exit_code != 0:
            return tool_error("shell_failed", f"PowerShell exited with code {result.exit_code}\n{output}")
        return tool_success(output)

    return ToolDefinition(
        name="shell",
        description="Run a PowerShell command in the current workspace.",
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
