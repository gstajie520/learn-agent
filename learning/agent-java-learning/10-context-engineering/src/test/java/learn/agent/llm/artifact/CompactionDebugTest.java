package learn.agent.llm.artifact;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import org.junit.jupiter.api.Test;

/**
 * 调试压缩逻辑。
 */
class CompactionDebugTest {

    @Test
    void debugSnipCompaction() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("问题 1"),      // group 0
            ChatMessage.assistant("回答 1"),  // group 1
            ChatMessage.user("问题 2"),      // group 2
            ChatMessage.assistant("回答 2"),  // group 3
            ChatMessage.user("问题 3"),      // group 4
            ChatMessage.assistant("回答 3")   // group 5
        );

        System.out.println("原始消息数：" + history.size());
        List<MessageGroup> groups = MessageGroup.fromHistory(history);
        System.out.println("原始组数：" + groups.size());

        // maxGroups=4, keepHead=1 → 保留 1 组头 + marker + 2 组尾
        List<ChatMessage> result = CompactionUtils.snipCompact(history, 4, 1);

        System.out.println("压缩后消息数：" + result.size());
        for (int i = 0; i < result.size(); i++) {
            ChatMessage msg = result.get(i);
            String content = "";
            if (msg instanceof ChatMessage.UserMessage) {
                content = ((ChatMessage.UserMessage) msg).getContent();
            } else if (msg instanceof ChatMessage.AssistantMessage) {
                content = ((ChatMessage.AssistantMessage) msg).getContent();
            } else if (msg instanceof ChatMessage.SystemMessage) {
                content = ((ChatMessage.SystemMessage) msg).getContent();
            }
            System.out.println(i + ": " + msg.getRole() + " - " + content);
        }
    }

    @Test
    void debugToolExchangeSnip() {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create", "{}")
            )),
            ChatMessage.tool("已创建", "call-1"),
            ChatMessage.user("检查设备"),
            ChatMessage.assistant("设备正常")
        );

        System.out.println("\n=== 工具交换 ===");
        System.out.println("原始消息数：" + history.size());
        List<MessageGroup> groups = MessageGroup.fromHistory(history);
        System.out.println("原始组数：" + groups.size());
        for (int i = 0; i < groups.size(); i++) {
            MessageGroup g = groups.get(i);
            System.out.println("组 " + i + ": " + g.getMessages().size() + " 条消息, isToolExchange=" + g.isToolExchange());
        }

        List<ChatMessage> result = CompactionUtils.snipCompact(history, 3, 1);
        System.out.println("压缩后消息数：" + result.size());
    }

    @Test
    void debugMicroCompaction() {
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

        System.out.println("\n=== Micro 压缩 ===");
        System.out.println("原始消息数：" + history.size());

        List<ChatMessage> result = CompactionUtils.microCompact(history, 1);
        System.out.println("压缩后消息数：" + result.size());
    }
}
