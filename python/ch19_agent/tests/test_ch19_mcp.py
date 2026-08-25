"""第十九章 MCP 动态工具池的离线验收。"""

from __future__ import annotations

import json

import pytest

from agent_ch19.core.tools import ToolContext, ToolRegistry
from agent_ch19.features.mcp_tools import (
    McpCallResult,
    McpContractError,
    McpPublishedTool,
    McpRuntime,
    McpServerSpec,
    McpToolPolicy,
)


class FakeConnection:
    """不启动进程的 MCP fake，便于验证 Runtime 状态迁移。"""

    def __init__(self, tools: tuple[McpPublishedTool, ...] | None = None) -> None:
        self.tools = tools or (
            McpPublishedTool(
                "lookup",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "查询演示数据",
            ),
        )
        self.close_calls = 0
        self.call_calls = 0

    def list_tools(self) -> tuple[McpPublishedTool, ...]:
        """返回固定远程工具声明。"""
        return self.tools

    def call_tool(
        self, name: str, arguments: dict[str, object], timeout_seconds: float
    ) -> McpCallResult:
        """返回固定远程结果。"""
        self.call_calls += 1
        return McpCallResult(
            ({"type": "text", "text": json.dumps(arguments)},), {"name": name}, False
        )

    def wait_for_failure(self) -> None:
        """fake 不主动终止。"""

    def close(self) -> None:
        """记录关闭次数。"""
        self.close_calls += 1


class FakeFactory:
    """总是交付同一个 fake connection。"""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.open_calls = 0

    def open(self, spec: McpServerSpec) -> FakeConnection:
        """记录 open 并返回连接。"""
        self.open_calls += 1
        return self.connection


def make_runtime(connection: FakeConnection) -> tuple[McpRuntime, ToolRegistry]:
    """创建一个只允许 lookup 的 fake MCP Runtime。"""
    runtime = McpRuntime(
        (McpServerSpec("fake", "unused", (), (McpToolPolicy("lookup", "read"),)),),
        FakeFactory(connection),
    )
    registry = ToolRegistry()
    runtime.install(registry)
    return runtime, registry


def test_connect_registers_prefixed_tool_and_disconnect_withdraws_it() -> None:
    """连接成功后动态工具出现，断开后同一对象被撤销。"""
    connection = FakeConnection()
    runtime, registry = make_runtime(connection)
    connected = runtime.connect("fake")
    assert not connected.is_error
    assert "mcp__fake__lookup" in registry.names
    disconnected = runtime.disconnect("fake")
    assert not disconnected.is_error
    assert "mcp__fake__lookup" not in registry.names
    assert connection.close_calls == 1


def test_policy_mismatch_is_atomic_and_closes_connection() -> None:
    """远程声明与本地 allowlist 不一致时，一个工具也不能发布。"""
    connection = FakeConnection((McpPublishedTool("other", {"type": "object"}),))
    runtime, registry = make_runtime(connection)
    result = runtime.connect("fake")
    assert result.is_error
    assert result.error_code == "mcp_connection_failed"
    assert registry.names == ("connect_mcp", "disconnect_mcp")
    assert connection.close_calls == 1


def test_external_schema_reference_is_rejected() -> None:
    """远程 schema 不能通过外部 $ref 拉取额外资源。"""
    connection = FakeConnection(
        (McpPublishedTool("lookup", {"type": "object", "$ref": "https://evil.test/schema"}),)
    )
    runtime, registry = make_runtime(connection)
    result = runtime.connect("fake")
    assert result.is_error
    assert "mcp__fake__lookup" not in registry.names


def test_dynamic_tool_handler_calls_remote_connection() -> None:
    """动态工具 handler 通过远程连接调用，而不是直接暴露 fake。"""
    connection = FakeConnection()
    runtime, registry = make_runtime(connection)
    assert not runtime.connect("fake").is_error
    prepared = registry.prepare(
        type(
            "Call", (), {"id": "1", "name": "mcp__fake__lookup", "arguments": '{"query":"needle"}'}
        )()
    )
    result = registry.invoke(prepared, ToolContext(".", "user"))
    assert not result.is_error
    assert connection.call_calls == 1


def test_invalid_alias_is_rejected() -> None:
    """alias 只能是稳定的小写标识符。"""
    with pytest.raises(McpContractError):
        McpServerSpec("Bad Alias", "unused", (), ())
