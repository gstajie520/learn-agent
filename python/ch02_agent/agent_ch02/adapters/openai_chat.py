"""OpenAI Chat Completions 适配器。

DeepSeek 等兼容 OpenAI 协议的服务也通过这里接入。外部 SDK 返回值先在本层
校验，再转换成核心层的 ModelReply，避免脏数据进入 Agent Loop。
"""

from typing import Any

from openai import OpenAI

from ..config import OpenAISettings
from ..core.messages import assistant_message, tool_call, validate_tool_pairing
from ..core.model import ModelClient, ModelReply, ModelRequest, TokenUsage


class OpenAIResponseError(Exception):
    """供应商响应不符合 Chat Completions 契约。

    这是什么：模型响应格式异常
    Java 类比：类似 InvalidProviderResponseException，表示 HTTP 成功但数据不符合预期
    为什么需要：将外部 API 的格式错误与网络错误区分开，便于精确诊断和重试策略

    Java 对照：类似 `InvalidProviderResponseException`，表示 HTTP 请求可能成功了，
    但响应内容的字段、角色或结束原因不符合本项目要求。
    """


class OpenAIChatModel(ModelClient):
    """ModelClient 的真实 OpenAI 兼容实现。

    这是什么：OpenAI Chat Completions 协议的适配器实现
    Java 类比：类似 @Component class OpenAIAdapter implements ModelClient
    为什么需要：封装 OpenAI SDK 细节，统一 DeepSeek/OpenAI 等兼容服务的接入方式

    DeepSeek 实现了相同的 Chat Completions 协议，所以只需更换 base_url、key 和模型名。
    """

    def __init__(self, settings: OpenAISettings, client: Any | None = None) -> None:
        """初始化 OpenAI 兼容客户端。

        这是什么：构造器，接收配置和可选的客户端实例
        Java 类比：类似构造器注入 OpenAISettings，client 参数用于依赖注入测试替身
        为什么需要：支持生产环境使用真实 SDK，测试环境注入 Mock 客户端
        """
        # client 可选是为了测试：生产环境创建真实 SDK，测试环境传入 FakeClient。
        self._client = client or OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0)
        self._model = settings.model  # 没有单次覆盖时默认使用的模型名称。

    def complete(self, request: ModelRequest) -> ModelReply:
        """把内部请求转换成 SDK 请求，再把 SDK 响应转换回内部对象。

        这是什么：模型调用的核心方法，执行请求转换和响应解析
        Java 类比：类似 ModelReply complete(ModelRequest request) throws IOException
        为什么需要：实现 ModelClient 接口契约，隔离外部 SDK 的数据格式变化
        """

        # 先在本地检查历史，避免用一份已损坏的消息浪费网络请求和 token。
        validate_tool_pairing(list(request.messages))
        if request.max_tokens is not None and (request.max_tokens <= 0 or int(request.max_tokens) != request.max_tokens):  # 验证 max_tokens 是正整数
            raise ValueError("max_tokens 必须是正整数")
        # payload 就是最终发给 DeepSeek/OpenAI 的 JSON 请求体。
        payload: dict[str, Any] = {
            "model": request.model or self._model,  # 请求指定模型优先，否则用配置默认模型
            "messages": [_to_openai_message(message) for message in request.messages],  # 转换消息格式
        }
        if request.tools:  # 有工具定义时添加到请求
            payload["tools"] = [tool.as_openai() for tool in request.tools]
        if request.max_tokens is not None:  # 限制最大输出 token 数
            payload["max_completion_tokens"] = request.max_tokens
        # **payload 类似把 Java Map 中的键值展开成方法参数。
        response = self._client.chat.completions.create(**payload)  # 调用 OpenAI SDK
        return _normalize_response(response)  # 校验并转换响应格式


def _to_openai_message(message: Any) -> dict[str, Any]:
    """把内部 dataclass 消息转换成供应商要求的字典格式。

    这是什么：消息格式转换器，将内部消息对象映射为 OpenAI API 格式
    Java 类比：类似 static Map<String, Object> toApiMessage(ChatMessage message)
    为什么需要：隔离内部数据结构和外部 API 契约，避免直接耦合第三方格式

    Java 对照：类似把内部 DTO 映射成第三方 SDK Request DTO。
    函数名前面的单下划线表示"仅供本模块内部使用"，近似 Java 的 private 方法约定。
    """
    if message.role in {"system", "user"}:  # 系统和用户消息只需 role 和 content
        return {"role": message.role, "content": message.content}
    if message.role == "tool":  # 工具消息需要额外的 tool_call_id 字段
        return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id}
    result: dict[str, Any] = {"role": "assistant", "content": message.content}  # assistant 消息基础结构
    if message.tool_calls:  # 有工具调用时添加 tool_calls 数组
        result["tool_calls"] = [{"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}} for call in message.tool_calls]
    return result


def _normalize_response(response: Any) -> ModelReply:
    """校验外部响应，并转换成核心层认识的 ModelReply。

    这是什么：响应校验和转换器，将外部 API 响应映射为内部领域对象
    Java 类比：类似 static ModelReply parseAndValidate(ApiResponse response) throws ValidationException
    为什么需要：外部 API 数据属于不可信边界，必须运行时校验，防止脏数据污染核心逻辑

    SDK 返回的数据属于不可信边界，就像 Controller 收到的外部请求一样，
    不能因为有类型提示就跳过运行时校验。
    """
    try:
        if not isinstance(response.choices, list) or len(response.choices) != 1:  # 必须恰好一个候选结果
            raise OpenAIResponseError("Chat Completions 响应必须恰好包含一个候选结果")
        choice = response.choices[0]  # 本章只接受一个候选回答，等价于 Java 的 list.get(0)。
        reason = choice.finish_reason  # 结束原因：stop/length/tool_calls/content_filter
        if reason not in {"stop", "length", "tool_calls", "content_filter", "function_call"}:  # 校验结束原因合法性
            raise OpenAIResponseError(f"不支持的 finish_reason: {reason}")
        if reason == "function_call":  # 拒绝旧版 function_call 协议
            raise OpenAIResponseError("不支持旧版 function_call 结束原因")
        message = choice.message  # 提取 assistant 消息
        if message.role != "assistant":  # 角色必须是 assistant
            raise OpenAIResponseError("Chat Completions 消息的 role 必须是 assistant")
        content = message.content if isinstance(message.content, str) else None  # 提取文本内容
        if content is None and isinstance(getattr(message, "refusal", None), str):  # 处理拒绝回复
            content = message.refusal
        # 这是生成器表达式：把供应商的每个调用映射为内部 ToolCall，类似 Java stream().map(...).toList()。
        calls = tuple(tool_call(call.id, call.function.name, call.function.arguments) for call in (message.tool_calls or []))
        usage = None  # 提取 token 使用量
        if response.usage is not None:
            usage = TokenUsage(response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total_tokens)
        return ModelReply(assistant_message(content, calls), reason, usage)  # 构造内部响应对象
    except OpenAIResponseError:  # 已知的响应错误直接抛出
        raise
    except Exception as error:  # 其他异常统一包装为响应错误
        raise OpenAIResponseError(f"Chat Completions 响应格式不正确: {error}") from error
