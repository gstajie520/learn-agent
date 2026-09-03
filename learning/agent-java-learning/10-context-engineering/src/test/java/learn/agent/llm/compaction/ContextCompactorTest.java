package learn.agent.llm.compaction;

import learn.agent.llm.artifact.ArtifactManager;
import learn.agent.llm.artifact.ChatMessage;
import learn.agent.llm.artifact.CompactionUtils;
import learn.agent.llm.artifact.ToolCall;
import learn.agent.llm.artifact.MessageUtils;
import learn.agent.llm.workspace.WorkspaceGuard;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * {@link ContextCompactor} 的测试。
 *
 * @author cj
 * @since 2026-09-03
 */
class ContextCompactorTest {
    @TempDir
    Path tempDir;

    private Path workspaceRoot;
    private ArtifactManager artifactManager;
    private ContextCompactor compactor;

    @BeforeEach
    void setUp() throws IOException {
        workspaceRoot = tempDir.resolve("workspace");
        Files.createDirectories(workspaceRoot);

        // artifactThreshold=1000
        artifactManager = new ArtifactManager(workspaceRoot, "artifacts", 1000);

        // maxGroups=10, keepHeadGroups=2, keepRecentToolGroups=2
        compactor = new ContextCompactor(artifactManager, 10, 2, 2);
    }

    /**
     * 规则：少于 micro 阈值时只做 artifact，不压缩消息。
     * <p>为什么重要：避免过早压缩。</p>
     */
    @Test
    void shouldOnlyArtifactWhenBelowThreshold() {
        // 2 组：低于 micro 阈值 (3)
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("查询"),
            ChatMessage.assistant("结果")
        );

        List<ChatMessage> result = compactor.compact(history);

        // 消息数不变
        assertEquals(2, result.size());
    }

    /**
     * 规则：超过 micro 阈值但低于 snip 阈值时，使用 micro 压缩。
     * <p>为什么重要：中等长度历史的温和压缩。</p>
     */
    @Test
    void shouldUseMicroWhenAboveMicroThreshold() {
        // 4 个工具交换组：超过 micro 阈值 (3)，低于 snip 阈值 (5)
        // 每个工具交换组算 1 组，所以需要 4 个工具交换
        List<ChatMessage> history = new ArrayList<>();
        history.add(ChatMessage.user("开始"));  // 单独一组
        for (int i = 0; i < 4; i++) {
            history.add(ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-" + i, "inspect", "{}")
            )));
            history.add(ChatMessage.tool("小结果" + i, "call-" + i));
        }
        history.add(ChatMessage.assistant("完成"));  // 单独一组
        // 总共：1(user) + 4(工具组) + 1(assistant) = 6 组

        List<ChatMessage> result = compactor.compact(history);

        // micro 不删除消息，只替换旧工具结果
        assertEquals(history.size(), result.size());

        // 前面的工具结果被压缩（保留最近 2 组）
        ChatMessage.ToolMessage firstTool = (ChatMessage.ToolMessage) result.get(2);
        assertEquals(CompactionUtils.COMPACTED_TOOL_RESULT, firstTool.getContent());
    }

    /**
     * 规则：超过 snip 阈值时，使用 snip 压缩（删除中间组）。
     * <p>为什么重要：长历史的激进压缩。</p>
     */
    @Test
    void shouldUseSnipWhenAboveSnipThreshold() {
        // 6 组：超过 snip 阈值 (5)
        List<ChatMessage> history = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            history.add(ChatMessage.user("请求" + i));
            history.add(ChatMessage.assistant("响应" + i));
        }

        List<ChatMessage> result = compactor.compact(history);

        // snip 会删除中间消息
        assertTrue(result.size() < history.size());
    }

    /**
     * 规则：大工具结果永远先落盘，再考虑其他压缩。
     * <p>为什么重要：artifact 最节省 token。</p>
     */
    @Test
    void shouldAlwaysArtifactFirst() throws IOException {
        // 创建大内容（超过阈值 1000）
        StringBuilder sb = new StringBuilder(1500);
        for (int i = 0; i < 1500; i++) {
            sb.append('x');
        }
        String largeContent = sb.toString();

        // 2 组：低于所有阈值
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("检查"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "inspect", "{}")
            )),
            ChatMessage.tool(largeContent, "call-1"),
            ChatMessage.assistant("完成")
        );

        List<ChatMessage> result = compactor.compact(history);

        // 即使不触发 snip/micro，大工具结果也被落盘
        ChatMessage.ToolMessage toolMsg = (ChatMessage.ToolMessage) result.get(2);
        assertTrue(toolMsg.getContent().startsWith("[Artifact:"));

        // 文件被创建
        Path artifactDir = workspaceRoot.resolve("artifacts");
        assertEquals(1, Files.list(artifactDir).count());
    }

    /**
     * 规则：压缩后 tool pairing 仍然合法。
     * <p>为什么重要：确保压缩不破坏协议。</p>
     */
    @Test
    void shouldPreserveToolPairingAfterCompaction() {
        // 6 组：触发 snip
        List<ChatMessage> history = new ArrayList<>();
        for (int i = 0; i < 6; i++) {
            history.add(ChatMessage.user("请求" + i));
            history.add(ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-" + i, "tool", "{}")
            )));
            history.add(ChatMessage.tool("结果" + i, "call-" + i));
            history.add(ChatMessage.assistant("完成" + i));
        }

        List<ChatMessage> result = compactor.compact(history);

        // pairing 仍然合法
        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(result));
    }
}
