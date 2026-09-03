“””模型边界契约。

这是什么：定义与大语言模型交互的接口和数据结构
Java 类比：interface ModelClient，遵循依赖倒置原则
为什么需要：隔离模型实现细节，核心循环不依赖具体的 SDK（OpenAI、DeepSeek等）

这里故意不导入 OpenAI SDK。核心循环只知道”有一个对象能完成一次模型请求”，
这就像 Java Service 只依赖 `ModelClient` 接口，而不是直接依赖某个厂商 SDK。
“””

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]  # 模型停止原因


@dataclass(frozen=True, slots=True)
class OpenAIToolSchema:
    """发给 OpenAI 兼容接口的工具说明。

    这是什么：工具的 JSON Schema 定义，供模型理解工具用途和参数
    Java 类比：record OpenAIToolSchema(String name, String description, Map parameters)
    为什么需要：模型无法直接读取 Python 代码，需要标准化的 JSON Schema 描述

    模型不会直接读取 Python 函数，它只能读取 JSON Schema，
    所以注册表需要把 Python 工具转换成这个结构。
    """

    name: str  # 模型调用时使用的函数名。
    description: str  # 给模型看的用途说明。
    parameters: dict[str, Any]  # JSON Schema，描述参数类型和必填字段。

    def as_openai(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 接口要求的嵌套字典。

        这是什么：格式转换方法，生成 OpenAI API 要求的工具定义格式
        Java 类比：public Map<String, Object> toOpenAIFormat()
        为什么需要：适配 OpenAI API 的特定嵌套结构要求
        """
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
