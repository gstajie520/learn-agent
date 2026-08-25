"""MCP 动态工具池。

Java 对照：``McpRuntime`` 是领域 Service，``McpConnection`` 是 Port，
``McpConnectionFactory`` 是 Adapter 工厂。连接成功前只暴露管理工具；
tools/list、allowlist 和 schema 全部通过后，才原子注册远程工具。
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)


class McpContractError(RuntimeError):
    """本地配置或远程 MCP 声明违反契约。"""


class McpTransportError(RuntimeError):
    """连接、初始化或请求传输失败。"""


class McpTimeoutError(McpTransportError):
    """远程调用超时。"""


@dataclass(frozen=True, slots=True)
class McpToolPolicy:
    """本地 allowlist 中一个远程工具的 effect。"""

    remote_name: str  # tools/list 返回的原始名称，必须精确匹配。
    effect: str  # read/write/execute/external，只能由本地配置决定。

    def __post_init__(self) -> None:
        """校验策略字段。"""
        if not self.remote_name or self.remote_name != self.remote_name.strip():
            raise McpContractError("MCP tool policy remote_name 不能为空或带空格")
        if self.effect not in {"read", "write", "execute", "external"}:
            raise McpContractError("MCP tool policy effect 无效")


@dataclass(frozen=True, slots=True)
class McpServerSpec:
    """一个本地允许连接的 MCP stdio Server 配置。"""

    alias: str  # 暴露给模型的短别名。
    command: str  # 子进程命令。
    args: tuple[str, ...]  # 不经过 shell 的参数数组。
    tool_policies: tuple[McpToolPolicy, ...]  # 远程工具 allowlist。
    startup_timeout_seconds: float = 10.0  # initialize/tools/list 的启动预算。
    tool_timeout_seconds: float = 30.0  # 单次 tools/call 预算。
    cwd: str | None = None  # 可选子进程工作目录。

    def __post_init__(self) -> None:
        """校验 alias、参数、policy 唯一性和超时。"""
        if re.fullmatch(r"[a-z][a-z0-9_]{0,31}", self.alias) is None:
            raise McpContractError("MCP server alias 格式无效")
        if not self.command.strip() or any(not isinstance(item, str) for item in self.args):
            raise McpContractError("MCP server command/args 无效")
        if len({policy.remote_name for policy in self.tool_policies}) != len(self.tool_policies):
            raise McpContractError("MCP tool policy 不能重复")
        if self.startup_timeout_seconds <= 0 or self.tool_timeout_seconds <= 0:
            raise McpContractError("MCP timeout 必须大于 0")


@dataclass(frozen=True, slots=True)
class McpPublishedTool:
    """远程 tools/list 的边界对象。"""

    name: str  # 远程原始工具名。
    input_schema: dict[str, Any]  # JSON Schema 对象。
    description: str = ""  # 远程描述，过长或空白会被本地处理。


@dataclass(frozen=True, slots=True)
class McpCallResult:
    """远程 tools/call 的结构化结果。"""

    content: tuple[dict[str, Any], ...]  # MCP content blocks。
    structured_content: dict[str, Any] | None  # 可选结构化结果。
    is_error: bool  # True 表示远程业务失败，不等同于传输失败。


class McpConnection(Protocol):
    """连接 Port；真实实现可以是 stdio JSON-RPC，测试使用 fake。"""

    def list_tools(self) -> tuple[McpPublishedTool, ...]: ...
    def call_tool(
        self, name: str, arguments: dict[str, Any], timeout_seconds: float
    ) -> McpCallResult: ...
    def wait_for_failure(self) -> None: ...
    def close(self) -> None: ...


class McpConnectionFactory(Protocol):
    """只在 initialize 成功后交付连接。"""

    def open(self, spec: McpServerSpec) -> McpConnection: ...


class SimpleMcpSchemaValidator:
    """不依赖第三方包的最小 JSON Schema 校验器，覆盖 object/properties/required。"""

    def compile(self, exposed_name: str, schema: dict[str, Any]):
        """把远程 schema 编译成同步谓词，并拒绝外部 $ref。"""
        if schema.get("type") != "object":
            raise McpContractError(f"MCP 工具 schema 必须是 object: {exposed_name}")
        if _has_external_ref(schema):
            raise McpContractError(f"MCP 工具 schema 含外部引用: {exposed_name}")

        def validate(value: Any) -> bool:
            if not isinstance(value, dict):
                return False
            required = schema.get("required", [])
            if not all(isinstance(item, str) and item in value for item in required):
                return False
            properties = schema.get("properties", {})
            if isinstance(properties, dict):
                for key, rule in properties.items():
                    if (
                        key in value
                        and isinstance(rule, dict)
                        and not _valid_type(value[key], rule.get("type"))
                    ):
                        return False
            return bool(schema.get("additionalProperties", True)) or set(value) <= set(properties)

        return validate


class McpRuntime:
    """把 allowlist Server 动态安装为 Lead 工具，并管理连接生命周期。"""

    def __init__(
        self,
        servers: tuple[McpServerSpec, ...],
        connection_factory: McpConnectionFactory,
        schema_validator: Any | None = None,
    ) -> None:
        """创建静态配置；远程工具必须等 connect 成功后才出现。"""
        if not servers or len({server.alias for server in servers}) != len(servers):
            raise McpContractError("MCP runtime 至少需要一个且 alias 不能重复")
        self._servers = {server.alias: server for server in servers}
        self._factory = connection_factory
        self._validator = schema_validator or SimpleMcpSchemaValidator()
        self._connections: dict[str, tuple[McpConnection, tuple[ToolDefinition, ...]]] = {}
        self._registry: ToolRegistry | None = None
        self._lock = threading.RLock()
        self._closed = False
        self._pending: list[McpConnection] = []

    @property
    def connected_aliases(self) -> tuple[str, ...]:
        """返回已完成发现和发布的 alias。"""
        with self._lock:
            return tuple(self._connections)

    @property
    def lead_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """返回仅供 Lead 使用的 connect/disconnect 管理工具。"""
        return (
            ToolDefinition(
                "connect_mcp",
                "连接本地 allowlist MCP server。",
                _alias_schema(),
                "external",
                lambda a, _c: self.connect(str(a["alias"])),
                _validate_alias,
                source="mcp:management",
            ),
            ToolDefinition(
                "disconnect_mcp",
                "断开 MCP server 并撤销其工具。",
                _alias_schema(),
                "external",
                lambda a, _c: self.disconnect(str(a["alias"])),
                _validate_alias,
                source="mcp:management",
            ),
        )

    def install(self, registry: ToolRegistry) -> None:
        """绑定一个 Lead registry，并安装两个管理工具。"""
        with self._lock:
            if self._registry is not None or self._closed:
                raise McpContractError("MCP runtime 已安装或已关闭")
            registry.register_many(list(self.lead_tool_definitions))
            self._registry = registry

    def connect(self, alias: str) -> ToolResult:
        """串行执行 open -> list -> policy/schema -> 批量注册。"""
        with self._lock:
            if self._closed:
                return tool_error("mcp_runtime_closed", "MCP runtime 正在关闭或已关闭")
            spec = self._servers.get(alias)
            if spec is None:
                return tool_error("unknown_mcp_server", f"未知 MCP server alias: {alias}")
            if alias in self._connections:
                return tool_error("mcp_already_connected", f"MCP server 已连接: {alias}")
            try:
                connection = self._factory.open(spec)
                published = connection.list_tools()
                definitions = self._build_definitions(spec, published)
                if self._registry is None:
                    raise McpContractError("MCP runtime 尚未安装 registry")
                stored = self._registry.register_many(list(definitions))
            except McpContractError as error:
                self._cleanup(connection if "connection" in locals() else None)
                return tool_error("mcp_connection_failed", str(error))
            except Exception:  # noqa: BLE001
                self._cleanup(connection if "connection" in locals() else None)
                return tool_error("mcp_connection_failed", f"MCP server connect 失败: {alias}")
            self._connections[alias] = (connection, tuple(stored))
            return tool_success(
                json.dumps(
                    {
                        "server_alias": alias,
                        "status": "connected",
                        "tools": [item.name for item in stored],
                    },
                    ensure_ascii=False,
                )
            )

    def disconnect(self, alias: str) -> ToolResult:
        """先撤销动态工具，再关闭连接；关闭失败加入 pending 队列。"""
        with self._lock:
            state = self._connections.pop(alias, None)
            if state is None:
                return tool_error("mcp_not_connected", f"MCP server 未连接: {alias}")
            connection, definitions = state
            if self._registry is not None:
                self._registry.unregister_many(definitions)
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                self._pending.append(connection)
                return tool_error("mcp_disconnect_failed", "MCP 工具已撤销，但连接清理待重试")
            return tool_success(
                json.dumps(
                    {
                        "server_alias": alias,
                        "status": "disconnected",
                        "tools": [item.name for item in definitions],
                    },
                    ensure_ascii=False,
                )
            )

    def close(self) -> None:
        """撤销所有动态工具并逆序关闭连接；失败连接下次继续重试。"""
        with self._lock:
            self._closed = True
            states = list(self._connections.values())[::-1]
            self._connections.clear()
            if self._registry is not None:
                for _connection, definitions in states:
                    self._registry.unregister_many(definitions)
            failures: list[Exception] = []
            for connection, _definitions in states + [(item, ()) for item in self._pending]:
                try:
                    connection.close()
                except Exception as error:  # noqa: BLE001
                    failures.append(error)
            self._pending.clear()
            if failures:
                raise RuntimeError("MCP runtime 关闭失败")

    def _build_definitions(
        self, spec: McpServerSpec, published: tuple[McpPublishedTool, ...]
    ) -> tuple[ToolDefinition, ...]:
        """要求 tools/list 与 policy 精确匹配，并生成带 alias 的本地定义。"""
        policies = {policy.remote_name: policy for policy in spec.tool_policies}
        if len({tool.name for tool in published}) != len(published) or set(policies) != {
            tool.name for tool in published
        }:
            raise McpContractError(f"MCP published tools 与本地 policy 不匹配: {spec.alias}")
        definitions: list[ToolDefinition] = []
        for tool in published:
            exposed = _exposed_name(spec.alias, tool.name)
            validator = self._validator.compile(exposed, tool.input_schema)
            description = (
                tool.description.strip() or f"MCP tool {tool.name} published by {spec.alias}."
            )
            if len(description) > 1024:
                raise McpContractError("MCP tool description 过长")
            policy = policies[tool.name]

            def handler(
                args: Mapping[str, Any],
                _context: ToolContext,
                alias: str = spec.alias,
                remote: str = tool.name,
            ) -> ToolResult:
                return self._invoke(alias, remote, dict(args))

            def validate(args: Mapping[str, Any], check: Any = validator) -> bool:
                return bool(check(dict(args)))

            definitions.append(
                ToolDefinition(
                    exposed,
                    description,
                    tool.input_schema,
                    policy.effect,
                    handler,
                    validate,
                    source=f"mcp:{spec.alias}:{tool.name}",
                )
            )
        return tuple(definitions)

    def _invoke(self, alias: str, remote: str, arguments: dict[str, Any]) -> ToolResult:
        """调用远程工具；超时/传输错误撤销连接，远程业务错误只影响本次结果。"""
        with self._lock:
            state = self._connections.get(alias)
        if state is None:
            return tool_error("mcp_not_connected", "MCP server 已断开")
        connection, _definitions = state
        try:
            result = connection.call_tool(
                remote, arguments, self._servers[alias].tool_timeout_seconds
            )
        except McpTimeoutError:
            self.disconnect(alias)
            return tool_error("mcp_timeout", "MCP 工具调用超时")
        except McpTransportError:
            self.disconnect(alias)
            return tool_error("mcp_connection_lost", "MCP 连接在调用期间断开")
        if result.is_error:
            return tool_error("mcp_remote_error", "MCP server 返回了工具错误")
        return tool_success(
            json.dumps(
                {
                    "content": result.content,
                    "server_alias": alias,
                    "status": "ok",
                    "structured_content": result.structured_content,
                    "tool": remote,
                },
                ensure_ascii=False,
            )
        )

    def _cleanup(self, connection: McpConnection | None) -> None:
        """连接发布失败时尽力关闭临时资源。"""
        if connection is None:
            return
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            self._pending.append(connection)


def _alias_schema() -> dict[str, Any]:
    """返回管理工具输入 schema。"""
    return {
        "type": "object",
        "properties": {"alias": {"type": "string"}},
        "required": ["alias"],
        "additionalProperties": False,
    }


def _validate_alias(arguments: Mapping[str, Any]) -> bool:
    """校验 alias。"""
    return (
        set(arguments) == {"alias"}
        and isinstance(arguments["alias"], str)
        and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", arguments["alias"]) is not None
    )


def _exposed_name(alias: str, remote: str) -> str:
    """把远程名规范化为 mcp__alias__name。"""
    normalized = re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]+", "_", remote.strip().lower())).strip("_")
    if not normalized:
        raise McpContractError("MCP 工具名无法规范化")
    exposed = f"mcp__{alias}__{normalized}"
    if len(exposed) > 64:
        raise McpContractError("MCP 暴露工具名过长")
    return exposed


def _has_external_ref(value: Any) -> bool:
    """递归拒绝 $ref 指向文档外部。"""
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                not isinstance(nested, str) or not nested.startswith("#")
            ):
                return True
            if _has_external_ref(nested):
                return True
    elif isinstance(value, list):
        return any(_has_external_ref(item) for item in value)
    return False


def _valid_type(value: Any, expected: Any) -> bool:
    """覆盖教程常用 JSON Schema 基础类型。"""
    return (
        expected is None
        or (expected == "string" and isinstance(value, str))
        or (expected == "object" and isinstance(value, dict))
        or (expected == "array" and isinstance(value, list))
        or (expected == "boolean" and isinstance(value, bool))
        or (
            expected == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)
        )
    )
