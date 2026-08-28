package learn.agent.llm.client;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;

/**
 * 内部对象与 Chat Completions JSON 之间的转换。
 *
 * <p>为什么把 JSON 处理单独拆成一个类，而不是塞进 HTTP 客户端：
 * <b>这一层能完全离线测试</b>。给它一段 JSON 字符串，它就该产出正确的
 * {@link ChatResponse} 或抛出正确的异常，不需要网络也不需要密钥。
 * 真实环境里最难复现的「服务端返回了畸形 JSON」，在这里一行代码就能构造。</p>
 *
 * <p>核心原则（和 Python 版一致）：<b>服务端响应属于不可信边界</b>。
 * 它和 Controller 收到的外部请求性质一样，不能因为文档写了某个字段
 * 就假定它一定存在。少一个 {@code choices} 字段就直接空指针，
 * 是这类代码最常见的线上故障。</p>
 */
public class ChatJsonCodec {

    /** Jackson 的 ObjectMapper 是线程安全的，可以复用，不必每次 new。 */
    private final ObjectMapper mapper = new ObjectMapper();

    /**
     * 把内部请求对象转成要发送的 JSON。
     *
     * <p>发出去的字段就是这几个。看清这一点很重要 ——
     * 所谓"调用大模型"，本质上就是发一个这样的 JSON。</p>
     */
    public String toRequestJson(ChatRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("request 不能为空");
        }
        ObjectNode root = mapper.createObjectNode();
        root.put("model", request.getModel());
        root.put("temperature", request.getTemperature());
        // 字段名是 max_tokens，不是 Java 里的驼峰 maxOutputTokens。
        root.put("max_tokens", request.getMaxOutputTokens());

