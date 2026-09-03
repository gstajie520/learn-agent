"""OpenAI Chat Completions 适配器。

这是什么：
    OpenAI/DeepSeek 等兼容供应商的 ModelClient 实现。

Java 类比：
    类似 Adapter 层，把第三方 SDK 的异常和响应转换为内部领域对象。
    这就是"Adapter 层把第三方异常转换成领域异常"的标准做法。

为什么需要：
    1. 核心层不应依赖 OpenAI SDK 的具体类型
    2. 外部 SDK 返回值先在本层校验，避免脏数据进入 Agent Loop
    3. 切换供应商（改用 Anthropic）时只需修改适配器层

核心职责：
    1. 异常映射：APIStatusError → ModelRateLimitError 等
    2. 响应转换：ChatCompletion → ModelReply
    3. 消息格式：ChatMessage → OpenAI 消息字典
"""

from typing import Any

from openai import APIStatusError, OpenAI

from ..config import OpenAISettings
from ..core.messages import assistant_message, tool_call, validate_tool_pairing
from ..core.model import (
    ModelClient,
    ModelOverloadedError,
    ModelPromptTooLongError,
    ModelRateLimitError,
    ModelReply,
    ModelRequest,
    TokenUsage,
)

PROMPT_TOO_LONG_CODES = frozenset(  # 各供应商的输入过长错误码集合
    {"context_length_exceeded", "max_context_window", "prompt_is_too_long", "prompt_too_long"}
)


class OpenAIResponseError(Exception):
    """供应商响应不符合 Chat Completions 契约。

    这是什么：适配器层的响应校验异常
    Java 类比：类似 InvalidProviderResponseException
    为什么需要：HTTP 请求可能成功，但响应字段不符合预期（如缺少 message、角色错误）

    触发场景：
        - 响应缺少 choices[0].message
        - message.role 不是 "assistant"
        - finish_reason 不在预期范围
        - tool_calls 格式错误
    """


class OpenAIChatModel(ModelClient):
    """ModelClient 的真实 OpenAI 兼容实现。

    这是什么：适配器模式的具体实现
    Java 类比：类似实现 ModelClient 接口的 OpenAIAdapter
    为什么需要：把 OpenAI SDK 的调用封装为统一接口

    兼容性：
        DeepSeek 实现了相同的 Chat Completions 协议，
        所以只需更换 base_url、key 和模型名即可接入。

    核心职责：
        1. 把 ModelRequest 转换为 OpenAI SDK 请求
        2. 捕获 APIStatusError 并映射为领域异常
        3. 把 ChatCompletion 响应转换为 ModelReply
    """

    def __init__(self, settings: OpenAISettings, client: Any | None = None) -> None:
        """初始化 OpenAI 客户端。

        Java 对照：构造器注入配置
        参数：
            settings: OpenAI 配置（base_url、api_key、model）
            client: 可选的 SDK 客户端（测试时注入 FakeClient）
        """
        # client 可选是为了测试：生产环境创建真实 SDK，测试环境传入 FakeClient。
        self._client = client or OpenAI(
            api_key=settings.api_key, base_url=settings.base_url, max_retries=0  # 重试由恢复层统一管理
        )
        self._model = settings.model  # 没有单次覆盖时默认使用的模型名称。

    def complete(self, request: ModelRequest) -> ModelReply:
        """把内部请求转换成 SDK 请求，再把 SDK 响应转换回内部对象。

        这是什么：ModelClient 接口的实现方法
        Java 类比：public ModelReply complete(ModelRequest req) throws ModelAPIError
        为什么需要：核心层只调用这个方法，不知道底层是 HTTP 还是 gRPC

        流程：
            1. 校验请求合法性（工具配对、max_tokens）
            2. 构造 OpenAI SDK 的 payload
            3. 调用 SDK（捕获 APIStatusError 并映射）
            4. 校验响应并转换为 ModelReply

        异常映射：
            APIStatusError → ModelRateLimitError / ModelOverloadedError / ModelPromptTooLongError
        """

        # 先在本地检查历史，避免用一份已损坏的消息浪费网络请求和 token。
        validate_tool_pairing(list(request.messages))
        if request.max_tokens is not None and (
            request.max_tokens <= 0 or int(request.max_tokens) != request.max_tokens
        ):
            raise ValueError("max_tokens 必须是正整数")
        # payload 就是最终发给 DeepSeek/OpenAI 的 JSON 请求体。
        payload: dict[str, Any] = {
            "model": request.model or self._model,  # 使用请求覆盖值或默认模型
            "messages": [_to_openai_message(message) for message in request.messages],  # 转换消息格式
        }
        if request.tools:  # 如果有工具定义，转换为 OpenAI 格式
            payload["tools"] = [tool.as_openai() for tool in request.tools]
        if request.max_tokens is not None:  # 如果有 token 上限，设置字段
            payload["max_completion_tokens"] = request.max_tokens
        # **payload 类似把 Java Map 中的键值展开成方法参数。
        try:
            response = self._client.chat.completions.create(**payload)  # 调用 OpenAI SDK
        except APIStatusError as error:  # 捕获 OpenAI SDK 的 HTTP 错误
            mapped = _map_api_status_error(error)  # 映射为领域异常
            if mapped is None:  # 未知错误码，原样抛出
                raise
            raise mapped from error  # 抛出映射后的领域异常（保留原始异常链）
        return _normalize_response(response)  # 校验并转换响应


