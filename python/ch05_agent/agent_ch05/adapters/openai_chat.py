"""OpenAI Chat Completions 适配器。

DeepSeek 等兼容 OpenAI 协议的服务也通过这里接入。外部 SDK 返回值先在本层
校验，再转换成核心层的 ModelReply，避免脏数据进入 Agent Loop。

Java 对照：这是适配器层，把外部 OpenAI SDK 的类型转换成核心层定义的契约。
类似 Java 中从第三方 Client 包装成项目内部的 ModelClient 接口实现。

这是什么：OpenAI API 的适配器实现
为什么需要：核心循环不依赖具体 SDK，所有供应商差异在此层吸收
"""

from typing import Any

from openai import OpenAI  # 第三方 SDK，核心层不知道它的存在

from ..config import OpenAISettings
from ..core.messages import assistant_message, tool_call, validate_tool_pairing
from ..core.model import ModelClient, ModelReply, ModelRequest, TokenUsage


class OpenAIResponseError(Exception):
    """供应商响应不符合 Chat Completions 契约。

    这是什么：模型 API 返回格式错误的专用异常
    Java 类比：类似 InvalidProviderResponseException，区分网络错误和响应格式错误
    为什么需要：HTTP 请求可能成功但返回字段缺失或类型错误，需要专门异常识别

    Java 对照：类似 `InvalidProviderResponseException`，表示 HTTP 请求可能成功了，
    但响应内容的字段、角色或结束原因不符合本项目要求。
    """


class OpenAIChatModel(ModelClient):
    """ModelClient 的真实 OpenAI 兼容实现。

    这是什么：真实模型客户端，实现核心层定义的 ModelClient 接口
    Java 类比：class OpenAIChatModel implements ModelClient { ... }
    为什么需要：把 OpenAI SDK 的调用方式适配成核心层的统一接口

    DeepSeek 实现了相同的 Chat Completions 协议，所以只需更换 base_url、key 和模型名。
    """

    def __init__(self, settings: OpenAISettings, client: Any | None = None) -> None:
        """初始化 OpenAI SDK 客户端。

        这是什么：构造适配器，准备调用外部 API
        Java 类比：public OpenAIChatModel(OpenAISettings settings, Client client)
        为什么需要：封装 SDK 初始化，支持测试时注入 Fake Client

        参数：
            settings: 包含 API 地址、密钥和模型名的配置对象
            client: 可选的 SDK 客户端，测试时传入 Mock 对象
        """
        # client 可选是为了测试：生产环境创建真实 SDK，测试环境传入 FakeClient
        self._client = client or OpenAI(
            api_key=settings.api_key,  # 供应商密钥，用于身份验证
            base_url=settings.base_url,  # API 根地址，DeepSeek 和 OpenAI 不同
            max_retries=0  # 不自动重试，失败直接抛异常让上层决定
        )
        self._model = settings.model  # 没有单次覆盖时默认使用的模型名称

    def complete(self, request: ModelRequest) -> ModelReply:
        """把内部请求转换成 SDK 请求，再把 SDK 响应转换回内部对象。

        这是什么：ModelClient 接口的实现方法，调用真实 API
        Java 类比：@Override public ModelReply complete(ModelRequest request)
        为什么需要：实现核心层定义的契约，在此转换所有格式差异
        """

        # 先在本地检查历史，避免用一份已损坏的消息浪费网络请求和 token
        validate_tool_pairing(list(request.messages))

        # 参数边界校验：max_tokens 必须是正整数，不能是小数或负数
        if request.max_tokens is not None and (request.max_tokens <= 0 or int(request.max_tokens) != request.max_tokens):
            raise ValueError("max_tokens 必须是正整数")

        # payload 就是最终发给 DeepSeek/OpenAI 的 JSON 请求体
        payload: dict[str, Any] = {
            "model": request.model or self._model,  # 优先使用请求中的模型，否则用默认模型
            "messages": [_to_openai_message(message) for message in request.messages],  # 转换消息格式
        }

        # 有工具时添加 tools 字段，模型才能选择调用工具
        if request.tools:
            payload["tools"] = [tool.as_openai() for tool in request.tools]

        # 设置本轮输出上限，防止单次调用消耗过多 token
        if request.max_tokens is not None:
            payload["max_completion_tokens"] = request.max_tokens

        # **payload 类似把 Java Map 中的键值展开成方法参数
        response = self._client.chat.completions.create(**payload)

        # 校验并转换响应为核心层认识的类型
        return _normalize_response(response)


