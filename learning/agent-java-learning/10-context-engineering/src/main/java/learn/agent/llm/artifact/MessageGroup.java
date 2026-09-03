package learn.agent.llm.artifact;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 消息组：压缩的最小单位。
 *
 * <p>规则：</p>
 * <ul>
 *   <li>普通消息（system/user/assistant 无工具调用）单独成组</li>
 *   <li>assistant 工具调用 + 其全部 tool 结果是一组（不可拆分）</li>
 * </ul>
 *
 * <p>为什么以组为单位：绝不能拆散 assistant 工具调用与 tool 结果的配对。
 * OpenAI 协议要求它们必须连续出现。</p>
 */
public final class MessageGroup {
    private final List<ChatMessage> messages;
    private final boolean isToolExchange;

    private MessageGroup(List<ChatMessage> messages, boolean isToolExchange) {
        this.messages = Collections.unmodifiableList(new ArrayList<>(messages));
        this.isToolExchange = isToolExchange;
    }

    /**
     * 组内的消息列表，不可变。
     */
    public List<ChatMessage> getMessages() {
        return messages;
    }

    /**
     * 是否为工具交换组（assistant + tools）。
     */
    public boolean isToolExchange() {
        return isToolExchange;
    }

    /**
     * 将消息历史切分为消息组。
     * 每个组要么是单条普通消息，要么是完整的工具交换。
     */
    public static List<MessageGroup> fromHistory(List<ChatMessage> history) {
        if (history == null) {
            throw new IllegalArgumentException("history must not be null");
        }

        // 先校验配对关系
        MessageUtils.validateToolPairing(history);

        List<MessageGroup> groups = new ArrayList<>();
        int index = 0;

        while (index < history.size()) {
            ChatMessage message = history.get(index);

            // assistant 工具调用开始一个工具交换组
            if (message.getRole() == Role.ASSISTANT) {
                ChatMessage.AssistantMessage assistant = (ChatMessage.AssistantMessage) message;
                if (!assistant.getToolCalls().isEmpty()) {
                    int end = index + 1 + assistant.getToolCalls().size();
                    groups.add(new MessageGroup(history.subList(index, end), true));
                    index = end;
                    continue;
                }
            }

            // 其他消息单独成组
            groups.add(new MessageGroup(Collections.singletonList(message), false));
            index++;
        }

        return Collections.unmodifiableList(groups);
    }

    /**
     * 将消息组列表展平为消息列表。
     */
    public static List<ChatMessage> flattenGroups(List<MessageGroup> groups) {
        List<ChatMessage> result = new ArrayList<>();
        for (MessageGroup group : groups) {
            result.addAll(group.messages);
        }
        return Collections.unmodifiableList(result);
    }

    /**
     * 创建消息组（包级可见，供压缩工具使用）。
     * 调用方负责确保消息列表符合组规则。
     */
    static MessageGroup create(List<ChatMessage> messages, boolean isToolExchange) {
        return new MessageGroup(messages, isToolExchange);
    }
}
