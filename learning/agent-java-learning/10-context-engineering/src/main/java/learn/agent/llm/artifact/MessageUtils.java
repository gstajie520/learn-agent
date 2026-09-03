package learn.agent.llm.artifact;

import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 消息历史工具：校验、压缩和序列化。
 */
public final class MessageUtils {

    private MessageUtils() {
        // 工具类，禁止实例化
    }

    /**
     * 校验 assistant 工具调用与 tool 消息的配对关系。
     *
     * <p>OpenAI 协议要求：assistant 工具调用后必须紧随对应数量的 tool 消息。
     * 这个函数检测三种非法状态：</p>
     *
     * <ol>
     *   <li><b>孤儿 tool</b>：pending 为空时遇到 tool 消息</li>
     *   <li><b>缺失 tool</b>：pending 非空但下一条不是 tool</li>
     *   <li><b>ID 不匹配</b>：tool 消息的 ID 不在 pending 里</li>
     * </ol>
     *
     * <p>用途：任何压缩操作（snip、micro、summary）之后都必须跑一遍这个校验，
     * 确保没有压断配对关系。</p>
     *
     * @param messages 消息历史
     * @throws MessageContractException 如果配对关系违规
     */
    public static void validateToolPairing(List<ChatMessage> messages) {
        if (messages == null) {
            throw new IllegalArgumentException("messages must not be null");
        }

        Set<String> pending = new HashSet<>();

        // pending 集合表达"当前 assistant 工具调用块尚未回填完成"：
        // 下一批消息必须是 tool，且只能消费 pending 中的 ID。
        for (ChatMessage message : messages) {
            if (!pending.isEmpty()) {
                // pending 非空时，下一条必须是 tool
                if (message.getRole() != Role.TOOL) {
                    String sorted = pending.stream().sorted().collect(Collectors.joining(", "));
                    throw new MessageContractException(
                        "missing tool results for ids: [" + sorted + "]"
                    );
                }
                // tool 消息必须消费 pending 中的某个 ID
                ChatMessage.ToolMessage toolMsg = (ChatMessage.ToolMessage) message;
                String toolCallId = toolMsg.getToolCallId();
                if (!pending.remove(toolCallId)) {
                    throw new MessageContractException(
                        "unexpected tool result id: " + toolCallId
                    );
                }
                continue;
            }

            // pending 为空时，tool 消息是孤儿
            if (message.getRole() == Role.TOOL) {
                ChatMessage.ToolMessage toolMsg = (ChatMessage.ToolMessage) message;
                throw new MessageContractException(
                    "orphan tool result id: " + toolMsg.getToolCallId()
                );
            }

            // assistant 消息的工具调用进入 pending
            if (message.getRole() == Role.ASSISTANT) {
                ChatMessage.AssistantMessage assistantMsg = (ChatMessage.AssistantMessage) message;
                for (ToolCall call : assistantMsg.getToolCalls()) {
                    pending.add(call.getId());
                }
            }
        }

        // 循环结束时 pending 必须为空
        if (!pending.isEmpty()) {
            String sorted = pending.stream().sorted().collect(Collectors.joining(", "));
            throw new MessageContractException(
                "missing tool results for ids: [" + sorted + "]"
            );
        }
    }

    /**
     * 计算消息历史的 UTF-8 字节数。
     * 用于判断是否超过预算阈值。
     */
    public static int historyUtf8Bytes(List<ChatMessage> messages) {
        int total = 0;
        for (ChatMessage message : messages) {
            if (message instanceof ChatMessage.SystemMessage) {
                total += ((ChatMessage.SystemMessage) message).getContent().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
            } else if (message instanceof ChatMessage.UserMessage) {
                total += ((ChatMessage.UserMessage) message).getContent().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
            } else if (message instanceof ChatMessage.AssistantMessage) {
                ChatMessage.AssistantMessage am = (ChatMessage.AssistantMessage) message;
                if (am.getContent() != null) {
                    total += am.getContent().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
                }
                for (ToolCall call : am.getToolCalls()) {
                    total += call.getName().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
                    total += call.getArguments().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
                }
            } else if (message instanceof ChatMessage.ToolMessage) {
                total += ((ChatMessage.ToolMessage) message).getContent().getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
            }
        }
        return total;
    }
}
