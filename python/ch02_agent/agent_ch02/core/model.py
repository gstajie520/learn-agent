"""模型边界契约。

这是什么：模型调用的领域接口和数据传输对象定义
Java 类比：类似定义 ModelClient 接口和 Request/Response DTO
为什么需要：隔离模型供应商细节，让核心层不依赖具体的 SDK 实现

这里故意不导入 OpenAI SDK。核心循环只知道"有一个对象能完成一次模型请求"，
这就像 Java Service 只依赖 `ModelClient` 接口，而不是直接依赖某个厂商 SDK。
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]  # 结束原因枚举


@dataclass(frozen=True, slots=True)
class OpenAIToolSchema:
    """发给 OpenAI 兼容接口的工具说明。

    这是什么：工具定义的数据传输对象，符合 OpenAI 格式
    Java 类比：类似 record ToolSchema(String name, String description, Map<String, Object> parameters)
    为什么需要：将内部工具定义转换为模型能理解的 JSON Schema 格式

    模型不会直接读取 Python 函数，它只能读取 JSON Schema，
    所以注册表需要把 Python 工具转换成这个结构。
    """
    name: str  # 模型调用时使用的函数名。
    description: str  # 给模型看的用途说明。
    parameters: dict[str, Any]  # JSON Schema，描述参数类型和必填字段。

    def as_openai(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 接口要求的嵌套字典。

        这是什么：格式转换方法，生成 OpenAI API 所需的字典结构
        Java 类比：类似 Map<String, Object> toOpenAIFormat()
        为什么需要：适配 OpenAI 的嵌套格式要求，封装转换逻辑
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
    """一次模型请求的完整输入。

    这是什么：模型请求的值对象，封装所有请求参数
    Java 类比：类似 record ModelRequest(List<ChatMessage> messages, List<ToolSchema> tools, ...)
    为什么需要：统一模型请求格式，便于传递和验证
    """
    messages: tuple[ChatMessage, ...]  # 本轮模型能看到的消息历史。
    tools: tuple[OpenAIToolSchema, ...]  # 本轮允许模型调用的工具。
    model: str | None = None  # 可选覆盖默认模型。
    max_tokens: int | None = None  # 可选的单轮输出 token 上限。


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token 使用量统计。

    这是什么：Token 消耗统计的值对象
    Java 类比：类似 record TokenUsage(int promptTokens, int completionTokens, int totalTokens)
    为什么需要：记录成本和监控模型使用情况
    """
    prompt_tokens: int  # 输入消息消耗的 token 数。
    completion_tokens: int  # 模型输出消耗的 token 数。
    total_tokens: int  # 输入和输出之和。


@dataclass(frozen=True, slots=True)
class ModelReply:
    """适配器转换后的统一模型响应。

    这是什么：模型响应的值对象，封装所有响应数据
    Java 类比：类似 record ModelReply(AssistantMessage message, FinishReason finishReason, TokenUsage usage)
    为什么需要：统一不同供应商的响应格式，提供类型安全的访问
    """
    message: AssistantMessage  # 已转换成内部消息对象的模型回答。
    finish_reason: FinishReason  # stop、tool_calls、length 等结束原因。
    usage: TokenUsage | None = None  # 有些供应商不返回用量，所以允许为空。


class ModelClient(Protocol):
    """模型客户端接口，类似 Java interface。

    这是什么：模型客户端的接口定义（Protocol）
    Java 类比：interface ModelClient { ModelReply complete(ModelRequest request) throws IOException; }
    为什么需要：定义模型调用契约，支持依赖倒置，便于测试和替换供应商

    核心循环只依赖这个协议，不关心 HTTP、鉴权和第三方 SDK；这正是依赖倒置
    的效果。真实适配器和测试 Fake 只要实现 `complete` 就可以被注入。
    """

    def complete(self, request: ModelRequest) -> ModelReply:
        """向模型发送一轮规范化请求，并返回核心层统一的响应。

        这是什么：模型调用的核心方法签名
        Java 类比：ModelReply complete(ModelRequest request) throws IOException
        为什么需要：定义统一的模型调用接口，隔离供应商差异
        """
