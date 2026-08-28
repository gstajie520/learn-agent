package learn.agent.llm.tool;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * 工具调用在「第 1 课消息模型」和「本课消息模型」之间的桥接编解码器。
 *
 * <p>为什么需要这个类：第 1 课的 {@link learn.agent.llm.client.ChatMessage}
 * 只有 role 和 content，没有 toolCallId 字段；{@link learn.agent.llm.client.ChatResponse}
 * 也没有 toolCalls 字段。真实协议里，工具调用是请求体里独立的
 * {@code tool_calls} 数组、响应里独立的 {@code tool_calls} 数组，根本不经过 content。</p>
 *
 * <p>本课为了不改第 1 课（保持「第 1 课一行未改」这个教学性质），
 * 用一个<b>约定</b>来桥接：把工具调用和工具结果编码成 content 里的一段 JSON，
 * 在循环的两端用这个类编码和解码。这样 {@link ToolCallingService} 的循环逻辑
 * 可以完整跑通，而第 1 课的类型保持原样。</p>
 *
 * <p><b>必须说清楚：这是教学桥接，不是生产做法。</b>生产里工具调用走的是
 * 协议原生的 {@code tool_calls} 字段，不会塞进 content。本课用这个桥接，
 * 是为了让你在「不破坏前几课」的前提下，把循环的每一步都看清楚。
 * 阶段 6 之后引入真正的请求/响应扩展时，这个类会被删掉。</p>
 *
 * <p>编码格式（content 里的一段 JSON）：</p>
 * <pre>{@code
 * 工具调用：  {"__tool_call__": {"id": "...", "name": "...", "arguments": "..."}}
 * 工具结果：  {"__tool_result__": {"id": "...", "content": "..."}}
 * }</pre>
 *
 * <p>用 {@code __tool_call__} / {@code __tool_result__} 这种带下划线前缀的键，
 * 是为了和模型正常输出的 JSON 区分开，避免误判。</p>
 */
public final class ToolCallCodec {

    /** 工具调用消息的标记键。 */
    private static final String TOOL_CALL_KEY = "__tool_call__";

    /** 工具结果消息的标记键。 */
    private static final String TOOL_RESULT_KEY = "__tool_result__";

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private ToolCallCodec() {
        // 工具类，禁止实例化。
    }

    /**
     * 把一次工具调用编码成 content 文本。
     *
     * @param call 模型发起的工具调用
     * @return 编码后的 content 文本
     */
    public static String encode(ToolCall call) {
        ObjectNode root = MAPPER.createObjectNode();
        ObjectNode inner = root.putObject(TOOL_CALL_KEY);
        inner.put("id", call.getId());
        inner.put("name", call.getName());
        inner.put("arguments", call.getRawArguments());
        return root.toString();
    }

    /**
     * 把工具结果编码成 content 文本。
     *
     * @param toolCallId 配对的调用 id
     * @param content    结果文本
     * @return 编码后的 content 文本
     */
    public static String encodeToolResult(String toolCallId, String content) {
        ObjectNode root = MAPPER.createObjectNode();
        ObjectNode inner = root.putObject(TOOL_RESULT_KEY);
        inner.put("id", toolCallId);
        inner.put("content", content);
        return root.toString();
    }

    /**
     * 从 content 文本解码出工具调用。
     *
     * @param content 模型响应的 content
     * @return 解码出的工具调用；如果 content 不是工具调用编码，返回 null
     */
    public static ToolCall decode(String content) {
        if (content == null || content.trim().isEmpty()) {
            return null;
        }
        try {
            JsonNode root = MAPPER.readTree(content);
            JsonNode inner = root.get(TOOL_CALL_KEY);
            if (inner == null || !inner.isObject()) {
                return null;
            }
            String id = inner.path("id").asText(null);
            String name = inner.path("name").asText(null);
            String arguments = inner.path("arguments").asText(null);
            if (id == null || name == null) {
                return null;
            }
            return new ToolCall(id, name, arguments);
        } catch (Exception e) {
            // content 不是合法 JSON，或不是工具调用编码 —— 都不是工具调用。
            return null;
        }
    }

    /**
     * 判断一段 content 是否是工具结果编码。
     *
     * <p>循环里用它区分「模型正常答复」和「工具结果回传」。
     * 本课当前实现里，工具结果只在程序内部生成，模型不会输出这个格式，
     * 所以这个方法主要给测试和调试用。</p>
     */
    public static boolean isToolResult(String content) {
        if (content == null || content.trim().isEmpty()) {
            return false;
        }
        try {
            JsonNode root = MAPPER.readTree(content);
            return root.has(TOOL_RESULT_KEY);
        } catch (Exception e) {
            return false;
        }
    }
}