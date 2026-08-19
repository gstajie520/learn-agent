"""工具注册表。

Java 对照：`ToolRegistry` 类似按命令名保存 Handler 的注册表；`prepare` 是
进入 Service 前的 JSON/schema 校验，`invoke` 才真正执行副作用。
"""

from dataclasses import dataclass
import json
import re
from typing import Any, Protocol

from .messages import ToolCall
from .model import OpenAIToolSchema

EffectClass = str


@dataclass(frozen=True, slots=True)
class ToolContext:
    """程序提供给工具的受控运行环境。

    工具不能自己猜工作目录，而是由 AgentRunner 明确传入，类似 Java Service
    接收一个包含租户、用户和工作目录的上下文对象。
    """
    workspace: str
    identity: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具的统一返回值。

    工具失败也返回 ToolResult，而不是直接让整个 Agent 崩溃。
    这样模型能看到错误，并有机会换一种做法。
    """
    content: str
    is_error: bool
    error_code: str | None = None


def tool_success(content: str) -> ToolResult:
    return ToolResult(content, False)


def tool_error(error_code: str, message: str) -> ToolResult:
    if not error_code.strip():
        raise ValueError("tool error code must not be empty")
    return ToolResult(f"Error [{error_code}]: {message}", True, error_code)


class ToolHandler(Protocol):
    """工具处理器接口，作用类似 Java 的 CommandHandler。"""
    def __call__(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """一个完整工具定义：名称、说明、参数格式、副作用类型和执行函数。"""
    name: str
    description: str
    parameters: dict[str, Any]
    effect: EffectClass
    handler: ToolHandler


@dataclass(frozen=True, slots=True)
class PreparedToolCall:
    """已经完成查找、JSON 解析和参数校验的工具调用。

    如果准备失败，`error` 中已经放好了要返回给模型的错误结果，
    AgentRunner 不需要用异常分支处理未知工具或错误 JSON。
    """
    call: ToolCall
    definition: ToolDefinition | None = None
    arguments: dict[str, Any] | None = None
    error: ToolResult | None = None


class ToolRegistry:
    """集中管理所有模型可以调用的工具。"""
    def __init__(self, definitions: dict[str, ToolDefinition] | None = None, mutable: bool = True) -> None:
        self._definitions = dict(definitions or {})
        self._mutable = mutable

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def register(self, definition: ToolDefinition) -> None:
        """注册工具，并在启动阶段尽早发现重名或非法名称。"""
        if not self._mutable:
            raise ValueError("tool registry snapshot is immutable")
        if not re.fullmatch(r"[A-Za-z0-9_]+", definition.name):
            raise ValueError(f"invalid tool name: {definition.name}")
        if not definition.description.strip():
            raise ValueError("tool description must not be empty")
        if definition.name in self._definitions:
            raise ValueError(f"tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def snapshot(self) -> "ToolRegistry":
        """生成只读快照。

        模型这一轮看到哪些工具，就必须只能执行这些工具，不能在请求过程中偷偷变化。
        """
        return ToolRegistry(self._definitions, mutable=False)

    def openai_tools(self) -> tuple[OpenAIToolSchema, ...]:
        """把 Python 工具定义转换成模型能理解的 JSON Schema。"""
        return tuple(OpenAIToolSchema(d.name, d.description, d.parameters) for d in self._definitions.values())

    def prepare(self, call: ToolCall) -> PreparedToolCall:
        """准备工具调用，但绝不执行真实副作用。

        顺序是：按名字找工具 -> 把 arguments 字符串解析成 JSON -> 校验必须是对象
        -> 校验 shell 只允许 command 字段。任何错误都转换成 ToolResult。
        """
        definition = self._definitions.get(call.name)
        if definition is None:
            return PreparedToolCall(call, error=tool_error("unknown_tool", f"Unknown tool: {call.name}"))
        try:
            raw = json.loads(call.arguments)
        except json.JSONDecodeError:
            return PreparedToolCall(call, definition=definition, error=tool_error("invalid_json", "Tool arguments must be valid JSON"))
        if not isinstance(raw, dict):
            return PreparedToolCall(call, definition=definition, error=tool_error("invalid_arguments", "Tool arguments must be a JSON object"))
        if definition.name == "shell" and (set(raw) != {"command"} or not isinstance(raw.get("command"), str) or not raw["command"]):
            return PreparedToolCall(call, definition=definition, error=tool_error("invalid_arguments", "Tool arguments failed schema validation"))
        return PreparedToolCall(call, definition=definition, arguments=raw)

    def invoke(self, prepared: PreparedToolCall, context: ToolContext) -> ToolResult:
        """真正执行已经准备好的工具调用。

        这是副作用发生的位置。handler 抛出的异常会在这里统一转换，
        不把 Python 堆栈或敏感信息直接发给模型。
        """
        if prepared.error is not None:
            return prepared.error
        if prepared.definition is None or prepared.arguments is None:
            raise ValueError("prepared tool call is incomplete")
        try:
            result = prepared.definition.handler(prepared.arguments, context)
            if not isinstance(result, ToolResult):
                return tool_error("invalid_tool_result", "Tool handler returned an invalid result")
            if result.is_error and not result.error_code:
                return tool_error("invalid_tool_result", "Tool handler returned an invalid result")
            if not result.is_error and result.error_code is not None:
                return tool_error("invalid_tool_result", "Tool handler returned an invalid result")
            return result
        except Exception:
            return tool_error("tool_execution_error", "Tool execution failed")