        ArrayNode messages = root.putArray("messages");
        for (ChatMessage message : request.getMessages()) {
            ObjectNode node = messages.addObject();
            // 用 wireValue 而不是 enum.name()：协议里是小写的 "system"，
            // 直接用 name() 会发出 "SYSTEM"，服务端不认。
            node.put("role", message.getRole().getWireValue());
            node.put("content", message.getContent());
        }
        try {
            return mapper.writeValueAsString(root);
        } catch (IOException e) {
            throw new ModelException(
                    ModelException.ErrorType.INVALID_REQUEST,
                    "请求序列化失败：" + e.getMessage(),
                    null,
                    e);
        }
    }

    /**
     * 把成功响应的 JSON 解析成内部对象。
     *
     * <p>每一步都在防御「字段不存在」和「类型不对」，因为这里是不可信边界。</p>
     *
     * @param json          服务端返回的响应体
     * @param headerRequestId 从 HTTP 响应头拿到的请求 id，可能为 null
     * @throws ModelException 响应不符合 Chat Completions 契约
     */
    public ChatResponse parseResponse(String json, String headerRequestId) {
        JsonNode root = readTree(json);

        // 响应体里的 id 优先，其次用响应头的；两者都没有时由 ChatResponse 兜底成 unknown。
        String requestId = optText(root, "id", headerRequestId);

        JsonNode choices = root.get("choices");
        if (choices == null || !choices.isArray() || choices.size() == 0) {
            throw new ModelException(
                    ModelException.ErrorType.SERVER_ERROR,
                    "响应缺少 choices 数组",
                    requestId,
                    null);
        }
        // 本课只接受一个候选结果，和 Python 版保持一致。
        JsonNode choice = choices.get(0);

        JsonNode messageNode = choice.get("message");
        if (messageNode == null || !messageNode.isObject()) {
            throw new ModelException(
                    ModelException.ErrorType.SERVER_ERROR,
                    "响应缺少 message 对象",
                    requestId,
                    null);
        }

        // content 允许是 null：模型决定调工具时就没有正文。
        // 转成空字符串而不是留 null，避免空指针一路传到业务层。
        String content = optText(messageNode, "content", "");

        FinishReason finishReason = parseFinishReason(optText(choice, "finish_reason", null));
        TokenUsage usage = parseUsage(root.get("usage"));

        return new ChatResponse(content, finishReason, usage, requestId);
    }

    /**
     * 把服务端的 finish_reason 字符串映射成本地枚举。
     *
     * <p>遇到没见过的值时返回 {@code UNKNOWN}，而不是抛异常。
     * 服务商随时可能新增结束原因，不该因此让整个调用失败；
     * 但也不能当成 {@code STOP}，否则会把异常结束误判成正常完成。</p>
     */
    private FinishReason parseFinishReason(String value) {
        if (value == null) {
            return FinishReason.UNKNOWN;
        }
        if ("stop".equals(value)) {
            return FinishReason.STOP;
        }
        if ("length".equals(value)) {
            return FinishReason.LENGTH;
        }
        if ("tool_calls".equals(value)) {
            return FinishReason.TOOL_CALLS;
        }
        if ("content_filter".equals(value)) {
            return FinishReason.CONTENT_FILTER;
        }
        return FinishReason.UNKNOWN;
    }

    /**
     * 解析 Token 用量。
     *
     * <p>部分兼容网关不返回 usage。这时记 0 而不是抛异常 ——
     * 拿不到用量是可观测性问题，不该让一次成功的业务调用失败。
     * 但要清楚：记 0 不代表没有计费。</p>
     */
    private TokenUsage parseUsage(JsonNode usageNode) {
        if (usageNode == null || !usageNode.isObject()) {
            return new TokenUsage(0, 0);
        }
        int promptTokens = optInt(usageNode, "prompt_tokens");
        int completionTokens = optInt(usageNode, "completion_tokens");
        return new TokenUsage(promptTokens, completionTokens);
    }

    /**
     * 把错误响应体解析成带分类的异常。
     *
     * <p>HTTP 状态码是主要依据，响应体里的 {@code error.code} 用于细分。
     * 最典型的是上下文超长：它同样返回 400，但和「参数写错」的处理方式完全不同 ——
     * 前者要压缩上下文后重发，后者要改代码。</p>
     *
     * @param statusCode HTTP 状态码
     * @param body       错误响应体，可能为空
     * @param requestId  请求 id，可能为 null
     */
    public ModelException toException(int statusCode, String body, String requestId) {
        String providerMessage = extractErrorMessage(body);
        String providerCode = extractErrorCode(body);

        ModelException.ErrorType type = classify(statusCode, providerCode);
        String message = "模型服务返回 HTTP " + statusCode
                + (providerMessage == null ? "" : "：" + providerMessage);
        return new ModelException(type, message, requestId, null);
    }

    /** 状态码到错误分类的映射。这张表决定了「这次失败该不该重试」。 */
    private ModelException.ErrorType classify(int statusCode, String providerCode) {
        // 上下文超长通常也是 400，但必须先压缩上下文，原样重试没用。
        if (providerCode != null && providerCode.contains("context_length_exceeded")) {
            return ModelException.ErrorType.CONTEXT_LENGTH_EXCEEDED;
        }
        if (providerCode != null && providerCode.contains("content_filter")) {
            return ModelException.ErrorType.CONTENT_FILTERED;
        }
        if (statusCode == 401 || statusCode == 403) {
            return ModelException.ErrorType.AUTHENTICATION;
        }
        if (statusCode == 408) {
            return ModelException.ErrorType.TIMEOUT;
        }
        if (statusCode == 429) {
            return ModelException.ErrorType.RATE_LIMIT;
        }
        if (statusCode >= 500) {
            // 5xx 是服务端问题，等一会儿重试通常能成功。
            return ModelException.ErrorType.SERVER_ERROR;
        }
        // 其余 4xx 都是请求本身的问题，重试无意义。
        return ModelException.ErrorType.INVALID_REQUEST;
    }

    /** 从错误响应体里取出人类可读的消息，取不到就返回 null。 */
    private String extractErrorMessage(String body) {
        if (body == null || body.trim().isEmpty()) {
            return null;
        }
        try {
            JsonNode error = mapper.readTree(body).get("error");
            if (error == null) {
                return null;
            }
            return optText(error, "message", null);
        } catch (IOException e) {
            // 错误响应体不是 JSON（例如网关返回一段 HTML）。
            // 这本身就是有用的排查线索，截断后原样带出去。
            return body.length() > 200 ? body.substring(0, 200) : body;
        }
    }

    /** 从错误响应体里取出服务商错误码，用于细分 400。 */
    private String extractErrorCode(String body) {
        if (body == null || body.trim().isEmpty()) {
            return null;
        }
        try {
            JsonNode error = mapper.readTree(body).get("error");
            if (error == null) {
                return null;
            }
            String code = optText(error, "code", null);
            if (code != null) {
                return code;
            }
            return optText(error, "type", null);
        } catch (IOException e) {
            return null;
        }
    }

    private JsonNode readTree(String json) {
        if (json == null || json.trim().isEmpty()) {
            throw new ModelException(
                    ModelException.ErrorType.SERVER_ERROR,
                    "模型服务返回空响应体",
                    null,
                    null);
        }
        try {
            return mapper.readTree(json);
        } catch (IOException e) {
            throw new ModelException(
                    ModelException.ErrorType.SERVER_ERROR,
                    "响应不是合法 JSON：" + e.getMessage(),
                    null,
                    e);
        }
    }

    /** 读取可选文本字段；字段缺失或为 JSON null 时返回默认值。 */
    private String optText(JsonNode node, String field, String defaultValue) {
        JsonNode value = node.get(field);
        if (value == null || value.isNull() || !value.isTextual()) {
            return defaultValue;
        }
        return value.asText();
    }

    /** 读取可选整数字段；字段缺失或类型不对时返回 0。 */
    private int optInt(JsonNode node, String field) {
        JsonNode value = node.get(field);
        if (value == null || value.isNull() || !value.isNumber()) {
            return 0;
        }
        int number = value.asInt();
        // 服务端理论上不会返回负数，但解析层不能假定这一点：
        // TokenUsage 会拒绝负数，在这里先归零避免整次调用失败。
        return number < 0 ? 0 : number;
    }
}
