package learn.agent.llm.artifact;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 历史压缩工具：snip 和 micro 压缩。
 */
public final class CompactionUtils {

    /** micro 压缩的占位符文本 */
    public static final String COMPACTED_TOOL_RESULT = "[Earlier tool result compacted. Re-run if needed.]";

    private CompactionUtils() {
        // 工具类
    }

    /**
     * snip 压缩：保留头尾消息组，中间插入省略标记。
     *
     * <p>规则：</p>
     * <ul>
     *   <li>消息组总数 <= maxGroups 时不压缩</li>
     *   <li>保留头部 keepHeadGroups 组</li>
     *   <li>保留尾部 (maxGroups - keepHeadGroups - 1) 组</li>
     *   <li>中间插入省略标记</li>
     * </ul>
     *
     * <p>为什么以组为单位：绝不能拆散 assistant 工具调用与 tool 结果的配对。</p>
     *
     * @param history 消息历史
     * @param maxGroups 允许的最大组数（至少 3：head + marker + tail）
     * @param keepHeadGroups 保留的头部组数（至少 1，且必须 <= maxGroups - 2）
     * @return 压缩后的历史
     */
    public static List<ChatMessage> snipCompact(List<ChatMessage> history, int maxGroups, int keepHeadGroups) {
        if (maxGroups < 3) {
            throw new IllegalArgumentException("maxGroups must be at least 3 (head + marker + tail)");
        }
        if (keepHeadGroups < 1 || keepHeadGroups > maxGroups - 2) {
            throw new IllegalArgumentException("keepHeadGroups must be in [1, maxGroups-2]");
        }

        List<MessageGroup> groups = MessageGroup.fromHistory(history);

        // 不超过限制时不压缩
        if (groups.size() <= maxGroups) {
            return history;
        }

        int keepTailGroups = maxGroups - keepHeadGroups - 1;
        int omitted = groups.size() - keepHeadGroups - keepTailGroups;

        List<MessageGroup> result = new ArrayList<>();
        result.addAll(groups.subList(0, keepHeadGroups));

        // 省略标记单独成组
        ChatMessage marker = ChatMessage.system("[Compacted: " + omitted + " message groups omitted]");
        result.add(MessageGroup.create(Collections.singletonList(marker), false));

        result.addAll(groups.subList(groups.size() - keepTailGroups, groups.size()));

        List<ChatMessage> compacted = MessageGroup.flattenGroups(result);
        MessageUtils.validateToolPairing(compacted);
        return compacted;
    }

    /**
     * micro 压缩：旧工具结果正文替换成占位符。
     *
     * <p>规则：</p>
     * <ul>
     *   <li>保留最近 keepRecentToolGroups 组工具交换</li>
     *   <li>其余工具组的 tool 消息正文替换成占位符</li>
     *   <li>保留 assistant 调用消息和 tool_call_id</li>
     * </ul>
     *
     * <p>为什么保留 tool_call_id：这是配对的唯一键，丢失会导致协议违规。</p>
     *
     * @param history 消息历史
     * @param keepRecentToolGroups 保留的最近工具组数
     * @return 压缩后的历史
     */
    public static List<ChatMessage> microCompact(List<ChatMessage> history, int keepRecentToolGroups) {
        if (keepRecentToolGroups < 0) {
            throw new IllegalArgumentException("keepRecentToolGroups must not be negative");
        }

        List<MessageGroup> groups = MessageGroup.fromHistory(history);

        // 找出所有工具交换组
        List<Integer> toolGroupIndices = new ArrayList<>();
        for (int i = 0; i < groups.size(); i++) {
            if (groups.get(i).isToolExchange()) {
                toolGroupIndices.add(i);
            }
        }

        // 计算需要压缩的工具组
        int compactCount = Math.max(0, toolGroupIndices.size() - keepRecentToolGroups);
        if (compactCount == 0) {
            return history;
        }

        List<Integer> compactIndices = new ArrayList<>(toolGroupIndices.subList(0, compactCount));

        // 压缩指定的工具组
        List<MessageGroup> updated = new ArrayList<>();
        for (int i = 0; i < groups.size(); i++) {
            MessageGroup group = groups.get(i);

            if (!compactIndices.contains(i)) {
                updated.add(group);
                continue;
            }

            // 压缩工具组：保留 assistant，替换 tool 消息内容
            List<ChatMessage> messages = group.getMessages();
            ChatMessage.AssistantMessage assistant = (ChatMessage.AssistantMessage) messages.get(0);

            List<ChatMessage> compacted = new ArrayList<>();
            compacted.add(assistant);

            for (int j = 1; j < messages.size(); j++) {
                ChatMessage.ToolMessage toolMsg = (ChatMessage.ToolMessage) messages.get(j);
                compacted.add(ChatMessage.tool(COMPACTED_TOOL_RESULT, toolMsg.getToolCallId()));
            }

            updated.add(MessageGroup.create(compacted, true));
        }

        List<ChatMessage> result = MessageGroup.flattenGroups(updated);
        MessageUtils.validateToolPairing(result);
        return result;
    }
}
