"""聊天消息领域模型。

Java 对照：这里的 dataclass 就像 Java 的 record，专门保存数据。
消息不能随便用 dict，因为模型消息有固定角色，而且工具调用必须和工具结果一一配对。
"""

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


class MessageContractError(Exception):
    """消息历史违反工具调用配对契约。

    把错误单独定义成一个类型，等价于 Java 中自定义业务异常，
    这样上层可以准确判断是消息格式错了，而不是网络错了。
    """


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型发出的“请程序帮我调用某个工具”的请求。"""
    id: str
    name: str
    arguments: str

    def __post_init__(self) -> None:
        _require_string(self.id, "tool call id")
        _require_string(self.name, "tool call name")
        _require_string(self.arguments, "tool call arguments", allow_empty=True)


@dataclass(frozen=True, slots=True)
class SystemMessage:
    """系统提示词：告诉模型它是谁、应该如何工作。"""
    role: Literal["system"]
    content: str


@dataclass(frozen=True, slots=True)
class UserMessage:
    """用户真正输入的问题。"""
    role: Literal["user"]
    content: str


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """模型的一次回答。

    `content` 有文本时表示模型在说话；`tool_calls` 非空时表示模型要程序做事。
    两者可以同时存在，但本章只关心是否存在工具调用。
    """
    role: Literal["assistant"]
    content: str | None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        if self.content is not None:
            _require_string(self.content, "assistant content", allow_empty=True)
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise MessageContractError("assistant tool call ids must be unique")


@dataclass(frozen=True, slots=True)
class ToolMessage:
    """程序执行工具后的结果，必须带回原来的 tool_call_id。"""
    role: Literal["tool"]
    content: str
    tool_call_id: str


ChatMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage


def _require_string(value: object, field: str, allow_empty: bool = False) -> str:
    """统一检查字符串。

    Python 不像 Java 编译器那样能保证运行时输入一定是字符串，
    所以从模型或 JSON 进入系统时必须主动校验。
    """
    if not isinstance(value, str):
        raise MessageContractError(f"{field} must be a string")
    if not allow_empty and not value:
        raise MessageContractError(f"{field} must not be empty")
    return value


def tool_call(call_id: object, name: object, arguments: object) -> ToolCall:
    return ToolCall(
        _require_string(call_id, "tool call id"),
        _require_string(name, "tool call name"),
        _require_string(arguments, "tool call arguments", allow_empty=True),
    )


def system_message(content: str) -> SystemMessage:
    return SystemMessage("system", _require_string(content, "system content", True))


def user_message(content: str) -> UserMessage:
    return UserMessage("user", _require_string(content, "user content", True))


def assistant_message(content: str | None, tool_calls: tuple[ToolCall, ...] = ()) -> AssistantMessage:
    return AssistantMessage("assistant", content, tuple(tool_calls))


def tool_message(content: str, tool_call_id: str) -> ToolMessage:
    return ToolMessage(
        "tool",
        _require_string(content, "tool content", True),
        _require_string(tool_call_id, "tool_call_id"),
    )


def validate_tool_pairing(messages: list[ChatMessage] | tuple[ChatMessage, ...]) -> None:
    """确保每个 assistant 工具调用恰好有一个后续 tool 结果。

    例子：assistant 调用 call-1 后，历史中必须出现 tool_call_id=call-1 的结果。
    这一步相当于数据库保存前的关联完整性检查，避免把坏消息发给模型供应商。
    """
    pending: set[str] = set()
    for message in messages:
        if pending:
            if not isinstance(message, ToolMessage):
                raise MessageContractError(f"missing tool results for ids: {sorted(pending)!r}")
            if message.tool_call_id not in pending:
                raise MessageContractError(f"unexpected tool result id: {message.tool_call_id}")
            pending.remove(message.tool_call_id)
            continue
        if isinstance(message, ToolMessage):
            raise MessageContractError(f"orphan tool result id: {message.tool_call_id}")
        if isinstance(message, AssistantMessage):
            pending.update(call.id for call in message.tool_calls)
    if pending:
        raise MessageContractError(f"missing tool results for ids: {sorted(pending)!r}")
