"""工具注册表。

这是什么：工具的注册、准备、调用和定义管理
Java 类比：@Service class ToolRegistry + CommandHandler 接口
为什么需要：集中管理所有可用工具，提供统一的调用接口和参数校验

Java 对照：`ToolRegistry` 类似按命令名保存 Handler 的注册表；`prepare` 是
进入 Service 前的 JSON/schema 校验，`invoke` 才真正执行副作用。
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .messages import ToolCall
from .model import OpenAIToolSchema

EffectClass = str  # 工具的副作用分类，用于权限决策


@dataclass(frozen=True, slots=True)
class ToolContext:
    """程序提供给工具的受控运行环境。

    这是什么：传递给工具执行器的上下文对象
    Java 类比：record ToolContext(String workspace, String identity)
    为什么需要：封装工具执行所需的环境信息（工作目录、身份），避免工具自行猜测

    工具不能自己猜工作目录，而是由 AgentRunner 明确传入，类似 Java Service
    接收一个包含租户、用户和工作目录的上下文对象。
    """

    workspace: str  # 工具执行时使用的受控工作目录。
    identity: str  # 发起调用的用户或 Agent 身份。


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具的统一返回值。

    这是什么：工具执行后的结果对象，成功或失败都用此类型
    Java 类比：record ToolResult(String content, boolean isError, String errorCode)
    为什么需要：统一工具的返回格式，让模型能看到错误并自行调整策略

    工具失败也返回 ToolResult，而不是直接让整个 Agent 崩溃。
    这样模型能看到错误，并有机会换一种做法。
    """

    content: str  # 给模型看的结果文本。
    is_error: bool  # True 表示执行失败，但仍然是合法的工具结果。
    error_code: str | None = None  # 机器可读错误码，例如 shell_timeout。


def tool_success(content: str) -> ToolResult:
    """创建成功结果；错误码必须保持为空。

    这是什么：工具成功结果的工厂方法
    Java 类比：public static ToolResult success(String content)
    为什么需要：提供类型安全的成功结果构造，确保错误码为空
    """
    return ToolResult(content, False)


def tool_error(error_code: str, message: str) -> ToolResult:
    """创建失败结果，让模型看到可理解的错误，而不是 Python 堆栈。"""
    if not error_code.strip():
        raise ValueError("工具错误码不能为空")
    return ToolResult(f"工具执行错误 [{error_code}]: {message}", True, error_code)


def copy_tool_result(result: ToolResult) -> ToolResult:
    """复制工具结果，切断 Hook 或 handler 持有的原对象引用。"""
    if not isinstance(result, ToolResult):
        raise TypeError("只能复制 ToolResult")
    return ToolResult(result.content, result.is_error, result.error_code)


ToolHandler = Callable[[Mapping[str, Any], ToolContext], ToolResult]
"""工具处理器签名，作用类似 Java 的 `BiFunction<Arguments, Context, Result>`。"""


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """一个完整工具定义：名称、说明、参数格式、副作用类型和执行函数。"""

    name: str  # 注册表中的唯一名称。
    description: str  # 发送给模型的工具说明。
    parameters: dict[str, Any]  # JSON Schema 参数约束。
    effect: EffectClass  # 副作用分类，当前为 read/write/execute/external 之一。
    handler: ToolHandler  # 参数校验通过后真正执行的函数。
    validator: Callable[[Mapping[str, Any]], bool] | None = None  # 执行前的严格参数校验器。


@dataclass(frozen=True, slots=True)
class PreparedToolCall:
    """已经完成查找、JSON 解析和参数校验的工具调用。

    如果准备失败，`error` 中已经放好了要返回给模型的错误结果，
    AgentRunner 不需要用异常分支处理未知工具或错误 JSON。
    """

    call: ToolCall  # 模型原始调用，必须保留 ID。
    definition: ToolDefinition | None = None  # 找到的工具定义。
    arguments: Mapping[str, Any] | None = None  # JSON 解析、校验并冻结后的参数。
    error: ToolResult | None = None  # 准备阶段失败时直接回填的错误。


def _freeze_json(value: Any) -> Any:
    """递归冻结 JSON 数据。

    Java 对照：类似把 Map/List 递归转换成 `Map.copyOf` 和 `List.copyOf`。
    `MappingProxyType` 是 Python 标准库提供的只读 Map 视图。
    """
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def copy_prepared_tool_call(
    prepared: PreparedToolCall,
    *,
    definition: ToolDefinition | None = None,
) -> PreparedToolCall:
    """复制并冻结 prepared call，同时按需保留可信工具定义的对象身份。"""
    if not isinstance(prepared, PreparedToolCall):
        raise TypeError("只能复制 PreparedToolCall")
    copied_arguments = (
        None if prepared.arguments is None else _freeze_json(dict(prepared.arguments))
    )
    copied_error = None if prepared.error is None else copy_tool_result(prepared.error)
    return PreparedToolCall(
        ToolCall(prepared.call.id, prepared.call.name, prepared.call.arguments),
        definition if definition is not None else prepared.definition,
        copied_arguments,
        copied_error,
    )


