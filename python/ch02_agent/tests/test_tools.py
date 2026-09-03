"""工具注册表与执行测试。

这是什么：工具系统核心功能的单元测试
Java 类比：类似 ToolRegistryTest 测试类
为什么需要：验证工具注册、调用准备、结果映射和错误处理
"""

from agent_ch02.core.commands import CommandResult
from agent_ch02.core.messages import tool_call
from agent_ch02.core.tools import ToolContext, ToolDefinition, ToolRegistry, tool_error
from agent_ch02.features.builtin_tools import create_shell_tool


def test_shell_result_mapping():
    """验证 shell 工具的结果映射逻辑。

    这是什么：命令执行结果转换测试
    Java 类比：类似 @Test void testShellResultMapping()
    为什么需要：确保命令超时、非零退出码等状态正确映射为工具错误
    """
    registry = ToolRegistry()  # 创建工具注册表
    registry.register(create_shell_tool(type("Runner", (), {"run": lambda *_: CommandResult("partial", 1, True, False)})()))  # 注册返回超时结果的假执行器
    prepared = registry.prepare(tool_call("call", "shell", '{"command":"test"}'))  # 准备工具调用
    result = registry.invoke(prepared, ToolContext(".", "test"))  # 执行工具
    assert result.is_error is True  # 应该是错误结果
    assert result.error_code == "shell_timeout"  # 错误码应为超时


def test_unknown_and_invalid_json_are_tool_results():
    """验证未知工具和无效 JSON 返回工具错误结果。

    这是什么：工具调用错误处理测试
    Java 类比：类似 @Test void testToolCallErrorHandling()
    为什么需要：确保工具系统将调用错误转换为标准工具结果，而非抛出异常
    """
    registry = ToolRegistry()  # 创建工具注册表
    registry.register(ToolDefinition("echo", "Echo", {"type": "object"}, "read", lambda _a, _c: tool_error("x", "x")))  # 注册测试工具
    assert registry.prepare(tool_call("1", "missing", "")).error.error_code == "unknown_tool"  # 未知工具返回错误
    assert registry.prepare(tool_call("2", "echo", "{")).error.error_code == "invalid_json"  # 无效 JSON 返回错误
