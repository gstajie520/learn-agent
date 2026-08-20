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
    id: str  # 本次调用唯一编号，用来和后面的 ToolMessage 配对。
    name: str  # 工具名称，例如 shell。
    arguments: str  # 模型生成的 JSON 字符串，必须在工具层再次校验。

    def __post_init__(self) -> None:
        _require_string(self.id, "tool call id")
        _require_string(self.name, "tool call name")
        _require_string(self.arguments, "tool call arguments", allow_empty=True)


@dataclass(frozen=True, slots=True)
class SystemMessage:
    """系统提示词：告诉模型它是谁、应该如何工作。

    Java 对照：可以把它看成消息 DTO 的一个具体子类型；`role` 是固定值，
    类似 Java 枚举字段，避免调用方把系统消息误标成 user。
    """
    role: Literal["system"]  # 固定为 system，便于代码判断消息类型。
    content: str  # 系统规则文本。


@dataclass(frozen=True, slots=True)
class UserMessage:
    """用户真正输入的问题。

    `content` 保存业务输入，不负责调用模型；真正的编排由 AgentRunner 完成。
    """
    role: Literal["user"]  # 固定为 user。
    content: str  # 用户输入的自然语言问题。


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """模型的一次回答。

    `content` 有文本时表示模型在说话；`tool_calls` 非空时表示模型要程序做事。
    两者可以同时存在，但本章只关心是否存在工具调用。
    """
    role: Literal["assistant"]  # 固定为 assistant。
    content: str | None  # 普通回答文本；请求工具时可能为 None。
    tool_calls: tuple[ToolCall, ...] = ()  # 本次回答要求执行的工具列表。

    def __post_init__(self) -> None:
        if self.content is not None:
            _require_string(self.content, "assistant content", allow_empty=True)
        ids = [call.id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise MessageContractError("同一条 assistant 消息中的工具调用 ID 不能重复")


@dataclass(frozen=True, slots=True)
class ToolMessage:
    """程序执行工具后的结果，必须带回原来的 tool_call_id。"""
    role: Literal["tool"]  # 固定为 tool。
    content: str  # 工具输出或结构化错误文本。
    tool_call_id: str  # 关联前一个 assistant 工具调用的 ID。


ChatMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage


def _require_string(value: object, field: str, allow_empty: bool = False) -> str:
    """统一检查字符串。

    Python 不像 Java 编译器那样能保证运行时输入一定是字符串，
    所以从模型或 JSON 进入系统时必须主动校验。
    """
    if not isinstance(value, str):
        raise MessageContractError(f"{field} 必须是字符串")
    if not allow_empty and not value:
        raise MessageContractError(f"{field} 不能为空")
    return value


def tool_call(call_id: object, name: object, arguments: object) -> ToolCall:
    """从不可信的模型字段创建 ToolCall，并在入口处完成字符串校验。"""
    return ToolCall(
        _require_string(call_id, "tool call id"),
        _require_string(name, "tool call name"),
        _require_string(arguments, "tool call arguments", allow_empty=True),
    )


def system_message(content: str) -> SystemMessage:
    """创建带有固定 `system` 角色的系统消息。"""
    return SystemMessage("system", _require_string(content, "system content", True))


def user_message(content: str) -> UserMessage:
    """创建带有固定 `user` 角色的用户消息。"""
    return UserMessage("user", _require_string(content, "user content", True))


def assistant_message(content: str | None, tool_calls: tuple[ToolCall, ...] = ()) -> AssistantMessage:
    """创建模型消息，并把工具调用集合转换成不可变 tuple。"""
    return AssistantMessage("assistant", content, tuple(tool_calls))


def tool_message(content: str, tool_call_id: str) -> ToolMessage:
    """创建工具结果消息；`tool_call_id` 用来和 assistant 请求配对。"""
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
