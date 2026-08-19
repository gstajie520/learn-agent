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
    """供应商响应不符合 Chat Completions 契约。"""


class OpenAIChatModel(ModelClient):
    """ModelClient 的真实 OpenAI 兼容实现。

    DeepSeek 实现了相同的 Chat Completions 协议，所以只需更换 base_url、key 和模型名。
    """

    def __init__(self, settings: OpenAISettings, client: Any | None = None) -> None:
        # client 可选是为了测试：生产环境创建真实 SDK，测试环境传入 FakeClient。
        self._client = client or OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0)
        self._model = settings.model

    def complete(self, request: ModelRequest) -> ModelReply:
        """把内部请求转换成 SDK 请求，再把 SDK 响应转换回内部对象。"""

        # 先在本地检查历史，避免用一份已损坏的消息浪费网络请求和 token。
        validate_tool_pairing(list(request.messages))
        if request.max_tokens is not None and (request.max_tokens <= 0 or int(request.max_tokens) != request.max_tokens):
            raise ValueError("max_tokens must be a positive integer")
        # payload 就是最终发给 DeepSeek/OpenAI 的 JSON 请求体。
        payload: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": [_to_openai_message(message) for message in request.messages],
        }
        if request.tools:
            payload["tools"] = [tool.as_openai() for tool in request.tools]
        if request.max_tokens is not None:
            payload["max_completion_tokens"] = request.max_tokens
        # **payload 类似把 Java Map 中的键值展开成方法参数。
        response = self._client.chat.completions.create(**payload)
        return _normalize_response(response)


def _to_openai_message(message: Any) -> dict[str, Any]:
    """把内部 dataclass 消息转换成供应商要求的字典格式。"""
    if message.role in {"system", "user"}:
        return {"role": message.role, "content": message.content}
    if message.role == "tool":
        return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id}
    result: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        result["tool_calls"] = [{"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}} for call in message.tool_calls]
    return result


def _normalize_response(response: Any) -> ModelReply:
    """校验外部响应，并转换成核心层认识的 ModelReply。

    SDK 返回的数据属于不可信边界，就像 Controller 收到的外部请求一样，
    不能因为有类型提示就跳过运行时校验。
    """
    try:
        if not isinstance(response.choices, list) or len(response.choices) != 1:
            raise OpenAIResponseError("Chat completion must return exactly one choice")
        choice = response.choices[0]
        reason = choice.finish_reason
        if reason not in {"stop", "length", "tool_calls", "content_filter", "function_call"}:
            raise OpenAIResponseError(f"Unsupported finish_reason: {reason}")
        if reason == "function_call":
            raise OpenAIResponseError("Legacy function_call finish reason is unsupported")
        message = choice.message
        if message.role != "assistant":
            raise OpenAIResponseError("Chat completion message role must be assistant")
        content = message.content if isinstance(message.content, str) else None
        if content is None and isinstance(getattr(message, "refusal", None), str):
            content = message.refusal
        calls = tuple(tool_call(call.id, call.function.name, call.function.arguments) for call in (message.tool_calls or []))
        usage = None
        if response.usage is not None:
            usage = TokenUsage(response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total_tokens)
        return ModelReply(assistant_message(content, calls), reason, usage)
    except OpenAIResponseError:
        raise
    except Exception as error:
        raise OpenAIResponseError(f"Malformed Chat completion response: {error}") from error
