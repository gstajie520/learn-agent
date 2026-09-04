"""模型边界契约。

这是什么：定义模型调用接口和数据结构的核心模块
Java 类比：类似 ModelClient 接口和相关的 DTO 类
为什么需要：抽象模型调用细节，让核心逻辑不依赖具体的 SDK 或 API

这里故意不导入 OpenAI SDK。核心循环只知道"有一个对象能完成一次模型请求"，
这就像 Java Service 只依赖 `ModelClient` 接口，而不是直接依赖某个厂商 SDK。
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "function_call"]


@dataclass(frozen=True, slots=True)
class OpenAIToolSchema:
    """发给 OpenAI 兼容接口的工具说明。

    这是什么：描述工具的 JSON Schema 结构
    Java 类比：类似 record ToolSchema(String name, String description, Map<String, Object> parameters)
    为什么需要：模型无法直接读取 Python 代码，需要用 JSON Schema 描述工具

    模型不会直接读取 Python 函数，它只能读取 JSON Schema，
    所以注册表需要把 Python 工具转换成这个结构。
    """

    name: str  # 模型调用时使用的函数名。
    description: str  # 给模型看的用途说明。
    parameters: dict[str, Any]  # JSON Schema，描述参数类型和必填字段。

    def as_openai(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 接口要求的嵌套字典。

        这是什么：将内部格式转换为 OpenAI API 格式
        Java 类比：类似 toOpenAIFormat() 或 Converter.convert(this)
        为什么需要：适配 OpenAI 的 tools 参数格式要求
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

    这是什么：封装模型调用所需的所有参数
    Java 类比：类似 record ModelRequest(List<ChatMessage> messages, List<ToolSchema> tools, ...)
    为什么需要：将分散的参数打包成一个对象，便于传递和扩展
    """

    messages: tuple[ChatMessage, ...]  # 本轮模型能看到的消息历史。
    tools: tuple[OpenAIToolSchema, ...]  # 本轮允许模型调用的工具。
    model: str | None = None  # 可选覆盖默认模型。
    max_tokens: int | None = None  # 可选的单轮输出 token 上限。


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token 使用情况的统计。

    这是什么：记录 token 消耗的值对象
    Java 类比：类似 record TokenUsage(int promptTokens, int completionTokens, int totalTokens)
    为什么需要：追踪 API 调用的成本，便于配额管理和审计
    """
    prompt_tokens: int  # 输入消息消耗的 token 数。
    completion_tokens: int  # 模型输出消耗的 token 数。
    total_tokens: int  # 输入和输出之和。


@dataclass(frozen=True, slots=True)
class ModelReply:
    """适配器转换后的统一模型响应。

    这是什么：封装模型返回结果的值对象
    Java 类比：类似 record ModelReply(AssistantMessage message, FinishReason finishReason, ...)
    为什么需要：统一不同模型供应商的响应格式，提供类型安全的访问接口
    """

    message: AssistantMessage  # 已转换成内部消息对象的模型回答。
    finish_reason: FinishReason  # stop、tool_calls、length 等结束原因。
    usage: TokenUsage | None = None  # 有些供应商不返回用量，所以允许为空。


class ModelClient(Protocol):
    """模型客户端接口，类似 Java interface。

    这是什么：定义模型调用契约的协议接口
    Java 类比：类似 interface ModelClient { ModelReply complete(ModelRequest); }
    为什么需要：核心层只依赖接口，不依赖具体实现，支持切换供应商和测试替换

    核心循环只依赖这个协议，不关心 HTTP、鉴权和第三方 SDK；这正是依赖倒置
    的效果。真实适配器和测试 Fake 只要实现 `complete` 就可以被注入。
    """

    def complete(self, request: ModelRequest) -> ModelReply:
        """向模型发送一轮规范化请求，并返回核心层统一的响应。

        这是什么：执行模型调用的核心方法
        Java 类比：类似 ModelReply complete(ModelRequest request)
        为什么需要：定义统一的模型调用契约，让所有实现遵守相同的输入输出格式
        """