def _map_api_status_error(error: APIStatusError) -> Exception | None:
    """只根据稳定 status/body/header 字段分类，不匹配异常文本。

    这是什么：异常映射器，把 OpenAI SDK 的 APIStatusError 转换为领域异常
    Java 类比：类似 ExceptionMapper 或 switch 表达式
    为什么需要：不能用 "429" in str(error) 这种脆弱判断，必须读取结构化字段

    映射规则：
        429 + Retry-After 头 → ModelRateLimitError
        529 → ModelOverloadedError
        400 + context_length_exceeded 等错误码 → ModelPromptTooLongError
        其他 → None（返回 None 表示无法映射，原样抛出）

    参数：
        error: OpenAI SDK 的 APIStatusError

    返回：
        映射后的领域异常，或 None（无法映射）

    为什么不匹配文本：
        1. 错误文本可能随供应商版本变化
        2. 多语言环境下文本可能不是英文
        3. 结构化字段（status_code、error.code）是稳定契约
    """
    status = getattr(error, "status_code", None)  # 读取 HTTP 状态码
    if not isinstance(status, int):  # 状态码必须是整数
        return None
    body = getattr(error, "body", None)  # 读取响应体（可能包含错误码）
    error_code = _structured_error_identifier(body)  # 提取供应商错误码
    request_id = _non_empty_text(getattr(error, "request_id", None))  # 提取请求 ID
    if status == 429:  # HTTP 429 限流
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        # 读取 Retry-After 头（可能是秒数或 HTTP-date）
        retry_after = _non_empty_text(headers.get("retry-after")) if headers is not None else None
        return ModelRateLimitError(
            "OpenAI 请求被限流",
            retry_after=retry_after,  # 保存原始字符串，由恢复层解析
            error_code=error_code,
            request_id=request_id,
        )
    if status == 529:  # HTTP 529 模型过载
        return ModelOverloadedError(
            "OpenAI 模型暂时过载", error_code=error_code, request_id=request_id
        )
    if status == 400 and error_code in PROMPT_TOO_LONG_CODES:  # HTTP 400 且错误码匹配
        return ModelPromptTooLongError(
            "OpenAI 输入超过模型上下文窗口",
            error_code=error_code,
            request_id=request_id,
        )
    return None


def _structured_error_identifier(body: object) -> str | None:
    if not isinstance(body, dict):
        return None
    candidates = [body]
    nested = body.get("error")
    if isinstance(nested, dict):
        candidates.append(nested)
    for candidate in candidates:
        for field in ("code", "type"):
            value = _non_empty_text(candidate.get(field))
            if value is not None:
                return value.lower()
    return None


def _non_empty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _to_openai_message(message: Any) -> dict[str, Any]:
    """把内部 dataclass 消息转换成供应商要求的字典格式。

    Java 对照：类似把内部 DTO 映射成第三方 SDK Request DTO。
    函数名前面的单下划线表示“仅供本模块内部使用”，近似 Java 的 private 方法约定。
    """
    if message.role in {"system", "user"}:
        return {"role": message.role, "content": message.content}
    if message.role == "tool":
        return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id}
    result: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    return result


def _normalize_response(response: Any) -> ModelReply:
    """校验外部响应，并转换成核心层认识的 ModelReply。

    SDK 返回的数据属于不可信边界，就像 Controller 收到的外部请求一样，
    不能因为有类型提示就跳过运行时校验。
    """
    try:
        if not isinstance(response.choices, list) or len(response.choices) != 1:
            raise OpenAIResponseError("Chat Completions 响应必须恰好包含一个候选结果")
        choice = response.choices[0]  # 本章只接受一个候选回答，等价于 Java 的 list.get(0)。
        reason = choice.finish_reason
        if reason not in {"stop", "length", "tool_calls", "content_filter", "function_call"}:
            raise OpenAIResponseError(f"不支持的 finish_reason: {reason}")
        if reason == "function_call":
            raise OpenAIResponseError("不支持旧版 function_call 结束原因")
        message = choice.message
        if message.role != "assistant":
            raise OpenAIResponseError("Chat Completions 消息的 role 必须是 assistant")
        content = message.content if isinstance(message.content, str) else None
        if content is None and isinstance(getattr(message, "refusal", None), str):
            content = message.refusal
        # 这是生成器表达式：把供应商的每个调用映射为内部 ToolCall，类似 Java stream().map(...).toList()。
        calls = tuple(
            tool_call(call.id, call.function.name, call.function.arguments)
            for call in (message.tool_calls or [])
        )
        usage = None
        if response.usage is not None:
            usage = TokenUsage(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens,
            )
        return ModelReply(assistant_message(content, calls), reason, usage)
    except OpenAIResponseError:
        raise
    except Exception as error:
        raise OpenAIResponseError(f"Chat Completions 响应格式不正确: {error}") from error
