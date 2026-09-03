“””聊天消息领域模型。

Java 对照：这里的 dataclass 就像 Java 的 record，专门保存数据。
消息不能随便用 dict，因为模型消息有固定角色，而且工具调用必须和工具结果一一配对。

这是什么：定义 Agent 与模型交互的消息结构
Java 类比：类似定义 DTO 或 record 的包，每种消息对应一个不可变对象
为什么需要：强类型消息避免角色混淆，确保工具调用与结果正确配对
“””

from dataclasses import dataclass
from typing import Literal

# 消息角色类型：限定只能是这四个值，类似 Java 的枚举
Role = Literal[“system”, “user”, “assistant”, “tool”]


class MessageContractError(Exception):
    “””消息历史违反工具调用配对契约时抛出的异常。

    这是什么：消息格式错误的专用异常
    Java 类比：类似自定义的 ValidationException 或 ContractViolationException
    为什么需要：区分消息格式错误和网络错误，让上层精确处理失败原因
    “””


@dataclass(frozen=True, slots=True)
class ToolCall:
    “””模型发出的”请程序帮我调用某个工具”的请求。

    这是什么：表示模型请求执行工具的数据对象
    Java 类比：类似 record ToolCall(String id, String name, String arguments)
    为什么需要：封装工具调用的三要素，确保每次调用都有唯一 ID 用于配对

    参数：
        id: 本次调用唯一编号，用来和后面的 ToolMessage 配对
        name: 工具名称，例如 shell
        arguments: 模型生成的 JSON 字符串，必须在工具层再次校验
    “””

    id: str  # 唯一调用 ID
    name: str  # 工具名称
    arguments: str  # JSON 参数字符串

    def __post_init__(self) -> None:
        “””创建后立即校验字段，确保不会出现空 ID 或空工具名。”””
        _require_string(self.id, “tool call id”)
        _require_string(self.name, “tool call name”)
        _require_string(self.arguments, “tool call arguments”, allow_empty=True)


@dataclass(frozen=True, slots=True)
class SystemMessage:
    """系统提示词：告诉模型它是谁、应该如何工作。

    这是什么：系统角色消息，定义 Agent 的身份和行为规范
    Java 类比：类似 record SystemMessage(String role, String content)，role 固定为 "system"
    为什么需要：通过类型系统确保系统消息不会被误标记为用户消息

    参数：
        role: 固定为 "system"，便于代码判断消息类型
        content: 系统规则文本，定义 Agent 的行为约束
    """

    role: Literal["system"]  # 固定角色
    content: str  # 系统提示词


@dataclass(frozen=True, slots=True)
class UserMessage:
    """用户真正输入的问题。

    这是什么：用户角色消息，表示用户的输入
    Java 类比：类似 record UserMessage(String role, String content)
    为什么需要：区分用户输入和模型回复，保持消息流清晰

    参数：
        role: 固定为 "user"
        content: 用户输入的自然语言问题
    """

    role: Literal["user"]  # 固定角色
    content: str  # 用户输入


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """模型的一次回答，可以包含文本或工具调用请求。

    这是什么：模型角色消息，表示模型的回复
    Java 类比：类似 record AssistantMessage(String role, String content, List<ToolCall> toolCalls)
    为什么需要：封装模型的两种输出形式（文本回答或工具请求）

    参数：
        role: 固定为 "assistant"
        content: 普通回答文本；请求工具时可能为 None
        tool_calls: 本次回答要求执行的工具列表
    """

    role: Literal["assistant"]  # 固定角色
    content: str | None  # 可选文本内容
    tool_calls: tuple[ToolCall, ...] = ()  # 工具调用列表

    def __post_init__(self) -> None:
        """创建后校验内容和工具调用 ID 唯一性。"""
        if self.content is not None:
            _require_string(self.content, "assistant content", allow_empty=True)
        # 检查工具调用 ID 不能重复（同一条消息内）
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise MessageContractError("同一条 assistant 消息中的工具调用 ID 不能重复")


@dataclass(frozen=True, slots=True)
class ToolMessage:
    """程序执行工具后的结果，必须带回原来的 tool_call_id。

    这是什么：工具执行结果消息
    Java 类比：类似 record ToolMessage(String role, String content, String toolCallId)
    为什么需要：将工具执行结果返回给模型，通过 tool_call_id 完成配对

    参数：
        role: 固定为 "tool"
        content: 工具输出或结构化错误文本
        tool_call_id: 关联前一个 assistant 工具调用的 ID
    """

    role: Literal["tool"]  # 固定角色
    content: str  # 工具输出
    tool_call_id: str  # 配对 ID


# 联合类型：所有消息的总类型，类似 Java 的 sealed interface
ChatMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage


def _require_string(value: object, field: str, allow_empty: bool = False) -> str:
    """统一检查字符串类型和非空约束。

    这是什么：字符串校验工具函数
    Java 类比：类似 Objects.requireNonNull() 或自定义 Validator.requireString()
    为什么需要：Python 运行时不强制类型，必须主动校验外部输入

    参数：
        value: 待校验的对象
        field: 字段名称（用于错误提示）
        allow_empty: 是否允许空字符串

    返回：
        str: 校验通过的字符串

    异常：
        MessageContractError: 类型不是字符串或为空
    """
    if not isinstance(value, str):
        raise MessageContractError(f"{field} 必须是字符串")
    if not allow_empty and not value:
        raise MessageContractError(f"{field} 不能为空")
    return value


