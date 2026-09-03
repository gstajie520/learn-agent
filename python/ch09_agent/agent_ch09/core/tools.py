"""工具注册表。

Java 对照：`ToolRegistry` 类似按命令名保存 Handler 的注册表；`prepare` 是
进入 Service 前的 JSON/schema 校验，`invoke` 才真正执行副作用。

这是什么：工具的注册、准备和执行管理器
Java 类比：类似 Spring 的 HandlerMapping + HandlerAdapter 组合
为什么需要：集中管理工具定义，确保参数校验和执行的安全性
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .messages import ToolCall
from .model import OpenAIToolSchema

EffectClass = str  # 副作用分类标签


@dataclass(frozen=True, slots=True)
class ToolContext:
    """程序提供给工具的受控运行环境。

    这是什么：工具执行的上下文数据对象
    Java 类比：类似 record ToolContext(String workspace, String identity)
    为什么需要：工具不能自行决定工作目录和身份，必须由框架统一管理

    参数：
        workspace: 工具执行时使用的受控工作目录
        identity: 发起调用的用户或 Agent 身份
    """

    workspace: str  # 工具允许操作的目录
    identity: str  # 调用者身份标识


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具的统一返回值，成功和失败都使用这个类型。

    这是什么：工具执行结果的标准封装
    Java 类比：类似 record ToolResult(String content, boolean isError, String errorCode)
    为什么需要：工具失败也返回 ToolResult，而不是直接让整个 Agent 崩溃，
                让模型能看到错误并换一种做法

    参数：
        content: 给模型看的结果文本
        is_error: True 表示执行失败，但仍然是合法的工具结果
        error_code: 机器可读错误码，例如 shell_timeout
    """

    content: str  # 结果内容
    is_error: bool  # 是否错误
    error_code: str | None = None  # 错误码


def tool_success(content: str) -> ToolResult:
    """创建成功结果；错误码必须保持为空。

    这是什么：工具成功结果的工厂方法
    Java 类比：类似 ToolResult.success(String content)
    为什么需要：确保成功结果的格式一致，error_code 自动为空

    参数：
        content: 成功执行的结果文本

    返回：
        ToolResult: 标记为成功的结果对象
    """
    return ToolResult(content, False)


def tool_error(error_code: str, message: str) -> ToolResult:
    """创建失败结果，让模型看到可理解的错误，而不是 Python 堆栈。

    这是什么：工具错误结果的工厂方法
    Java 类比：类似 ToolResult.error(String code, String message)
    为什么需要：统一错误格式，避免暴露内部实现细节给模型

    参数：
        error_code: 机器可读的错误码（不能为空）
        message: 人类可读的错误描述

    返回：
        ToolResult: 标记为失败的结果对象

    异常：
        ValueError: 错误码为空
    """
    if not error_code.strip():
        raise ValueError("工具错误码不能为空")
    return ToolResult(f"工具执行错误 [{error_code}]: {message}", True, error_code)


def copy_tool_result(result: ToolResult) -> ToolResult:
    """复制工具结果，切断 Hook 或 handler 持有的原对象引用。

    这是什么：工具结果的深拷贝方法
    Java 类比：类似 ToolResult.copy() 或防御性拷贝
    为什么需要：确保 Hook 不能修改已经产生的结果

    参数：
        result: 原始工具结果

    返回：
        ToolResult: 新的结果对象

    异常：
        TypeError: 参数不是 ToolResult 类型
    """
    if not isinstance(result, ToolResult):
        raise TypeError("只能复制 ToolResult")
    return ToolResult(result.content, result.is_error, result.error_code)


ToolHandler = Callable[[Mapping[str, Any], ToolContext], ToolResult]
"""工具处理器签名，接收参数和上下文，返回结果。

这是什么：工具执行函数的类型签名
Java 类比：类似 BiFunction<Map<String, Object>, ToolContext, ToolResult>
为什么需要：定义统一的工具接口，所有工具必须遵循这个签名
"""


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """一个完整工具定义：名称、说明、参数格式、副作用类型和执行函数。

    这是什么：工具的元数据和执行器的组合
    Java 类比：类似 record ToolDefinition(String name, String description, ...)
    为什么需要：将工具的声明和实现绑定在一起，便于注册和管理

    参数：
        name: 注册表中的唯一名称
        description: 发送给模型的工具说明
        parameters: JSON Schema 参数约束
        effect: 副作用分类（read/write/execute/external）
        handler: 参数校验通过后真正执行的函数
        validator: 执行前的严格参数校验器（可选）
    """

    name: str  # 工具名称
    description: str  # 工具描述
    parameters: dict[str, Any]  # 参数 schema
    effect: EffectClass  # 副作用类别
    handler: ToolHandler  # 执行函数
    validator: Callable[[Mapping[str, Any]], bool] | None = None  # 校验器


