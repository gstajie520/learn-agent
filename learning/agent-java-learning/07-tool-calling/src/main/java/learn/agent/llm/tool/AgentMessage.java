package learn.agent.llm.tool;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRole;

/**
 * 工具调用循环里的一条消息。
 *
 * <p>第 1 课的 {@link ChatMessage} 只有 {@code role} 和 {@code content} 两个字段，
 * 装不下工具调用需要的东西。本课不修改第 1 课（保持「第 1 课一行未改」），
 * 而是定义自己的消息载体，把工具调用需要的三种消息补全：</p>
 * <ul>
 *   <li><b>assistant 带 tool_calls</b>：模型说「我要调 create_device，参数是…」。</li>
 *   <li><b>tool 结果</b>：程序执行完，把结果回传给模型。</li>
 *   <li><b>普通文本</b>：系统规则、用户输入、模型最终答复。</li>
 * </ul>
 *
 * <p>三种消息用三个静态工厂区分，而不是一个万能构造器加一堆可空字段。
 * 这样「哪种消息有哪些字段」由类型本身保证，调用方不可能造出一条
 * 既没有正文又没有工具调用的四不像。</p>
 */
public class AgentMessage {

    /** 消息角色。 */
    private final ChatRole role;

    /** 文本正文；工具调用消息里为 null。 */
    private final String content;

    /** 模型发起的工具调用；只有 assistant 消息可能非 null。 */
    private final ToolCall toolCall;

    /** 工具结果回传时，必须和某次 toolCall 的 id 配对。 */
    private final String toolCallId;

    private AgentMessage(ChatRole role, String content, ToolCall toolCall, String toolCallId) {
        this.role = role;
        this.content = content;
        this.toolCall = toolCall;
        this.toolCallId = toolCallId;
    }

    /** 系统规则消息。 */
    public static AgentMessage system(String content) {
        return new AgentMessage(ChatRole.SYSTEM, requireText(content), null, null);
    }

    /** 用户消息。 */
    public static AgentMessage user(String content) {
        return new AgentMessage(ChatRole.USER, requireText(content), null, null);
    }

    /** 模型普通答复（没有工具调用）。 */
    public static AgentMessage assistant(String content) {
        return new AgentMessage(ChatRole.ASSISTANT, requireText(content), null, null);
    }

    /**
     * 模型发起工具调用的消息。
     *
     * <p>注意：协议里一条 assistant 消息可以带<b>多个</b> tool_calls。
     * 本课为了把「配对」这件事讲清楚，先限制为一条消息一个调用。
     * 多调用并行是阶段 6 之后的扩展，不是本课目标。</p>
     */
    public static AgentMessage assistantToolCall(ToolCall call) {
        if (call == null) {
            throw new IllegalArgumentException("toolCall 不能为 null");
        }
        return new AgentMessage(ChatRole.ASSISTANT, null, call, null);
    }

    /**
     * 工具结果回传消息。
     *
     * <p><b>toolCallId 必须原样带回</b>：模型靠它把结果和当初的调用对上。
     * 自己造一个 id 或写错一个字符，模型就会把结果张冠李戴。</p>
     */
    public static AgentMessage toolResult(String toolCallId, String resultContent) {
        if (toolCallId == null || toolCallId.trim().isEmpty()) {
            throw new IllegalArgumentException("toolCallId 不能为空，否则结果无法配对");
        }
        if (resultContent == null) {
            throw new IllegalArgumentException("resultContent 不能为 null");
        }
        return new AgentMessage(ChatRole.TOOL, resultContent, null, toolCallId.trim());
    }

    private static String requireText(String content) {
        if (content == null) {
            throw new IllegalArgumentException("文本消息的 content 不能为 null");
        }
        return content;
    }

    public ChatRole getRole() {
        return role;
    }

    /** @return 文本正文；工具调用消息里为 null */
    public String getContent() {
        return content;
    }

    /** @return 工具调用；只有 assistant 工具调用消息非 null */
    public ToolCall getToolCall() {
        return toolCall;
    }

    /** @return 工具结果配对 id；只有 tool 消息非 null */
    public String getToolCallId() {
        return toolCallId;
    }

    /** @return 是否携带工具调用 */
    public boolean hasToolCall() {
        return toolCall != null;
    }

    /** @return 是否是工具结果回传消息 */
    public boolean isToolResult() {
        return role == ChatRole.TOOL;
    }

    /**
     * 转成第 1 课的 {@link ChatMessage}，用于塞进 {@code ChatRequest} 的消息列表。
     *
     * <p>第 1 课的 {@link ChatMessage} 只有 role 和 content，装不下 toolCallId。
     * 本课不修改第 1 课，所以这里做一次「降级」：工具调用消息把调用内容编码进
     * content（由 {@link ToolCallCodec} 负责），工具结果消息把 id 拼进 content 前缀。
     * 真实实现里这一步应该由 codec 直接写进请求体的 {@code tool_calls} 字段，
     * 而不是塞进 content —— 本课为了聚焦循环，用这个约定桥接。</p>
     */
    public ChatMessage toChatMessage() {
        if (hasToolCall()) {
            return ChatMessage.assistant(ToolCallCodec.encode(toolCall));
        }
        if (isToolResult()) {
            // 第 1 课的 ChatMessage 没有 tool 工厂，也没有 toolCallId 字段。
            // 用 codec 把「id + 结果」编码进 content，另一端再还原配对关系。
            return ChatMessage.assistant(ToolCallCodec.encodeToolResult(toolCallId, content));
        }
        return new ChatMessage(role, content);
    }

    @Override
    public String toString() {
        if (hasToolCall()) {
            return "[assistant] tool_call " + toolCall;
        }
        if (isToolResult()) {
            return "[tool] id=" + toolCallId + " -> " + content;
        }
        return "[" + role.getWireValue() + "] " + content;
    }
}