def tool_call(call_id: object, name: object, arguments: object) -> ToolCall:
    """从不可信的模型字段创建 ToolCall，并在入口处完成字符串校验。

    这是什么：ToolCall 的安全构造函数
    Java 类比：类似静态工厂方法 ToolCall.from(Object id, Object name, Object args)
    为什么需要：模型返回的字段类型不可信，必须在边界处校验

    参数：
        call_id: 模型返回的调用 ID（需要校验是字符串）
        name: 模型返回的工具名称
        arguments: 模型返回的参数 JSON

    返回：
        ToolCall: 校验通过的工具调用对象
    """
    return ToolCall(
        _require_string(call_id, "tool call id"),
        _require_string(name, "tool call name"),
        _require_string(arguments, "tool call arguments", allow_empty=True),
    )


def system_message(content: str) -> SystemMessage:
    """创建带有固定 `system` 角色的系统消息。

    这是什么：SystemMessage 的便捷构造函数
    Java 类比：类似静态工厂方法 SystemMessage.of(String content)
    为什么需要：自动填充固定的 role 字段，简化调用代码

    参数：
        content: 系统提示词内容

    返回：
        SystemMessage: 系统消息对象
    """
    return SystemMessage("system", _require_string(content, "system content", True))


def user_message(content: str) -> UserMessage:
    """创建带有固定 `user` 角色的用户消息。

    这是什么：UserMessage 的便捷构造函数
    Java 类比：类似静态工厂方法 UserMessage.of(String content)
    为什么需要：自动填充固定的 role 字段，避免手动传入

    参数：
        content: 用户输入内容

    返回：
        UserMessage: 用户消息对象
    """
    return UserMessage("user", _require_string(content, "user content", True))


def assistant_message(
    content: str | None, tool_calls: tuple[ToolCall, ...] = ()
) -> AssistantMessage:
    """创建模型消息，并把工具调用集合转换成不可变 tuple。

    这是什么：AssistantMessage 的便捷构造函数
    Java 类比：类似静态工厂方法 AssistantMessage.of(String content, List<ToolCall> calls)
    为什么需要：确保工具调用列表是不可变的，防止外部修改

    参数：
        content: 模型回复文本（可为空）
        tool_calls: 工具调用列表

    返回：
        AssistantMessage: 模型消息对象
    """
    return AssistantMessage("assistant", content, tuple(tool_calls))


def tool_message(content: str, tool_call_id: str) -> ToolMessage:
    """创建工具结果消息；`tool_call_id` 用来和 assistant 请求配对。

    这是什么：ToolMessage 的便捷构造函数
    Java 类比：类似静态工厂方法 ToolMessage.of(String content, String callId)
    为什么需要：自动填充固定的 role 字段，确保配对 ID 非空

    参数：
        content: 工具执行结果
        tool_call_id: 对应的工具调用 ID

    返回：
        ToolMessage: 工具结果消息对象
    """
    return ToolMessage(
        "tool",
        _require_string(content, "tool content", True),
        _require_string(tool_call_id, "tool_call_id"),
    )


def validate_tool_pairing(messages: list[ChatMessage] | tuple[ChatMessage, ...]) -> None:
    """确保每个 assistant 工具调用恰好有一个后续 tool 结果。

    这是什么：消息历史的完整性校验函数
    Java 类比：类似 Validator.validateToolPairing(List<Message> messages)
    为什么需要：避免把格式错误的消息发给模型，导致 API 调用失败

    工作原理：
        遍历消息历史，用 pending 集合跟踪待配对的工具调用 ID。
        遇到 AssistantMessage 时，将其 tool_calls 的 ID 加入 pending。
        遇到 ToolMessage 时，必须能从 pending 中找到对应 ID，然后移除。
        最终 pending 必须为空，表示所有调用都有结果。

    参数：
        messages: 消息历史列表或元组

    异常：
        MessageContractError: 工具调用与结果配对不完整
    """
    pending: set[str] = set()  # 待配对的工具调用 ID 集合
    for message in messages:
        if pending:  # 有待配对的调用
            # 下一条消息必须是工具结果
            if not isinstance(message, ToolMessage):
                raise MessageContractError(f"以下工具调用缺少返回结果: {sorted(pending)!r}")
            # 工具结果的 ID 必须在待配对集合中
            if message.tool_call_id not in pending:
                raise MessageContractError(f"收到未预期的工具结果 ID: {message.tool_call_id}")
            pending.remove(message.tool_call_id)  # 配对成功，移除
            continue
        # pending 为空时，不应该出现工具结果
        if isinstance(message, ToolMessage):
            raise MessageContractError(f"工具结果找不到对应的调用 ID: {message.tool_call_id}")
        # 遇到 AssistantMessage 时，记录其工具调用 ID
        if isinstance(message, AssistantMessage):
            pending.update(call.id for call in message.tool_calls)
    # 最终检查：所有调用都必须有结果
    if pending:
        raise MessageContractError(f"以下工具调用缺少返回结果: {sorted(pending)!r}")
