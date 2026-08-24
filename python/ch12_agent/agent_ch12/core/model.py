"""模型边界契约。

这里故意不导入 OpenAI SDK。核心循环只知道“有一个对象能完成一次模型请求”，
这就像 Java Service 只依赖 `ModelClient` 接口，而不是直接依赖某个厂商 SDK。
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]


class ModelAPIError(Exception):
    """供应商 API 错误的稳定内部表示，不暴露 SDK 私有对象。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if not isinstance(message, str) or not message.strip():
            raise TypeError("message 必须是非空字符串")
        if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code <= 0:
            raise ValueError("status_code 必须是正整数")
        if error_code is not None and not error_code.strip():
            raise TypeError("error_code 必须是非空字符串或 None")
        if request_id is not None and not request_id.strip():
            raise TypeError("request_id 必须是非空字符串或 None")
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id


class ModelRateLimitError(ModelAPIError):
    """HTTP 429；Retry-After 保留原始字符串，由恢复层解析。"""

    def __init__(
        self,
        message: str,
        *,
        retry_after: str | None = None,
        status_code: int = 429,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if status_code != 429:
            raise ValueError("ModelRateLimitError 的 status_code 必须是 429")
        if retry_after is not None and not isinstance(retry_after, str):
            raise TypeError("retry_after 必须是字符串或 None")
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            request_id=request_id,
        )
        self.retry_after = retry_after


class ModelOverloadedError(ModelAPIError):
    """HTTP 529；连续次数和 fallback 由 RecoveryManager 管理。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 529,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if status_code != 529:
            raise ValueError("ModelOverloadedError 的 status_code 必须是 529")
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            request_id=request_id,
        )


class ModelPromptTooLongError(ModelAPIError):
    """HTTP 400 且带明确 context-length error code。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if status_code != 400:
            raise ValueError("ModelPromptTooLongError 的 status_code 必须是 400")
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            request_id=request_id,
        )


@dataclass(frozen=True, slots=True)
class OpenAIToolSchema:
    """发给 OpenAI 兼容接口的工具说明。

    模型不会直接读取 Python 函数，它只能读取 JSON Schema，
    所以注册表需要把 Python 工具转换成这个结构。
    """

    name: str  # 模型调用时使用的函数名。
    description: str  # 给模型看的用途说明。
    parameters: dict[str, Any]  # JSON Schema，描述参数类型和必填字段。

    def as_openai(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 接口要求的嵌套字典。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次模型请求的完整输入。"""

    messages: tuple[ChatMessage, ...]  # 本轮模型能看到的消息历史。
    tools: tuple[OpenAIToolSchema, ...]  # 本轮允许模型调用的工具。
    model: str | None = None  # 可选覆盖默认模型。
    max_tokens: int | None = None  # 可选的单轮输出 token 上限。


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int  # 输入消息消耗的 token 数。
    completion_tokens: int  # 模型输出消耗的 token 数。
    total_tokens: int  # 输入和输出之和。


@dataclass(frozen=True, slots=True)
class ModelReply:
    """适配器转换后的统一模型响应。"""

    message: AssistantMessage  # 已转换成内部消息对象的模型回答。
    finish_reason: FinishReason  # stop、tool_calls、length 等结束原因。
    usage: TokenUsage | None = None  # 有些供应商不返回用量，所以允许为空。


class ModelClient(Protocol):
    """模型客户端接口，类似 Java interface。

    核心循环只依赖这个协议，不关心 HTTP、鉴权和第三方 SDK；这正是依赖倒置
    的效果。真实适配器和测试 Fake 只要实现 `complete` 就可以被注入。
    """

    def complete(self, request: ModelRequest) -> ModelReply:
        """向模型发送一轮规范化请求，并返回核心层统一的响应。"""
