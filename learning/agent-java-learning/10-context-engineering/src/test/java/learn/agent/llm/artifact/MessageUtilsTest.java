package learn.agent.llm.artifact;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 测试 {@link MessageUtils#validateToolPairing}。
 * 核心规则：assistant 工具调用后必须紧随对应数量的 tool 消息。
 */
class MessageUtilsTest {

    /**
     * 规则：合法的完整工具交换必须通过校验。
     * <p>为什么重要：这是协议的正常路径，压缩后仍需保持这个结构。</p>
     */
    @Test
    void shouldPassValidToolExchange() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create_device", "{}")
            )),
            ChatMessage.tool("设备已创建", "call-1")
        );

        // 不应抛异常
        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(messages));
    }

    /**
     * 规则：assistant 多个工具调用必须全部回填。
     * <p>为什么重要：模型一次可以调用多个工具，每个都需要结果。</p>
     */
    @Test
    void shouldPassMultipleToolCalls() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.user("检查设备"),
            ChatMessage.assistant(null, Arrays.asList(
                new ToolCall("call-1", "inspect", "{}"),
                new ToolCall("call-2", "inspect", "{}")
            )),
            ChatMessage.tool("设备 1 正常", "call-1"),
            ChatMessage.tool("设备 2 离线", "call-2")
        );

        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(messages));
    }

    /**
     * 规则：pending 为空时遇到 tool 消息是孤儿。
     * <p>为什么重要：孤儿 tool 说明历史被错误裁剪，丢失了对应的 assistant 调用。</p>
     */
    @Test
    void shouldRejectOrphanToolResult() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.tool("设备已创建", "call-1")  // 没有对应的 assistant 调用
        );

        MessageContractException ex = assertThrows(
            MessageContractException.class,
            () -> MessageUtils.validateToolPairing(messages)
        );
        assertTrue(ex.getMessage().contains("orphan tool result id: call-1"));
    }

    /**
     * 规则：assistant 调用后必须紧随 tool 消息，不能插入其他消息。
     * <p>为什么重要：snip 压缩如果在中间插入省略标记，会破坏配对。</p>
     */
    @Test
    void shouldRejectMissingToolResult() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create_device", "{}")
            )),
            ChatMessage.user("另一个问题")  // 缺少 tool 消息
        );

        MessageContractException ex = assertThrows(
            MessageContractException.class,
            () -> MessageUtils.validateToolPairing(messages)
        );
        assertTrue(ex.getMessage().contains("missing tool results for ids"));
        assertTrue(ex.getMessage().contains("call-1"));
    }

    /**
     * 规则：tool 消息的 ID 必须在 pending 集合中。
     * <p>为什么重要：ID 不匹配说明 tool_call_id 被篡改或丢失。</p>
     */
    @Test
    void shouldRejectUnexpectedToolResultId() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create_device", "{}")
            )),
            ChatMessage.tool("设备已创建", "call-2")  // ID 不匹配
        );

        MessageContractException ex = assertThrows(
            MessageContractException.class,
            () -> MessageUtils.validateToolPairing(messages)
        );
        assertTrue(ex.getMessage().contains("unexpected tool result id: call-2"));
    }

    /**
     * 规则：多个工具调用不能只回填部分。
     * <p>为什么重要：micro 压缩保留 assistant 但删掉部分 tool 时会违反这条。</p>
     */
    @Test
    void shouldRejectPartialToolResults() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.user("检查设备"),
            ChatMessage.assistant(null, Arrays.asList(
                new ToolCall("call-1", "inspect", "{}"),
                new ToolCall("call-2", "inspect", "{}")
            )),
            ChatMessage.tool("设备 1 正常", "call-1")
            // 缺少 call-2 的结果
        );

        MessageContractException ex = assertThrows(
            MessageContractException.class,
            () -> MessageUtils.validateToolPairing(messages)
        );
        assertTrue(ex.getMessage().contains("missing tool results for ids"));
        assertTrue(ex.getMessage().contains("call-2"));
    }

    /**
     * 规则：空消息列表是合法的。
     * <p>为什么重要：会话刚开始时历史为空。</p>
     */
    @Test
    void shouldPassEmptyMessages() {
        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(Collections.emptyList()));
    }

    /**
     * 规则：没有工具调用的消息列表是合法的。
     * <p>为什么重要：纯对话不涉及工具。</p>
     */
    @Test
    void shouldPassMessagesWithoutTools() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.system("你是助手"),
            ChatMessage.user("你好"),
            ChatMessage.assistant("你好，有什么可以帮你？")
        );

        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(messages));
    }

    /**
     * 规则：historyUtf8Bytes 应计算消息内容的总字节数。
     * <p>为什么重要：预算判断依赖准确的字节统计。</p>
     */
    @Test
    void shouldCalculateHistoryUtf8Bytes() {
        List<ChatMessage> messages = Arrays.asList(
            ChatMessage.user("你好"),  // 6 bytes UTF-8
            ChatMessage.assistant("好的")  // 6 bytes UTF-8
        );

        int bytes = MessageUtils.historyUtf8Bytes(messages);
        assertEquals(12, bytes);
    }

    /**
     * 规则：工具调用的名称和参数也计入字节数。
     * <p>为什么重要：工具调用占用的上下文预算不能漏算。</p>
     */
    @Test
    void shouldCountToolCallBytes() {
        List<ChatMessage> messages = Collections.singletonList(
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create", "{\"a\":1}")
            ))
        );

        int bytes = MessageUtils.historyUtf8Bytes(messages);
        // "create" = 6 bytes, "{\"a\":1}" = 7 bytes
        assertEquals(13, bytes);
    }
}
