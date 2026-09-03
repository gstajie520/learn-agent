package learn.agent.llm.artifact;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 测试 {@link CompactionUtils} 的 snip 和 micro 压缩。
 */
class CompactionUtilsTest {

    /**
     * 规则：消息组不超过 maxGroups 时，snip 不压缩。
     * <p>为什么重要：避免不必要的压缩开销。</p>
     */
    @Test
    void snipShouldNotCompactWhenUnderLimit() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("问题 1"),
            ChatMessage.assistant("回答 1"),
            ChatMessage.user("问题 2")
        );

        List<ChatMessage> result = CompactionUtils.snipCompact(history, 5, 1);

        assertEquals(3, result.size());
        assertEquals(history, result);
    }

    /**
     * 规则：超过 maxGroups 时保留头尾，中间插入省略标记。
     * <p>为什么重要：让模型既能看到任务开端，又能看到最新进展。</p>
     */
    @Test
    void snipShouldCompactMiddleGroups() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("问题 1"),      // group 0
            ChatMessage.assistant("回答 1"),  // group 1
            ChatMessage.user("问题 2"),      // group 2
            ChatMessage.assistant("回答 2"),  // group 3
            ChatMessage.user("问题 3"),      // group 4
            ChatMessage.assistant("回答 3")   // group 5
        );

        // maxGroups=4, keepHead=1 → 保留 1 组头 + marker + 2 组尾 = 4 条消息
        List<ChatMessage> result = CompactionUtils.snipCompact(history, 4, 1);

        assertEquals(4, result.size());
        assertEquals("问题 1", ((ChatMessage.UserMessage) result.get(0)).getContent());
        assertTrue(((ChatMessage.SystemMessage) result.get(1)).getContent().contains("3 message groups omitted"));
        assertEquals("问题 3", ((ChatMessage.UserMessage) result.get(2)).getContent());
        assertEquals("回答 3", ((ChatMessage.AssistantMessage) result.get(3)).getContent());
    }

    /**
     * 规则：snip 不能拆散工具交换组。
     * <p>为什么重要：assistant 工具调用与 tool 结果必须连续。</p>
     */
    @Test
    void snipShouldPreserveToolExchangeGroups() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create", "{}")
            )),
            ChatMessage.tool("已创建", "call-1"),
            ChatMessage.user("检查设备"),
            ChatMessage.assistant("设备正常")
        );

        // 5条消息→4组：user + (assistant+tool) + user + assistant
        // maxGroups=3, keepHead=1 → 保留 1 组头 + marker + 1 组尾 = 3 条消息
        List<ChatMessage> result = CompactionUtils.snipCompact(history, 3, 1);

        // 工具交换组不能拆开，压缩后为：user + marker + assistant
        assertEquals(3, result.size());
        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(result));
    }

    /**
     * 规则：maxGroups 必须至少为 3（head + marker + tail）。
     * <p>为什么重要：少于 3 组无法插入省略标记。</p>
     */
    @Test
    void snipShouldRejectInvalidMaxGroups() {
        List<ChatMessage> history = Collections.singletonList(ChatMessage.user("测试"));

        assertThrows(IllegalArgumentException.class,
            () -> CompactionUtils.snipCompact(history, 2, 1));
    }

    /**
     * 规则：没有工具调用时，micro 不压缩。
     * <p>为什么重要：纯对话不需要压缩工具结果。</p>
     */
    @Test
    void microShouldNotCompactWithoutTools() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("你好"),
            ChatMessage.assistant("你好")
        );

        List<ChatMessage> result = CompactionUtils.microCompact(history, 1);

        assertEquals(history, result);
    }

    /**
     * 规则：保留最近 N 组工具交换，其余替换成占位符。
     * <p>为什么重要：旧工具结果通常不需要完整正文。</p>
     */
    @Test
    void microShouldCompactOldToolResults() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("创建设备 1"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create", "{}")
            )),
            ChatMessage.tool("设备 1 已创建", "call-1"),
            ChatMessage.user("创建设备 2"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-2", "create", "{}")
            )),
            ChatMessage.tool("设备 2 已创建", "call-2")
        );

        // 保留最近 1 组工具交换，micro 只替换内容不删除消息
        List<ChatMessage> result = CompactionUtils.microCompact(history, 1);

        assertEquals(6, result.size());
        // 第一组工具结果被压缩
        assertEquals(CompactionUtils.COMPACTED_TOOL_RESULT,
            ((ChatMessage.ToolMessage) result.get(2)).getContent());
        // 第二组工具结果保留
        assertEquals("设备 2 已创建",
            ((ChatMessage.ToolMessage) result.get(5)).getContent());
    }

    /**
     * 规则：micro 压缩必须保留 tool_call_id。
     * <p>为什么重要：tool_call_id 是配对的唯一键。</p>
     */
    @Test
    void microShouldPreserveToolCallId() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create", "{}")
            )),
            ChatMessage.tool("设备已创建", "call-1")
        );

        List<ChatMessage> result = CompactionUtils.microCompact(history, 0);

        // tool_call_id 必须保留
        assertEquals("call-1",
            ((ChatMessage.ToolMessage) result.get(2)).getToolCallId());
        // 但内容被替换
        assertEquals(CompactionUtils.COMPACTED_TOOL_RESULT,
            ((ChatMessage.ToolMessage) result.get(2)).getContent());
    }

    /**
     * 规则：micro 压缩后必须通过 validateToolPairing。
     * <p>为什么重要：压缩不能破坏协议约束。</p>
     */
    @Test
    void microShouldPreserveToolPairing() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("批量检查"),
            ChatMessage.assistant(null, Arrays.asList(
                new ToolCall("call-1", "inspect", "{}"),
                new ToolCall("call-2", "inspect", "{}")
            )),
            ChatMessage.tool("设备 1 正常", "call-1"),
            ChatMessage.tool("设备 2 离线", "call-2")
        );

        List<ChatMessage> result = CompactionUtils.microCompact(history, 0);

        // 压缩后仍然合法
        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(result));
        // 两个 tool 结果都被压缩
        assertEquals(CompactionUtils.COMPACTED_TOOL_RESULT,
            ((ChatMessage.ToolMessage) result.get(2)).getContent());
        assertEquals(CompactionUtils.COMPACTED_TOOL_RESULT,
            ((ChatMessage.ToolMessage) result.get(3)).getContent());
    }

    /**
     * 规则：keepRecentToolGroups=0 时压缩所有工具组。
     * <p>为什么重要：响应式压缩需要激进策略。</p>
     */
    @Test
    void microShouldCompactAllWhenKeepZero() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create", "{}")
            )),
            ChatMessage.tool("设备已创建", "call-1")
        );

        List<ChatMessage> result = CompactionUtils.microCompact(history, 0);

        assertEquals(CompactionUtils.COMPACTED_TOOL_RESULT,
            ((ChatMessage.ToolMessage) result.get(2)).getContent());
    }
}
