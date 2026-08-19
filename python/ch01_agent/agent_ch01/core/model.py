"""模型边界契约。

这里故意不导入 OpenAI SDK。核心循环只知道“有一个对象能完成一次模型请求”，
这就像 Java Service 只依赖 `ModelClient` 接口，而不是直接依赖某个厂商 SDK。
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]


@dataclass(frozen=True, slots=True)
class OpenAIToolSchema:
    """发给 OpenAI 兼容接口的工具说明。

    模型不会直接读取 Python 函数，它只能读取 JSON Schema，
    所以注册表需要把 Python 工具转换成这个结构。
    """
    name: str
    description: str
    parameters: dict[str, Any]

    def as_openai(self) -> dict[str, Any]:
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
    messages: tuple[ChatMessage, ...]
    tools: tuple[OpenAIToolSchema, ...]
    model: str | None = None
    max_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class ModelReply:
    """适配器转换后的统一模型响应。"""
    message: AssistantMessage
    finish_reason: FinishReason
    usage: TokenUsage | None = None


class ModelClient(Protocol):
    """模型客户端接口，类似 Java interface。"""

    def complete(self, request: ModelRequest) -> ModelReply:
        """向模型发送一轮规范化请求。"""
