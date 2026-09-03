“””模型边界契约。

这里故意不导入 OpenAI SDK。核心循环只知道”有一个对象能完成一次模型请求”，
这就像 Java Service 只依赖 `ModelClient` 接口，而不是直接依赖某个厂商 SDK。

这是什么：定义模型交互的接口和数据传输对象
Java 类比：类似定义 Service 层的接口和 DTO，遵循依赖倒置原则
为什么需要：让核心逻辑不依赖具体实现，便于测试和替换不同模型供应商
“””

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

# 模型完成原因：类似 Java 的枚举
FinishReason = Literal[“stop”, “length”, “tool_calls”, “content_filter”, “function_call”]


@dataclass(frozen=True, slots=True)
class OpenAIToolSchema:
    “””发给 OpenAI 兼容接口的工具说明。

    这是什么：工具定义的 OpenAI 格式数据对象
    Java 类比：类似 record OpenAIToolSchema(String name, String description, Map parameters)
    为什么需要：模型不能直接读取 Python 函数，需要转换成 JSON Schema 格式

    参数：
        name: 模型调用时使用的函数名
        description: 给模型看的用途说明
        parameters: JSON Schema，描述参数类型和必填字段
    “””

    name: str  # 工具名称
    description: str  # 工具描述
    parameters: dict[str, Any]  # 参数 JSON Schema

    def as_openai(self) -> dict[str, Any]:
        “””转换为 OpenAI Chat Completions 接口要求的嵌套字典。

        这是什么：格式转换方法
        Java 类比：类似 toOpenAIFormat() 方法
        为什么需要：OpenAI API 要求特定的嵌套结构

        返回：
            dict: OpenAI 格式的工具定义
        “””
        return {
            “type”: “function”,
            “function”: {
                “name”: self.name,
                “description”: self.description,
                “parameters”: self.parameters,
            },
        }


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次模型请求的完整输入。

    这是什么：模型请求的数据传输对象
    Java 类比：类似 record ModelRequest(List<Message> messages, List<Tool> tools, ...)
    为什么需要：封装请求参数，确保参数不可变且类型安全

    参数：
        messages: 本轮模型能看到的消息历史
        tools: 本轮允许模型调用的工具
        model: 可选覆盖默认模型
        max_tokens: 可选的单轮输出 token 上限
    """

    messages: tuple[ChatMessage, ...]  # 消息历史
    tools: tuple[OpenAIToolSchema, ...]  # 工具列表
    model: str | None = None  # 可选模型名称
    max_tokens: int | None = None  # 可选 token 限制


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """模型 token 使用统计。

    这是什么：token 计费统计对象
    Java 类比：类似 record TokenUsage(int prompt, int completion, int total)
    为什么需要：跟踪模型调用成本，用于计费和性能分析

    参数：
        prompt_tokens: 输入消息消耗的 token 数
        completion_tokens: 模型输出消耗的 token 数
        total_tokens: 输入和输出之和
    """

    prompt_tokens: int  # 输入 token
    completion_tokens: int  # 输出 token
    total_tokens: int  # 总 token


@dataclass(frozen=True, slots=True)
class ModelReply:
    """适配器转换后的统一模型响应。

    这是什么：模型响应的数据传输对象
    Java 类比：类似 record ModelReply(AssistantMessage message, FinishReason reason, ...)
    为什么需要：统一不同供应商的响应格式，核心逻辑只处理标准化数据

    参数：
        message: 已转换成内部消息对象的模型回答
        finish_reason: stop、tool_calls、length 等结束原因
        usage: 有些供应商不返回用量，所以允许为空
    """

    message: AssistantMessage  # 模型消息
    finish_reason: FinishReason  # 完成原因
    usage: TokenUsage | None = None  # 可选 token 统计


class ModelClient(Protocol):
    """模型客户端接口，遵循依赖倒置原则。

    这是什么：模型交互的抽象接口
    Java 类比：类似 interface ModelClient { ModelReply complete(ModelRequest req); }
    为什么需要：核心循环只依赖接口不依赖实现，便于测试和替换供应商

    实现者：真实适配器（OpenAI、DeepSeek）和测试 Fake 只需实现 complete 方法
    """

    def complete(self, request: ModelRequest) -> ModelReply:
        """向模型发送一轮规范化请求，并返回核心层统一的响应。

        这是什么：模型调用的核心方法
        Java 类比：类似 ModelReply execute(ModelRequest request) throws ModelException
        为什么需要：定义统一的模型调用契约

        参数：
            request: 标准化的模型请求对象

        返回：
            ModelReply: 标准化的模型响应对象
        """
        ...
