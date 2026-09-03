“””模型边界契约。

这里故意不导入 OpenAI SDK。核心循环只知道”有一个对象能完成一次模型请求”，
这就像 Java Service 只依赖 `ModelClient` 接口，而不是直接依赖某个厂商 SDK。

Java 对照：这个模块定义了模型层的接口和 DTO，类似 Java 中的
interface ModelClient + record ModelRequest/ModelReply。
“””

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .messages import AssistantMessage, ChatMessage

# 模型停止原因的字面量联合类型，类似 Java 的枚举
FinishReason = Literal[“stop”, “length”, “tool_calls”, “content_filter”, “function_call”]


@dataclass(frozen=True, slots=True)
class OpenAIToolSchema:
    “””发给 OpenAI 兼容接口的工具说明。

    这是什么：工具定义的传输对象，用于告诉模型有哪些函数可调用
    Java 类比：类似 record ToolSchema(String name, String description, Map<String, Object> parameters)
    为什么需要：模型 API 不能直接读取 Python 函数，必须用 JSON Schema 描述参数格式
    “””
    name: str  # 模型调用时使用的函数名
    description: str  # 给模型看的用途说明，影响模型选择工具的准确性
    parameters: dict[str, Any]  # JSON Schema 对象，定义参数类型和必填字段

    def as_openai(self) -> dict[str, Any]:
        “””转换为 OpenAI Chat Completions 接口要求的嵌套字典。

        这是什么：序列化方法，把 Python 对象转换成 API 要求的 JSON 格式
        Java 类比：类似 toApiFormat() 方法，返回 Map<String, Object>
        为什么需要：OpenAI API 要求工具定义必须嵌套在 {“type”: “function”, “function”: {...}} 结构中
        “””
        # OpenAI API 要求的固定结构：type 必须是 “function”，实际定义放在 function 字段下
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

    这是什么：发给模型的请求参数封装
    Java 类比：record ModelRequest(List<ChatMessage> messages, List<ToolSchema> tools, ...)
    为什么需要：把所有请求参数统一打包，避免接口方法参数过多
    """
    messages: tuple[ChatMessage, ...]  # 本轮模型能看到的消息历史，tuple 保证不可变
    tools: tuple[OpenAIToolSchema, ...]  # 本轮允许模型调用的工具列表
    model: str | None = None  # 可选覆盖默认模型，用于同一任务切换不同能力的模型
    max_tokens: int | None = None  # 可选的单轮输出 token 上限，防止成本失控


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """模型调用的 token 消耗统计。

    这是什么：记录一次模型调用的计费单位
    Java 类比：record TokenUsage(int promptTokens, int completionTokens, int totalTokens)
    为什么需要：用于成本追踪和性能分析，某些供应商按 token 数计费
    """
    prompt_tokens: int  # 输入消息消耗的 token 数（问题部分）
    completion_tokens: int  # 模型输出消耗的 token 数（回答部分）
    total_tokens: int  # 输入和输出之和，通常等于前两者相加


@dataclass(frozen=True, slots=True)
class ModelReply:
    """适配器转换后的统一模型响应。

    这是什么：模型返回的标准化响应对象
    Java 类比：record ModelReply(AssistantMessage message, FinishReason finishReason, TokenUsage usage)
    为什么需要：统一不同供应商（OpenAI/DeepSeek/Claude）的响应格式
    """
    message: AssistantMessage  # 已转换成内部消息对象的模型回答
    finish_reason: FinishReason  # 结束原因：stop（正常完成）、length（token 超限）等
    usage: TokenUsage | None = None  # 有些供应商不返回用量，所以允许为空


class ModelClient(Protocol):  # Protocol = Java 的 interface
    """模型客户端接口，类似 Java interface。

    这是什么：定义模型层的契约，核心循环通过此接口与模型通信
    Java 类比：interface ModelClient { ModelReply complete(ModelRequest request); }
    为什么需要：依赖倒置原则，核心层不依赖具体供应商 SDK，测试时可注入 Fake

    核心循环只依赖这个协议，不关心 HTTP、鉴权和第三方 SDK；这正是依赖倒置
    的效果。真实适配器和测试 Fake 只要实现 `complete` 就可以被注入。
    """

    def complete(self, request: ModelRequest) -> ModelReply:
        """向模型发送一轮规范化请求，并返回核心层统一的响应。

        这是什么：模型调用的唯一入口方法
        Java 类比：ModelReply complete(ModelRequest request) throws IOException
        为什么需要：封装所有供应商差异，让核心层只关心"输入消息+工具→输出消息"
        """
        ...  # Protocol 接口方法，类似 Java 接口中的抽象方法声明
