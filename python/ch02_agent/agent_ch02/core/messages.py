"""聊天消息领域模型。

这是什么：Chat Completions 消息的领域对象定义
Java 类比：类似定义 Message 接口和各种 record 实现类（SystemMessage, UserMessage 等）
为什么需要：用类型安全的对象替代字典，强制消息格式约束，便于编译期检查

Java 对照：这里的 dataclass 就像 Java 的 record，专门保存数据。
消息不能随便用 dict，因为模型消息有固定角色，而且工具调用必须和工具结果一一配对。
"""

from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]  # 消息角色枚举


class MessageContractError(Exception):
    """消息历史违反工具调用配对契约。

    这是什么：消息格式异常，表示消息违反了 Chat Completions 协议
    Java 类比：类似 MessageValidationException
    为什么需要：区分消息格式错误和其他错误，便于精确处理

    把错误单独定义成一个类型，等价于 Java 中自定义业务异常，
    这样上层可以准确判断是消息格式错了，而不是网络错了。
    """


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型发出的"请程序帮我调用某个工具"的请求。

    这是什么：工具调用请求的值对象
    Java 类比：类似 record ToolCall(String id, String name, String arguments)
    为什么需要：封装模型的工具调用意图，关联后续的工具结果
    """
    id: str  # 本次调用唯一编号，用来和后面的 ToolMessage 配对。
    name: str  # 工具名称，例如 shell。
    arguments: str  # 模型生成的 JSON 字符串，必须在工具层再次校验。

    def __post_init__(self) -> None:
        """dataclass 构造后的验证钩子。

        这是什么：后置验证方法，确保字段值合法
        Java 类比：类似 record 的 compact constructor 或构造器末尾的验证
        为什么需要：在对象创建时立即发现非法数据，避免脏数据传播
        """
        _require_string(self.id, "tool call id")  # 验证 id 非空
        _require_string(self.name, "tool call name")  # 验证 name 非空
        _require_string(self.arguments, "tool call arguments", allow_empty=True)  # arguments 可以为空字符串


@dataclass(frozen=True, slots=True)
class SystemMessage:
    """系统提示词：告诉模型它是谁、应该如何工作。

    这是什么：系统消息对象，定义模型行为和约束
    Java 类比：类似 record SystemMessage(String role, String content) 且 role 固定为 "system"
    为什么需要：封装系统提示，通过类型确保角色不会被误用

    Java 对照：可以把它看成消息 DTO 的一个具体子类型；`role` 是固定值，
    类似 Java 枚举字段，避免调用方把系统消息误标成 user。
    """
    role: Literal["system"]  # 固定为 system，便于代码判断消息类型。
    content: str  # 系统规则文本。


@dataclass(frozen=True, slots=True)
class UserMessage:
    """用户真正输入的问题。

    这是什么：用户消息对象，封装用户输入
    Java 类比：类似 record UserMessage(String role, String content) 且 role 固定为 "user"
    为什么需要：类型安全地表示用户输入，避免角色混淆

    `content` 保存业务输入，不负责调用模型；真正的编排由 AgentRunner 完成。
    """
    role: Literal["user"]  # 固定为 user。
    content: str  # 用户输入的自然语言问题。


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    """模型的一次回答。

    这是什么：模型响应消息对象，可包含文本和工具调用
    Java 类比：类似 record AssistantMessage(String role, String content, List<ToolCall> toolCalls)
    为什么需要：封装模型响应，支持纯文本回复和工具调用两种模式

    `content` 有文本时表示模型在说话；`tool_calls` 非空时表示模型要程序做事。
    两者可以同时存在，但本章只关心是否存在工具调用。
    """
    role: Literal["assistant"]  # 固定为 assistant。
    content: str | None  # 普通回答文本；请求工具时可能为 None。
    tool_calls: tuple[ToolCall, ...] = ()  # 本次回答要求执行的工具列表。

    def __post_init__(self) -> None:
        """验证 content 和 tool_calls 的一致性。

        这是什么：后置验证方法，检查消息完整性
        Java 类比：类似 compact constructor 中的验证逻辑
        为什么需要：确保工具调用 ID 唯一，避免配对冲突
        """
        if self.content is not None:  # content 可选，但如果存在则验证
            _require_string(self.content, "assistant content", allow_empty=True)
        ids = [call.id for call in self.tool_calls]  # 收集所有工具调用 ID
        if len(ids) != len(set(ids)):  # 检查 ID 是否重复
            raise MessageContractError("同一条 assistant 消息中的工具调用 ID 不能重复")


@dataclass(frozen=True, slots=True)
class ToolMessage:
    """程序执行工具后的结果，必须带回原来的 tool_call_id。

    这是什么：工具结果消息对象，关联工具调用请求
    Java 类比：类似 record ToolMessage(String role, String content, String toolCallId)
    为什么需要：封装工具执行结果，通过 tool_call_id 与请求配对
    """
    role: Literal["tool"]  # 固定为 tool。
    content: str  # 工具输出或结构化错误文本。
    tool_call_id: str  # 关联前一个 assistant 工具调用的 ID。


ChatMessage = SystemMessage | UserMessage | AssistantMessage | ToolMessage  # 消息类型联合


def _require_string(value: object, field: str, allow_empty: bool = False) -> str:
    """统一检查字符串。

    这是什么：字符串验证工具函数
    Java 类比：类似 static String requireNonEmpty(Object value, String field)
    为什么需要：Python 无编译期类型检查，必须运行时验证外部数据

    Python 不像 Java 编译器那样能保证运行时输入一定是字符串，
    所以从模型或 JSON 进入系统时必须主动校验。
    """
    if not isinstance(value, str):  # 类型检查
        raise MessageContractError(f"{field} 必须是字符串")
    if not allow_empty and not value:  # 空值检查
        raise MessageContractError(f"{field} 不能为空")
    return value


def tool_call(call_id: object, name: object, arguments: object) -> ToolCall:
    """从不可信的模型字段创建 ToolCall，并在入口处完成字符串校验。

    这是什么：ToolCall 工厂方法，从外部数据构造并验证
    Java 类比：类似 static ToolCall fromUntrusted(Object id, Object name, Object args)
    为什么需要：外部数据（模型响应）不可信，必须在边界验证并转换为类型安全对象
    """
    return ToolCall(
        _require_string(call_id, "tool call id"),  # 验证并转换 id
        _require_string(name, "tool call name"),  # 验证并转换 name
        _require_string(arguments, "tool call arguments", allow_empty=True),  # 验证 arguments，允许空
    )


def system_message(content: str) -> SystemMessage:
    """创建带有固定 `system` 角色的系统消息。

    这是什么：SystemMessage 工厂方法
    Java 类比：类似 static SystemMessage of(String content)
    为什么需要：封装对象创建，自动填充固定的 role 字段，验证内容合法性
    """
    return SystemMessage("system", _require_string(content, "system content", True))


def user_message(content: str) -> UserMessage:
    """创建带有固定 `user` 角色的用户消息。

    这是什么：UserMessage 工厂方法
    Java 类比：类似 static UserMessage of(String content)
    为什么需要：封装对象创建，自动填充固定的 role 字段，验证内容合法性
    """
    return UserMessage("user", _require_string(content, "user content", True))


def assistant_message(content: str | None, tool_calls: tuple[ToolCall, ...] = ()) -> AssistantMessage:
    """创建模型消息，并把工具调用集合转换成不可变 tuple。

    这是什么：AssistantMessage 工厂方法
    Java 类比：类似 static AssistantMessage of(String content, List<ToolCall> toolCalls)
    为什么需要：封装对象创建，确保 tool_calls 不可变，验证内容合法性
    """
    return AssistantMessage("assistant", content, tuple(tool_calls))


def tool_message(content: str, tool_call_id: str) -> ToolMessage:
    """创建工具结果消息；`tool_call_id` 用来和 assistant 请求配对。

    这是什么：ToolMessage 工厂方法
    Java 类比：类似 static ToolMessage of(String content, String toolCallId)
    为什么需要：封装对象创建，自动填充固定的 role 字段，验证字段合法性
    """
    return ToolMessage(
        "tool",
        _require_string(content, "tool content", True),  # 验证 content，允许空
        _require_string(tool_call_id, "tool_call_id"),  # 验证 tool_call_id 非空
    )


def validate_tool_pairing(messages: list[ChatMessage] | tuple[ChatMessage, ...]) -> None:
    """确保每个 assistant 工具调用恰好有一个后续 tool 结果。

    这是什么：消息历史完整性验证器
    Java 类比：类似 static void validateToolPairing(List<ChatMessage> messages) throws ValidationException
    为什么需要：确保工具调用和结果一一对应，避免发送损坏的消息历史给模型

    例子：assistant 调用 call-1 后，历史中必须出现 tool_call_id=call-1 的结果。
    这一步相当于数据库保存前的关联完整性检查，避免把坏消息发给模型供应商。
    """
    pending: set[str] = set()  # 待匹配的工具调用 ID 集合
    for message in messages:  # 遍历消息历史
        if pending:  # 有待匹配的工具调用
            if not isinstance(message, ToolMessage):  # 下一条必须是工具结果
                raise MessageContractError(f"以下工具调用缺少返回结果: {sorted(pending)!r}")
            if message.tool_call_id not in pending:  # 工具结果 ID 必须在待匹配集合中
                raise MessageContractError(f"收到未预期的工具结果 ID: {message.tool_call_id}")
            pending.remove(message.tool_call_id)  # 移除已匹配的 ID
            continue
        if isinstance(message, ToolMessage):  # 工具结果前面必须有对应的调用
            raise MessageContractError(f"工具结果找不到对应的调用 ID: {message.tool_call_id}")
        if isinstance(message, AssistantMessage):  # assistant 消息可能包含工具调用
            pending.update(call.id for call in message.tool_calls)  # 添加到待匹配集合
    if pending:  # 遍历结束后不应有未匹配的工具调用
        raise MessageContractError(f"以下工具调用缺少返回结果: {sorted(pending)!r}")
