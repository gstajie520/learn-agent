"""工具注册表。

这是什么：工具管理系统，负责工具注册、查找、校验和执行
Java 类比：类似工具注册表 + 命令处理器模式
为什么需要：统一管理工具生命周期，隔离工具定义和执行逻辑

Java 对照：`ToolRegistry` 类似按命令名保存 Handler 的注册表；`prepare` 是
进入 Service 前的 JSON/schema 校验，`invoke` 才真正执行副作用。
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .messages import ToolCall
from .model import OpenAIToolSchema

EffectClass = str  # 副作用分类类型别名


@dataclass(frozen=True, slots=True)
class ToolContext:
    """程序提供给工具的受控运行环境。

    这是什么：工具执行上下文，封装运行时环境参数
    Java 类比：类似 record ExecutionContext(String workspace, String identity)
    为什么需要：统一传递执行环境，限制工具访问边界，支持多租户隔离

    工具不能自己猜工作目录，而是由 AgentRunner 明确传入，类似 Java Service
    接收一个包含租户、用户和工作目录的上下文对象。
    """
    workspace: str  # 工具执行时使用的受控工作目录。
    identity: str  # 发起调用的用户或 Agent 身份。


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具的统一返回值。

    这是什么：工具执行结果的值对象，统一成功和失败情况
    Java 类比：类似 record ToolResult(String content, boolean isError, String errorCode)
    为什么需要：统一结果格式，让失败也能返回结构化信息而非异常

    工具失败也返回 ToolResult，而不是直接让整个 Agent 崩溃。
    这样模型能看到错误，并有机会换一种做法。
    """
    content: str  # 给模型看的结果文本。
    is_error: bool  # True 表示执行失败，但仍然是合法的工具结果。
    error_code: str | None = None  # 机器可读错误码，例如 shell_timeout。


def tool_success(content: str) -> ToolResult:
    """创建成功结果；错误码必须保持为空。

    这是什么：成功结果的工厂方法
    Java 类比：类似 static ToolResult success(String content)
    为什么需要：简化成功结果创建，确保错误标志正确设置
    """
    return ToolResult(content, False)


def tool_error(error_code: str, message: str) -> ToolResult:
    """创建失败结果，让模型看到可理解的错误，而不是 Python 堆栈。

    这是什么：错误结果的工厂方法
    Java 类比：类似 static ToolResult error(String errorCode, String message)
    为什么需要：简化错误结果创建，提供结构化错误信息给模型
    """
    if not error_code.strip():  # 错误码不能为空
        raise ValueError("工具错误码不能为空")
    return ToolResult(f"工具执行错误 [{error_code}]: {message}", True, error_code)