@dataclass(frozen=True, slots=True)
class PreparedToolCall:
    """已经完成查找、JSON 解析和参数校验的工具调用。

    这是什么：工具调用的准备结果
    Java 类比：类似 record PreparedToolCall(ToolCall call, ToolDefinition definition, ...)
    为什么需要：分离准备阶段和执行阶段，准备失败时直接返回错误，不进入执行

    参数：
        call: 模型原始调用，必须保留 ID
        definition: 找到的工具定义（准备失败时为 None）
        arguments: JSON 解析、校验并冻结后的参数（准备失败时为 None）
        error: 准备阶段失败时直接回填的错误（成功时为 None）
    """

    call: ToolCall  # 原始调用
    definition: ToolDefinition | None = None  # 工具定义
    arguments: Mapping[str, Any] | None = None  # 解析后的参数
    error: ToolResult | None = None  # 准备错误


def _freeze_json(value: Any) -> Any:
    """递归冻结 JSON 数据，防止后续修改。

    这是什么：JSON 数据的不可变转换函数
    Java 类比：类似把 Map/List 递归转换成 Map.copyOf 和 List.copyOf
    为什么需要：确保参数在准备后不能被修改，保证执行安全

    参数：
        value: 待冻结的 JSON 数据

    返回：
        Any: 不可变的数据结构（dict->MappingProxyType, list->tuple）
    """
    if isinstance(value, dict):
        # MappingProxyType 是 Python 标准库提供的只读 Map 视图
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        # tuple 是不可变序列
        return tuple(_freeze_json(item) for item in value)
    return value  # 基本类型不需要冻结


def copy_prepared_tool_call(
    prepared: PreparedToolCall,
    *,
    definition: ToolDefinition | None = None,
) -> PreparedToolCall:
    """复制并冻结 prepared call，同时按需保留可信工具定义的对象身份。

    这是什么：PreparedToolCall 的深拷贝方法
    Java 类比：类似防御性拷贝构造器
    为什么需要：Hook 可能修改 prepared，需要隔离原始对象

    参数：
        prepared: 原始准备好的调用
        definition: 可选的工具定义（用于保留对象引用）

    返回：
        PreparedToolCall: 新的准备好的调用对象

    异常：
        TypeError: 参数不是 PreparedToolCall 类型
    """
    if not isinstance(prepared, PreparedToolCall):
        raise TypeError("只能复制 PreparedToolCall")
    # 递归冻结参数
    copied_arguments = (
        None if prepared.arguments is None else _freeze_json(dict(prepared.arguments))
    )
    # 复制错误结果
    copied_error = None if prepared.error is None else copy_tool_result(prepared.error)
    return PreparedToolCall(
        ToolCall(prepared.call.id, prepared.call.name, prepared.call.arguments),
        definition if definition is not None else prepared.definition,
        copied_arguments,
        copied_error,
    )