class ToolRegistry:
    """集中管理所有模型可以调用的工具。"""

    def __init__(
        self, definitions: dict[str, ToolDefinition] | None = None, mutable: bool = True
    ) -> None:
        # 复制一份字典，避免外部继续修改传入的 definitions 影响本注册表。
        # Java 对照：类似构造器里 new HashMap<>(definitions)。
        self._definitions = dict(definitions or {})
        # True 表示启动装配阶段允许 register；快照会改成 False。
        self._mutable = mutable

    @property
    def names(self) -> tuple[str, ...]:
        """返回已注册工具名的不可变快照，便于日志和测试查看。"""
        return tuple(self._definitions)

    def register(self, definition: ToolDefinition) -> None:
        """注册工具，并在启动阶段尽早发现重名或非法名称。"""
        if not self._mutable:
            raise ValueError("工具注册表快照不可修改")
        if not re.fullmatch(r"[A-Za-z0-9_]+", definition.name):
            raise ValueError(f"工具名称不合法: {definition.name}")
        if not definition.description.strip():
            raise ValueError("工具描述不能为空")
        if definition.name in self._definitions:
            raise ValueError(f"工具已经注册过: {definition.name}")
        self._definitions[definition.name] = definition

    def snapshot(self) -> "ToolRegistry":
        """生成只读快照。

        模型这一轮看到哪些工具，就必须只能执行这些工具，不能在请求过程中偷偷变化。
        """
        return ToolRegistry(self._definitions, mutable=False)

    def openai_tools(self) -> tuple[OpenAIToolSchema, ...]:
        """把 Python 工具定义转换成模型能理解的 JSON Schema。"""
        return tuple(
            OpenAIToolSchema(d.name, d.description, d.parameters)
            for d in self._definitions.values()
        )

    def prepare(self, call: ToolCall) -> PreparedToolCall:
        """准备工具调用，但绝不执行真实副作用。

        顺序是：按名字找工具 -> 把 arguments 字符串解析成 JSON -> 校验必须是对象
        -> 校验 shell 只允许 command 字段。任何错误都转换成 ToolResult。
        """
        definition = self._definitions.get(call.name)
        if definition is None:
            return PreparedToolCall(
                call, error=tool_error("unknown_tool", f"找不到工具: {call.name}")
            )
        try:
            raw = json.loads(call.arguments)
        except json.JSONDecodeError:
            return PreparedToolCall(
                call,
                definition=definition,
                error=tool_error("invalid_json", "工具参数必须是合法 JSON"),
            )
        if not isinstance(raw, dict):
            return PreparedToolCall(
                call,
                definition=definition,
                error=tool_error("invalid_arguments", "工具参数必须是 JSON 对象"),
            )
        if definition.validator is not None and not definition.validator(raw):
            return PreparedToolCall(
                call,
                definition=definition,
                error=tool_error("invalid_arguments", "工具参数没有通过格式校验"),
            )
        # prepare 成功后立刻冻结参数。后面的 Hook、审批器和 handler 共享这份快照，
        # 外部代码无法在异步等待期间偷偷修改参数。
        return copy_prepared_tool_call(PreparedToolCall(call, definition=definition, arguments=raw))

    def invoke(self, prepared: PreparedToolCall, context: ToolContext) -> ToolResult:
        """真正执行已经准备好的工具调用。

        这是副作用发生的位置。handler 抛出的异常会在这里统一转换，
        不把 Python 堆栈或敏感信息直接发给模型。
        """
        if prepared.error is not None:
            return prepared.error
        if prepared.definition is None or prepared.arguments is None:
            raise ValueError("准备好的工具调用不完整")
        try:
            result = prepared.definition.handler(prepared.arguments, context)
            if not isinstance(result, ToolResult):
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")
            if result.is_error and not result.error_code:
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")
            if not result.is_error and result.error_code is not None:
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")
            return result
        # handler 是可插拔的外部代码，所有异常都要在注册表边界转换成稳定结果。
        except Exception:  # noqa: BLE001
            return tool_error("tool_execution_error", "工具执行失败")