class ToolHandler(Protocol):
    """工具处理器接口，作用类似 Java 的 CommandHandler。

    这是什么：工具执行函数的接口定义
    Java 类比：interface ToolHandler { ToolResult handle(Map<String, Object> args, ToolContext ctx); }
    为什么需要：定义工具执行契约，支持可调用对象和函数作为工具实现
    """
    def __call__(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """一个完整工具定义：名称、说明、参数格式、副作用类型和执行函数。

    这是什么：工具元数据的完整定义对象
    Java 类比：类似 record ToolDefinition(String name, String description, JsonSchema parameters, ...)
    为什么需要：封装工具的所有元数据和行为，便于注册和管理
    """
    name: str  # 注册表中的唯一名称。
    description: str  # 发送给模型的工具说明。
    parameters: dict[str, Any]  # JSON Schema 参数约束。
    effect: EffectClass  # 副作用分类，当前为 read/write/execute/external 之一。
    handler: ToolHandler  # 参数校验通过后真正执行的函数。
    validator: Callable[[dict[str, Any]], bool] | None = None  # 执行前的严格参数校验器。


@dataclass(frozen=True, slots=True)
class PreparedToolCall:
    """已经完成查找、JSON 解析和参数校验的工具调用。

    这是什么：已准备好的工具调用对象，封装准备阶段的结果
    Java 类比：类似 record PreparedToolCall(ToolCall call, ToolDefinition definition, Map args, ToolResult error)
    为什么需要：分离准备和执行阶段，让准备失败也能优雅返回错误

    如果准备失败，`error` 中已经放好了要返回给模型的错误结果，
    AgentRunner 不需要用异常分支处理未知工具或错误 JSON。
    """
    call: ToolCall  # 模型原始调用，必须保留 ID。
    definition: ToolDefinition | None = None  # 找到的工具定义。
    arguments: dict[str, Any] | None = None  # JSON 解析并校验后的参数。
    error: ToolResult | None = None  # 准备阶段失败时直接回填的错误。


class ToolRegistry:
    """集中管理所有模型可以调用的工具。

    这是什么：工具注册表，管理工具的注册、查找和执行
    Java 类比：类似 @Component class ToolRegistry，维护 Map<String, ToolDefinition>
    为什么需要：集中管理工具生命周期，提供快照隔离，支持动态工具集
    """

    def __init__(self, definitions: dict[str, ToolDefinition] | None = None, mutable: bool = True) -> None:
        """初始化工具注册表。

        这是什么：构造器，初始化工具映射表
        Java 类比：类似构造器复制传入的 Map 以防外部修改
        为什么需要：隔离内部状态，支持快照模式
        """
        # 复制一份字典，避免外部继续修改传入的 definitions 影响本注册表。
        # Java 对照：类似构造器里 new HashMap<>(definitions)。
        self._definitions = dict(definitions or {})  # 复制工具定义字典
        # True 表示启动装配阶段允许 register；快照会改成 False。
        self._mutable = mutable  # 是否允许修改

    @property
    def names(self) -> tuple[str, ...]:
        """返回已注册工具名的不可变快照，便于日志和测试查看。

        这是什么：工具名称列表的只读访问器
        Java 类比：类似 public List<String> getToolNames() { return List.copyOf(names); }
        为什么需要：提供只读视图，避免暴露内部字典
        """
        return tuple(self._definitions)  # 返回工具名称的不可变元组

    def register(self, definition: ToolDefinition) -> None:
        """注册工具，并在启动阶段尽早发现重名或非法名称。

        这是什么：工具注册方法，添加工具到注册表
        Java 类比：类似 public void register(ToolDefinition definition) throws ValidationException
        为什么需要：集中管理工具，启动时验证配置，防止运行时冲突
        """
        if not self._mutable:  # 快照不可修改
            raise ValueError("工具注册表快照不可修改")
        if not re.fullmatch(r"[A-Za-z0-9_]+", definition.name):  # 验证工具名称格式
            raise ValueError(f"工具名称不合法: {definition.name}")
        if not definition.description.strip():  # 验证描述非空
            raise ValueError("工具描述不能为空")
        if definition.name in self._definitions:  # 检查重复注册
            raise ValueError(f"工具已经注册过: {definition.name}")
        self._definitions[definition.name] = definition  # 添加到注册表

    def snapshot(self) -> "ToolRegistry":
        """生成只读快照。

        这是什么：创建不可变快照的方法
        Java 类比：类似 public ToolRegistry snapshot() { return new ToolRegistry(definitions, false); }
        为什么需要：保证单次请求中工具集不变，避免并发修改

        模型这一轮看到哪些工具，就必须只能执行这些工具，不能在请求过程中偷偷变化。
        """
        return ToolRegistry(self._definitions, mutable=False)  # 创建只读副本

    def openai_tools(self) -> tuple[OpenAIToolSchema, ...]:
        """把 Python 工具定义转换成模型能理解的 JSON Schema。

        这是什么：工具定义转换方法，生成模型可识别的格式
        Java 类比：类似 public List<ToolSchema> toOpenAIFormat()
        为什么需要：适配 OpenAI API 格式，将内部定义转换为外部协议
        """
        return tuple(OpenAIToolSchema(d.name, d.description, d.parameters) for d in self._definitions.values())  # 转换为 OpenAI 格式

    def prepare(self, call: ToolCall) -> PreparedToolCall:
        """准备工具调用，但绝不执行真实副作用。

        这是什么：工具调用准备方法，查找、解析和验证但不执行
        Java 类比：类似 public PreparedToolCall prepare(ToolCall call)
        为什么需要：分离准备和执行阶段，让准备失败能返回结构化错误而非异常
        """

        # 顺序是：按名字找工具 -> 把 arguments 字符串解析成 JSON -> 校验必须是对象
        # -> 校验 shell 只允许 command 字段。任何错误都转换成 ToolResult。
        definition = self._definitions.get(call.name)  # 根据名称查找工具定义
        if definition is None:  # 工具不存在
            return PreparedToolCall(call, error=tool_error("unknown_tool", f"找不到工具: {call.name}"))
        try:
            raw = json.loads(call.arguments)  # 解析 JSON 参数
        except json.JSONDecodeError:  # JSON 格式错误
            return PreparedToolCall(call, definition=definition, error=tool_error("invalid_json", "工具参数必须是合法 JSON"))
        if not isinstance(raw, dict):  # 参数必须是对象
            return PreparedToolCall(call, definition=definition, error=tool_error("invalid_arguments", "工具参数必须是 JSON 对象"))
        if definition.validator is not None and not definition.validator(raw):  # 自定义验证器检查
            return PreparedToolCall(call, definition=definition, error=tool_error("invalid_arguments", "工具参数没有通过格式校验"))
        return PreparedToolCall(call, definition=definition, arguments=raw)  # 准备成功

    def invoke(self, prepared: PreparedToolCall, context: ToolContext) -> ToolResult:
        """真正执行已经准备好的工具调用。

        这是什么：工具执行方法，调用工具处理器产生副作用
        Java 类比：类似 public ToolResult invoke(PreparedToolCall prepared, ToolContext context)
        为什么需要：执行实际操作，统一处理异常，保护模型不受实现细节污染

        这是副作用发生的位置。handler 抛出的异常会在这里统一转换，
        不把 Python 堆栈或敏感信息直接发给模型。
        """
        if prepared.error is not None:  # 准备阶段已有错误
            return prepared.error
        if prepared.definition is None or prepared.arguments is None:  # 不完整的准备结果
            raise ValueError("准备好的工具调用不完整")
        try:
            result = prepared.definition.handler(prepared.arguments, context)  # 调用工具处理器
            if not isinstance(result, ToolResult):  # 验证返回类型
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")
            if result.is_error and not result.error_code:  # 错误结果必须有错误码
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")
            if not result.is_error and result.error_code is not None:  # 成功结果不应有错误码
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")
            return result  # 返回有效结果
        # handler 是可插拔的外部代码，所有异常都要在注册表边界转换成稳定结果。
        except Exception:  # noqa: BLE001 | 捕获所有执行异常
            return tool_error("tool_execution_error", "工具执行失败")  # 转换为结构化错误
