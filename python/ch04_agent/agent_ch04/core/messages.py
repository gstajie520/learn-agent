"""聊天消息领域模型。

Java 对照：这里的 dataclass 就像 Java 的 record，专门保存数据。
消息不能随便用 dict，因为模型消息有固定角色，而且工具调用必须和工具结果一一配对。
"""

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


class MessageContractError(Exception):
    """消息历史违反工具调用配对契约。

    这是什么：消息契约违反的专用异常
    Java 类比：类似 MessageContractViolationException
    为什么需要：消息历史必须满足配对契约（每个 tool_call 有且仅有一个 tool 消息），违反时需明确报错区别于网络等其他异常
    """


@dataclass(frozen=True, slots=True)
class ToolCall:
    “””模型发出的”请程序帮我调用某个工具”的请求。

    这是什么：工具调用请求的值对象
    Java 类比：类似 record ToolCall(String id, String name, String arguments)
    为什么需要：封装模型请求的工具调用信息，确保 id、name、arguments 都存在且有效
    “””
    id: str  # 本次调用唯一编号，用来和后面的 ToolMessage 配对
    name: str  # 工具名称，例如 shell
    arguments: str  # 模型生成的 JSON 字符串，必须在工具层再次校验

    def __post_init__(self) -> None:
        “””构造后校验所有字段非空（arguments 可为空字符串）。

        这是什么：字段完整性校验器
        Java 类比：类似构造器中的 Objects.requireNonNull() 校验
        为什么需要：确保工具调用的核心字段都有效，防止空 id 或空 name 导致配对失败
        “””
        _require_string(self.id, “tool call id”)
        _require_string(self.name, “tool call name”)
        _require_string(self.arguments, “tool call arguments”, allow_empty=True)


@dataclass(frozen=True, slots=True)
class SystemMessage:
    """系统提示词：告诉模型它是谁、应该如何工作。

    这是什么：系统角色消息的值对象
    Java 类比：类似 record SystemMessage(String role = "system", String content)
    为什么需要：封装系统提示词，role 固定为 "system" 避免类型混淆
    """
    role: Literal["system"]  # 固定为 system，便于代码判断消息类型
    content: str  # 系统规则文本


@dataclass(frozen=True, slots=True)
class UserMessage:
    """用户真正输入的问题。

    这是什么：用户角色消息的值对象
    Java 类比：类似 record UserMessage(String role = "user", String content)
    为什么需要：封装用户输入，role 固定为 "user" 避免类型混淆
    """
    role: Literal["user"]  # 固定为 user
    content: str  # 用户输入的自然语言问题


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """模型的一次回答。

    这是什么：助手角色消息的值对象
    Java 类比：类似 record AssistantMessage(String role = "assistant", String content, List<ToolCall> toolCalls)
    为什么需要：封装模型回答，可包含文本或工具调用或两者都有
    """
    role: Literal["assistant"]  # 固定为 assistant
    content: str | None  # 普通回答文本；请求工具时可能为 None
    tool_calls: tuple[ToolCall, ...] = ()  # 本次回答要求执行的工具列表

    def __post_init__(self) -> None:
        """校验 content 和 tool_calls 的完整性。

        这是什么：助手消息字段校验器
        Java 类比：类似构造器中的字段校验
        为什么需要：确保 content 非空（如果存在）且同一消息内工具调用 id 不重复
        """
        if self.content is not None:
            _require_string(self.content, "assistant content", allow_empty=True)
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise MessageContractError("同一条 assistant 消息中的工具调用 ID 不能重复")


@dataclass(frozen=True, slots=True)
class ToolMessage:
    """程序执行工具后的结果，必须带回原来的 tool_call_id。

    这是什么：工具执行结果消息的值对象
    Java 类比：类似 record ToolMessage(String role = "tool", String content, String toolCallId)
    为什么需要：封装工具执行结果，通过 tool_call_id 与前面的 ToolCall 配对
    """
    role: Literal["tool"]  # 固定为 tool
    content: str  # 工具输出或结构化错误文本
    tool_call_id: str  # 关联前一个 assistant 工具调用的 ID


ChatMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage


def _require_string(value: object, field: str, allow_empty: bool = False) -> str:
    """统一检查字符串。

    这是什么：字符串类型和非空校验器
    Java 类比：类似 String requireNonEmpty(Object value, String fieldName)
    为什么需要：Python 运行时不保证类型，需主动校验字符串类型和是否为空
    """
    if not isinstance(value, str):
        raise MessageContractError(f"{field} 必须是字符串")
    if not allow_empty and not value:
        raise MessageContractError(f"{field} 不能为空")
    return value


def tool_call(call_id: object, name: object, arguments: object) -> ToolCall:
    """从不可信的模型字段创建 ToolCall，并在入口处完成字符串校验。

    这是什么：ToolCall 的安全构造器
    Java 类比：类似 static ToolCall fromUntrusted(Object id, Object name, Object args)
    为什么需要：模型返回的字段不可信，需在边界处校验类型后再构造值对象
    """
    return ToolCall(
        _require_string(call_id, "tool call id"),
        _require_string(name, "tool call name"),
        _require_string(arguments, "tool call arguments", allow_empty=True),
    )


def system_message(content: str) -> SystemMessage:
    """创建带有固定 `system` 角色的系统消息。

    这是什么：SystemMessage 的工厂方法
    Java 类比：类似 static SystemMessage of(String content)
    为什么需要：提供便捷构造方法，自动填充 role 并校验 content
    """
    return SystemMessage("system", _require_string(content, "system content", True))


def user_message(content: str) -> UserMessage:
    """创建带有固定 `user` 角色的用户消息。

    这是什么：UserMessage 的工厂方法
    Java 类比：类似 static UserMessage of(String content)
    为什么需要：提供便捷构造方法，自动填充 role 并校验 content
    """
    return UserMessage("user", _require_string(content, "user content", True))


def assistant_message(content: str | None, tool_calls: tuple[ToolCall, ...] = ()) -> AssistantMessage:
    """创建模型消息，并把工具调用集合转换成不可变 tuple。

    这是什么：AssistantMessage 的工厂方法
    Java 类比：类似 static AssistantMessage of(String content, List<ToolCall> calls)
    为什么需要：提供便捷构造方法，自动填充 role 并确保 tool_calls 不可变
    """
    return AssistantMessage("assistant", content, tuple(tool_calls))


def tool_message(content: str, tool_call_id: str) -> ToolMessage:
    """创建工具结果消息；`tool_call_id` 用来和 assistant 请求配对。

    这是什么：ToolMessage 的工厂方法
    Java 类比：类似 static ToolMessage of(String content, String callId)
    为什么需要：提供便捷构造方法，自动填充 role 并校验字段
    """
    return ToolMessage(
        "tool",
        _require_string(content, "tool content", True),
        _require_string(tool_call_id, "tool_call_id"),
    )


def validate_tool_pairing(messages: list[ChatMessage] | tuple[ChatMessage, ...]) -> None:
    """确保每个 assistant 工具调用恰好有一个后续 tool 结果。

    这是什么：消息历史的配对完整性校验器
    Java 类比：类似 void validatePairing(List<ChatMessage> messages)
    为什么需要：防止把不配对的消息发给模型（缺少结果或多余结果），确保对话历史完整性
    """
    pending: set[str] = set()
    for message in messages:
        if pending:
            if not isinstance(message, ToolMessage):
                raise MessageContractError(f"以下工具调用缺少返回结果: {sorted(pending)!r}")
            if message.tool_call_id not in pending:
                raise MessageContractError(f"收到未预期的工具结果 ID: {message.tool_call_id}")
            pending.remove(message.tool_call_id)
            continue
        if isinstance(message, ToolMessage):
            raise MessageContractError(f"工具结果找不到对应的调用 ID: {message.tool_call_id}")
        if isinstance(message, AssistantMessage):
            pending.update(call.id for call in message.tool_calls)
    if pending:
        raise MessageContractError(f"以下工具调用缺少返回结果: {sorted(pending)!r}")