class ToolRegistry:
    """集中管理所有模型可以调用的工具。

    这是什么：工具的注册中心和执行管理器
    Java 类比：类似 Spring 的 BeanFactory 或命令模式的 CommandRegistry
    为什么需要：集中管理工具定义，支持动态注册、快照隔离和安全执行
    """

    def __init__(
        self, definitions: dict[str, ToolDefinition] | None = None, mutable: bool = True
    ) -> None:
        """初始化工具注册表。

        参数：
            definitions: 初始工具定义字典（会被复制）
            mutable: 是否允许后续注册新工具（快照为 False）
        """
        # 复制一份字典，避免外部继续修改传入的 definitions 影响本注册表
        # Java 对照：类似构造器里 new HashMap<>(definitions)
        self._definitions = dict(definitions or {})
        # True 表示启动装配阶段允许 register；快照会改成 False
        self._mutable = mutable

    @property
    def names(self) -> tuple[str, ...]:
        """返回已注册工具名的不可变快照。

        这是什么：获取所有工具名称的只读属性
        Java 类比：类似 Set<String> getToolNames()
        为什么需要：便于日志、测试和调试查看当前可用工具

        返回：
            tuple[str, ...]: 工具名称的不可变元组
        """
        return tuple(self._definitions)

    def register(self, definition: ToolDefinition) -> None:
        """注册工具，并在启动阶段尽早发现重名或非法名称。

        这是什么：工具注册方法
        Java 类比：类似 void registerTool(ToolDefinition definition)
        为什么需要：集中验证工具定义，确保名称合法且唯一

        参数：
            definition: 完整的工具定义对象

        异常：
            ValueError: 注册表不可变、工具名不合法、描述为空或工具已注册
        """
        if not self._mutable:
            raise ValueError("工具注册表快照不可修改")
        # 工具名只允许字母、数字和下划线
        if not re.fullmatch(r"[A-Za-z0-9_]+", definition.name):
            raise ValueError(f"工具名称不合法: {definition.name}")
        if not definition.description.strip():
            raise ValueError("工具描述不能为空")
        if definition.name in self._definitions:
            raise ValueError(f"工具已经注册过: {definition.name}")
        self._definitions[definition.name] = definition

    def snapshot(self) -> "ToolRegistry":
        """生成只读快照，确保一轮请求中工具集合不变。

        这是什么：创建注册表的不可变快照
        Java 类比：类似 Collections.unmodifiableMap() 包装后的注册表
        为什么需要：模型这一轮看到哪些工具，就必须只能执行这些工具，
                    不能在请求过程中偷偷变化

        返回：
            ToolRegistry: 不可变的工具注册表快照
        """
        return ToolRegistry(self._definitions, mutable=False)

    def openai_tools(self) -> tuple[OpenAIToolSchema, ...]:
        """把 Python 工具定义转换成模型能理解的 JSON Schema。

        这是什么：工具定义的格式转换方法
        Java 类比：类似 List<OpenAIToolSchema> toOpenAIFormat()
        为什么需要：模型不能直接读取 Python 函数，需要转换成 OpenAI 格式

        返回：
            tuple[OpenAIToolSchema, ...]: OpenAI 格式的工具定义列表
        """
        return tuple(
            OpenAIToolSchema(d.name, d.description, d.parameters)
            for d in self._definitions.values()
        )

    def prepare(self, call: ToolCall) -> PreparedToolCall:
        """准备工具调用：查找工具、解析参数、校验格式，但不执行。

        这是什么：工具调用的准备阶段
        Java 类比：类似 PreparedStatement 的参数绑定和校验
        为什么需要：分离准备和执行，将错误转换成 ToolResult 而不是异常

        执行顺序：
            1. 按名字查找工具定义
            2. 把 arguments 字符串解析成 JSON
            3. 校验必须是 JSON 对象
            4. 调用可选的 validator 进行参数校验
            5. 冻结参数，防止后续修改

        参数：
            call: 模型的工具调用请求

        返回：
            PreparedToolCall: 准备好的调用（可能包含错误）
        """
        # 第一步：查找工具定义
        definition = self._definitions.get(call.name)
        if definition is None:
            return PreparedToolCall(
                call, error=tool_error("unknown_tool", f"找不到工具: {call.name}")
            )

        # 第二步：解析 JSON 参数
        try:
            raw = json.loads(call.arguments)
        except json.JSONDecodeError:
            return PreparedToolCall(
                call,
                definition=definition,
                error=tool_error("invalid_json", "工具参数必须是合法 JSON"),
            )

        # 第三步：校验参数类型（必须是对象）
        if not isinstance(raw, dict):
            return PreparedToolCall(
                call,
                definition=definition,
                error=tool_error("invalid_arguments", "工具参数必须是 JSON 对象"),
            )

        # 第四步：调用自定义校验器
        if definition.validator is not None and not definition.validator(raw):
            return PreparedToolCall(
                call,
                definition=definition,
                error=tool_error("invalid_arguments", "工具参数没有通过格式校验"),
            )

        # 第五步：冻结参数并返回
        # prepare 成功后立刻冻结参数。后面的 Hook、审批器和 handler 共享这份快照，
        # 外部代码无法在异步等待期间偷偷修改参数
        return copy_prepared_tool_call(PreparedToolCall(call, definition=definition, arguments=raw))

    def invoke(self, prepared: PreparedToolCall, context: ToolContext) -> ToolResult:
        """真正执行已经准备好的工具调用，这是副作用发生的位置。

        这是什么：工具调用的执行阶段
        Java 类比：类似 PreparedStatement.execute()
        为什么需要：统一执行入口，将异常转换成 ToolResult，避免暴露内部细节

        异常处理策略：
            handler 是可插拔的外部代码，所有异常都要在注册表边界转换成稳定结果，
            不把 Python 堆栈或敏感信息直接发给模型

        参数：
            prepared: 准备好的工具调用
            context: 工具执行上下文

        返回：
            ToolResult: 工具执行结果（成功或失败）

        异常：
            ValueError: 准备好的调用不完整
        """
        # 如果准备阶段已失败，直接返回错误
        if prepared.error is not None:
            return prepared.error

        # 确保准备阶段已成功
        if prepared.definition is None or prepared.arguments is None:
            raise ValueError("准备好的工具调用不完整")

        try:
            # 调用工具处理函数
            result = prepared.definition.handler(prepared.arguments, context)

            # 校验返回值类型
            if not isinstance(result, ToolResult):
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")

            # 校验错误结果必须有错误码
            if result.is_error and not result.error_code:
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")

            # 校验成功结果不能有错误码
            if not result.is_error and result.error_code is not None:
                return tool_error("invalid_tool_result", "工具处理函数返回了无效结果")

            return result

        # 捕获所有异常并转换成标准错误结果
        except Exception:  # noqa: BLE001
            return tool_error("tool_execution_error", "工具执行失败")