def _to_openai_message(message: Any) -> dict[str, Any]:
    """把内部 dataclass 消息转换成供应商要求的字典格式。

    这是什么：消息格式转换的私有辅助函数
    Java 类比：private static Map<String, Object> toOpenAIMessage(ChatMessage message)
    为什么需要：核心层用 dataclass，OpenAI SDK 要求 dict，需要格式转换

    Java 对照：类似把内部 DTO 映射成第三方 SDK Request DTO。
    函数名前面的单下划线表示"仅供本模块内部使用"，近似 Java 的 private 方法约定。
    """
    # system 和 user 消息格式相同：只有 role 和 content 两个字段
    if message.role in {"system", "user"}:
        return {"role": message.role, "content": message.content}

    # tool 消息需要额外的 tool_call_id 字段，用于和前面的 assistant 调用配对
    if message.role == "tool":
        return {"role": "tool", "content": message.content, "tool_call_id": message.tool_call_id}

    # assistant 消息可能包含普通文本或工具调用（或两者都有）
    result: dict[str, Any] = {"role": "assistant", "content": message.content}

    # 有工具调用时，转换成 OpenAI 要求的嵌套格式
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,  # 唯一调用 ID，工具结果需要引用它
                "type": "function",  # OpenAI 固定要求的 type 字段
                "function": {"name": call.name, "arguments": call.arguments}  # 工具名和 JSON 参数
            }
            for call in message.tool_calls
        ]
    return result


def _normalize_response(response: Any) -> ModelReply:
    """校验外部响应，并转换成核心层认识的 ModelReply。

    这是什么：响应校验和格式转换的私有函数
    Java 类比：private static ModelReply normalizeResponse(CompletionResponse response)
    为什么需要：SDK 返回值属于不可信边界，必须严格校验后再传给核心循环

    SDK 返回的数据属于不可信边界，就像 Controller 收到的外部请求一样，
    不能因为有类型提示就跳过运行时校验。
    """
    try:
        # 本项目只处理单候选响应，不支持 n > 1 的多候选生成
        if not isinstance(response.choices, list) or len(response.choices) != 1:
            raise OpenAIResponseError("Chat Completions 响应必须恰好包含一个候选结果")

        choice = response.choices[0]  # 本章只接受一个候选回答，等价于 Java 的 list.get(0)
        reason = choice.finish_reason

        # 只支持这五种结束原因，其他值视为供应商协议变更
        if reason not in {"stop", "length", "tool_calls", "content_filter", "function_call"}:
            raise OpenAIResponseError(f"不支持的 finish_reason: {reason}")

        # function_call 是旧版 API，本项目只支持新版 tool_calls
        if reason == "function_call":
            raise OpenAIResponseError("不支持旧版 function_call 结束原因")

        message = choice.message

        # 模型返回的消息角色必须是 assistant，不能是 user 或 system
        if message.role != "assistant":
            raise OpenAIResponseError("Chat Completions 消息的 role 必须是 assistant")

        # content 可能是 None（只有工具调用时），只接受字符串类型的 content
        content = message.content if isinstance(message.content, str) else None

        # 某些模型拒绝回答时会填充 refusal 字段而不是 content
        if content is None and isinstance(getattr(message, "refusal", None), str):
            content = message.refusal

        # 这是生成器表达式：把供应商的每个调用映射为内部 ToolCall，类似 Java stream().map(...).toList()
        calls = tuple(
            tool_call(call.id, call.function.name, call.function.arguments)
            for call in (message.tool_calls or [])
        )

        # usage 字段可选，某些供应商或测试环境不返回
        usage = None
        if response.usage is not None:
            usage = TokenUsage(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                response.usage.total_tokens
            )

        # 转换成核心层认识的统一格式
        return ModelReply(assistant_message(content, calls), reason, usage)

    except OpenAIResponseError:
        # 已经是业务异常，直接向上传播
        raise
    except Exception as error:
        # 其他异常（属性缺失、类型错误等）统一包装成 OpenAIResponseError
        raise OpenAIResponseError(f"Chat Completions 响应格式不正确: {error}") from error
