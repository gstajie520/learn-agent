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

    这是什么：工具定义的 OpenAI 格式值对象
    Java 类比：类似 record ToolSchema(String name, String description, Map<String, Object> parameters)
    为什么需要：模型只能读取 JSON Schema 而非 Python 函数，需将工具定义转换为模型理解的格式
    """
    name: str  # 模型调用时使用的函数名
    description: str  # 给模型看的用途说明
    parameters: dict[str, Any]  # JSON Schema，描述参数类型和必填字段

    def as_openai(self) -> dict[str, Any]:
        """转换为 OpenAI Chat Completions 接口要求的嵌套字典。

        这是什么：OpenAI API 格式转换器
        Java 类比：类似 Map<String, Object> toOpenAIFormat()
        为什么需要：OpenAI API 要求特定的嵌套结构（type + function 字段），需按规范封装
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

    这是什么：模型调用请求的值对象
    Java 类比：类似 record ModelRequest(List<ChatMessage> messages, List<ToolSchema> tools, String model, Integer maxTokens)
    为什么需要：封装模型请求的所有输入参数，确保消息历史、工具列表和配置项完整传递
    """
    messages: tuple[ChatMessage, ...]  # 本轮模型能看到的消息历史
    tools: tuple[OpenAIToolSchema, ...]  # 本轮允许模型调用的工具
    model: str | None = None  # 可选覆盖默认模型
    max_tokens: int | None = None  # 可选的单轮输出 token 上限


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token 使用统计。

    这是什么：模型调用的 token 消耗统计值对象
    Java 类比：类似 record TokenUsage(int promptTokens, int completionTokens, int totalTokens)
    为什么需要：记录每次调用的 token 消耗，便于成本核算和限额控制
    """
    prompt_tokens: int  # 输入消息消耗的 token 数
    completion_tokens: int  # 模型输出消耗的 token 数
    total_tokens: int  # 输入和输出之和


@dataclass(frozen=True, slots=True)
class ModelReply:
    """适配器转换后的统一模型响应。

    这是什么：模型回复的值对象
    Java 类比：类似 record ModelReply(AssistantMessage message, FinishReason reason, TokenUsage usage)
    为什么需要：封装模型返回的消息、结束原因和 token 统计，让核心层不依赖供应商特定格式
    """
    message: AssistantMessage  # 已转换成内部消息对象的模型回答
    finish_reason: FinishReason  # stop、tool_calls、length 等结束原因
    usage: TokenUsage | None = None  # 有些供应商不返回用量，所以允许为空


class ModelClient(Protocol):
    """模型客户端接口，类似 Java interface。

    这是什么：模型调用的协议定义
    Java 类比：类似 interface ModelClient { ModelReply complete(ModelRequest request); }
    为什么需要：核心层只依赖接口不依赖具体实现（依赖倒置），让真实适配器和测试 Fake 可替换
    """

    def complete(self, request: ModelRequest) -> ModelReply:
        """向模型发送一轮规范化请求，并返回核心层统一的响应。

        这是什么：模型调用的抽象方法
        Java 类比：类似接口中的 ModelReply callModel(ModelRequest request)
        为什么需要：定义统一契约，屏蔽 HTTP 通信、鉴权和供应商 SDK 差异
        """
