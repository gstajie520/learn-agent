“””模型边界契约。

这是什么：
    定义核心层与模型适配器之间的接口和异常契约。

Java 类比：
    这就像 Java Service 只依赖 ModelClient 接口，而不是直接依赖某个厂商 SDK。
    异常定义类似领域异常（DomainException），隔离第三方 SDK 的异常类型。

为什么需要：
    1. 核心层不应依赖 OpenAI SDK 的具体类型
    2. 切换供应商（DeepSeek → Anthropic）时只改适配器
    3. 测试时可以用 Fake 实现替换真实 HTTP 客户端

核心设计：
    - ModelClient 接口：统一的模型请求方法
    - ModelAPIError 系列：供应商无关的领域异常
    - ModelRequest/ModelReply：不可变的请求/响应 DTO
“””

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]  # 模型回复的结束原因类型


class ModelAPIError(Exception):
    """供应商 API 错误的稳定内部表示，不暴露 SDK 私有对象。

    这是什么：模型 API 错误的基础异常类
    Java 类比：类似自定义的 ModelAPIException 领域异常
    为什么需要：隔离供应商 SDK 的异常类型，核心层只依赖领域异常

    核心职责：
        1. 保存 HTTP 状态码（429、529、400 等）
        2. 保存供应商错误码（context_length_exceeded 等）
        3. 保存请求 ID（用于排查问题）

    设计原则：
        - 不依赖 OpenAI SDK 的 APIError 类型
        - 字段都是基础类型（int、str），可序列化
        - 参数校验在构造时完成，避免运行时才发现错误
    """

    def __init__(
        self,
        message: str,  # 错误描述文本
        *,
        status_code: int,  # HTTP 状态码（429、529、400 等）
        error_code: str | None = None,  # 供应商错误码（如 "context_length_exceeded"）
        request_id: str | None = None,  # 请求 ID（用于排查问题）
    ) -> None:
        """初始化模型 API 错误。

        Java 对照：构造器参数校验，类似 Preconditions.checkArgument()
        """
        # 校验 message 必须是非空字符串
        if not isinstance(message, str) or not message.strip():
            raise TypeError("message 必须是非空字符串")
        # 校验 status_code 必须是正整数（不能是 bool，Python 中 True == 1）
        if isinstance(status_code, bool) or not isinstance(status_code, int) or status_code <= 0:
            raise ValueError("status_code 必须是正整数")
        # 校验 error_code 如果存在必须非空
        if error_code is not None and not error_code.strip():
            raise TypeError("error_code 必须是非空字符串或 None")
        # 校验 request_id 如果存在必须非空
        if request_id is not None and not request_id.strip():
            raise TypeError("request_id 必须是非空字符串或 None")
        super().__init__(message)  # 调用 Exception 基类构造器
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id


class ModelRateLimitError(ModelAPIError):
    """HTTP 429；Retry-After 保留原始字符串，由恢复层解析。

    这是什么：速率限制错误的专用异常
    Java 类比：类似 RateLimitException
    为什么需要：429 需要特殊处理（遵守 Retry-After 头）

    核心字段：
        retry_after: Retry-After 头的原始字符串（可能是秒数或 HTTP-date）

    恢复策略：
        - 优先遵守 Retry-After 头
        - 没有该头时使用指数退避
        - 清零 consecutive_529 计数（429 说明模型可用）
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: str | None = None,  # Retry-After 头的原始值
        status_code: int = 429,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """初始化限流错误。

        Java 对照：子类构造器校验，确保 status_code 匹配
        """
        # 强制校验 status_code 必须是 429
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
        self.retry_after = retry_after  # 保存原始字符串，由恢复层解析


class ModelOverloadedError(ModelAPIError):
    """HTTP 529；连续次数和 fallback 由 RecoveryManager 管理。

    这是什么：模型过载错误的专用异常
    Java 类比：类似 ServiceUnavailableException
    为什么需要：529 需要特殊处理（连续 3 次切换 fallback）

    恢复策略：
        - consecutive_529 计数 +1
        - 达到阈值（默认 3 次）切换到 fallback 模型
        - 使用指数退避重试
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 529,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """初始化过载错误。

        Java 对照：子类构造器校验
        """
        # 强制校验 status_code 必须是 529
        if status_code != 529:
            raise ValueError("ModelOverloadedError 的 status_code 必须是 529")
        super().__init__(
            message,
            status_code=status_code,
            error_code=error_code,
            request_id=request_id,
        )


class ModelPromptTooLongError(ModelAPIError):
    """HTTP 400 且带明确 context-length error code。

    这是什么：输入过长错误的专用异常
    Java 类比：类似 PayloadTooLargeException
    为什么需要：输入过长需要特殊处理（保留 system，压缩历史）

    恢复策略：
        - 分离首条 system message（保留）
        - 调用 CompactionManager 压缩其余历史
        - 一次请求只压缩一次（避免递归）
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """初始化输入过长错误。

        Java 对照：子类构造器校验
        """
        # 强制校验 status_code 必须是 400
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
