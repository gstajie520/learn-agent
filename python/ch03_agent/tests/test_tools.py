"""工具注册表测试。

这是什么：测试工具注册、参数校验（prepare）、执行（invoke）、错误转换。
Java 类比：类似 ToolRegistryTest，验证工具查找、JSON 解析、参数校验逻辑。
为什么需要：工具调用是外部边界，必须保证未知工具、错误 JSON 都能转成稳定结果。
"""

from agent_ch03.core.commands import CommandResult
from agent_ch03.core.messages import tool_call
from agent_ch03.core.tools import ToolContext, ToolDefinition, ToolRegistry, tool_error
from agent_ch03.features.builtin_tools import create_shell_tool


def test_shell_result_mapping():
    registry = ToolRegistry()
    registry.register(create_shell_tool(type("Runner", (), {"run": lambda *_: CommandResult("partial", 1, True, False)})()))
    prepared = registry.prepare(tool_call("call", "shell", '{"command":"test"}'))
    result = registry.invoke(prepared, ToolContext(".", "test"))
    assert result.is_error is True
    assert result.error_code == "shell_timeout"


def test_unknown_and_invalid_json_are_tool_results():
    registry = ToolRegistry()
    registry.register(ToolDefinition("echo", "Echo", {"type": "object"}, "read", lambda _a, _c: tool_error("x", "x")))
    assert registry.prepare(tool_call("1", "missing", "{}")).error.error_code == "unknown_tool"
    assert registry.prepare(tool_call("2", "echo", "{")).error.error_code == "invalid_json"
