"""工具模块的单元测试：验证工具注册、执行和错误处理逻辑。

这是什么：测试工具定义、调用和结果映射功能
Java 类比：类似 ToolRegistryTest 单元测试类
为什么需要：确保工具能正确注册到注册表，且执行结果符合 OpenAI 工具规范
"""

from agent_ch08.core.commands import CommandResult
from agent_ch08.core.messages import tool_call
from agent_ch08.core.tools import ToolContext, ToolDefinition, ToolRegistry, tool_error
from agent_ch08.features.builtin_tools import create_shell_tool


def test_shell_result_mapping():
    registry = ToolRegistry()
    registry.register(
        create_shell_tool(
            type("Runner", (), {"run": lambda *_: CommandResult("partial", 1, True, False)})()
        )
    )
    prepared = registry.prepare(tool_call("call", "shell", '{"command":"test"}'))
    result = registry.invoke(prepared, ToolContext(".", "test"))
    assert result.is_error is True
    assert result.error_code == "shell_timeout"


def test_unknown_and_invalid_json_are_tool_results():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "echo", "Echo", {"type": "object"}, "read", lambda _a, _c: tool_error("x", "x")
        )
    )
    assert registry.prepare(tool_call("1", "missing", "{}")).error.error_code == "unknown_tool"
    assert registry.prepare(tool_call("2", "echo", "{")).error.error_code == "invalid_json"
