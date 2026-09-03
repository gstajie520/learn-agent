package learn.agent.llm.artifact;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 测试 {@link ArtifactManager} 的产物落盘机制。
 */
class ArtifactManagerTest {

    @TempDir
    Path tempDir;

    private Path workspaceRoot;
    private Path artifactDir;
    private ArtifactManager manager;

    @BeforeEach
    void setUp() throws IOException {
        workspaceRoot = tempDir.resolve("workspace");
        artifactDir = workspaceRoot.resolve("artifacts");

        // WorkspaceGuard.open() 要求工作区根必须已经存在
        Files.createDirectories(workspaceRoot);

        manager = new ArtifactManager(workspaceRoot, "artifacts", 100);
        manager.resetSequence();
    }

    @AfterEach
    void tearDown() throws IOException {
        // 清理临时目录
        if (Files.exists(workspaceRoot)) {
            Files.walk(workspaceRoot)
                .sorted((a, b) -> b.compareTo(a))
                .forEach(path -> {
                    try {
                        Files.deleteIfExists(path);
                    } catch (IOException e) {
                        // 忽略清理错误
                    }
                });
        }
    }

    /**
     * 规则：小于阈值的 tool 消息不落盘。
     * <p>为什么重要：避免创建过多小文件。</p>
     */
    @Test
    void shouldNotCompactSmallToolResults() throws IOException {
        String smallContent = "设备已创建";  // 远小于 100 字节
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("创建设备"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "create", "")
            )),
            ChatMessage.tool(smallContent, "call-1")
        );

        List<ChatMessage> result = manager.compactToArtifacts(history);

        // 小消息不变
        assertEquals(3, result.size());
        assertEquals(smallContent,
            ((ChatMessage.ToolMessage) result.get(2)).getContent());

        // 不创建文件
        if (Files.exists(artifactDir)) {
            assertEquals(0, Files.list(artifactDir).count());
        }
    }

    /**
     * 规则：超过阈值的 tool 消息写入文件，历史中替换为引用。
     * <p>为什么重要：节省历史 token。</p>
     */
    @Test
    void shouldCompactLargeToolResults() throws IOException {
        String largeContent = repeat('x', 200);  // 超过 100 字节
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("检查日志"),
            ChatMessage.assistant(null, Collections.singletonList(
                new ToolCall("call-1", "inspect", "{}")
            )),
            ChatMessage.tool(largeContent, "call-1")
        );

        List<ChatMessage> result = manager.compactToArtifacts(history);

        // 大消息被替换为引用
        assertEquals(3, result.size());
        ChatMessage.ToolMessage toolMsg = (ChatMessage.ToolMessage) result.get(2);
        assertTrue(toolMsg.getContent().startsWith("[Artifact: artifact-"));
        assertTrue(toolMsg.getContent().endsWith(".txt]"));

        // 保留 tool_call_id
        assertEquals("call-1", toolMsg.getToolCallId());

        // 文件被创建
        assertEquals(1, Files.list(artifactDir).count());
        Path artifactFile = Files.list(artifactDir).findFirst().orElseThrow(() -> new AssertionError("artifact file not found"));
        assertEquals(largeContent, new String(Files.readAllBytes(artifactFile), "UTF-8"));
    }

    /**
     * 规则：产物目录不存在时自动创建。
     * <p>为什么重要：首次使用时的便利性。</p>
     */
    @Test
    void shouldCreateArtifactDirIfNotExists() throws IOException {
        assertFalse(Files.exists(artifactDir));

        String largeContent = repeat('x', 200);
        List<ChatMessage> history = Collections.singletonList(
            ChatMessage.tool(largeContent, "call-1")
        );

        manager.compactToArtifacts(history);

        assertTrue(Files.exists(artifactDir));
        assertTrue(Files.isDirectory(artifactDir));
    }

    /**
     * 规则：多个大型工具结果生成不同文件名（时间戳+序号）。
     * <p>为什么重要：避免文件名冲突。</p>
     */
    @Test
    void shouldGenerateUniqueFilenames() throws IOException {
        String content1 = repeat('a', 200);
        String content2 = repeat('b', 200);

        List<ChatMessage> history = Arrays.asList(
            ChatMessage.tool(content1, "call-1"),
            ChatMessage.tool(content2, "call-2")
        );

        List<ChatMessage> result = manager.compactToArtifacts(history);

        // 两个引用
        ChatMessage.ToolMessage tool1 = (ChatMessage.ToolMessage) result.get(0);
        ChatMessage.ToolMessage tool2 = (ChatMessage.ToolMessage) result.get(1);
        assertTrue(tool1.getContent().contains("artifact-"));
        assertTrue(tool2.getContent().contains("artifact-"));

        // 两个文件
        assertEquals(2, Files.list(artifactDir).count());
    }

    /**
     * 规则：非 tool 消息不受影响。
     * <p>为什么重要：落盘仅针对工具结果。</p>
     */
    @Test
    void shouldNotAffectNonToolMessages() throws IOException {
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user(repeat('x', 200)),
            ChatMessage.assistant(repeat('y', 200))
        );

        List<ChatMessage> result = manager.compactToArtifacts(history);

        // 内容不变
        assertEquals(history, result);

        // 不创建文件
        if (Files.exists(artifactDir)) {
            assertEquals(0, Files.list(artifactDir).count());
        }
    }

    /**
     * 规则：产物路径必须在工作区内。
     * <p>为什么重要：安全边界（防止目录遍历攻击）。</p>
     */
    @Test
    void shouldEnforceBoundary() throws IOException {
        // 尝试使用 ".." 逃逸
        ArtifactManager badManager = new ArtifactManager(workspaceRoot, "../outside", 100);

        String largeContent = repeat('x', 200);
        List<ChatMessage> history = Collections.singletonList(
            ChatMessage.tool(largeContent, "call-1")
        );

        assertThrows(Exception.class,
            () -> badManager.compactToArtifacts(history),
            "应该拒绝包含 .. 的路径");
    }

    /**
     * 规则：保留 tool_call_id 不变。
     * <p>为什么重要：压缩不能破坏 tool pairing。</p>
     */
    @Test
    void shouldPreserveToolCallId() throws IOException {
        String largeContent = repeat('x', 200);
        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("批量检查"),
            ChatMessage.assistant(null, Arrays.asList(
                new ToolCall("call-1", "inspect", "{}"),
                new ToolCall("call-2", "inspect", "{}")
            )),
            ChatMessage.tool(largeContent, "call-1"),
            ChatMessage.tool(largeContent, "call-2")
        );

        List<ChatMessage> result = manager.compactToArtifacts(history);

        // tool_call_id 必须保留
        assertEquals("call-1",
            ((ChatMessage.ToolMessage) result.get(2)).getToolCallId());
        assertEquals("call-2",
            ((ChatMessage.ToolMessage) result.get(3)).getToolCallId());

        // pairing 仍然合法
        assertDoesNotThrow(() -> MessageUtils.validateToolPairing(result));
    }

    /**
     * 辅助方法：创建重复字符串（Java 8 兼容）。
     */
    private static String repeat(char c, int count) {
        StringBuilder sb = new StringBuilder(count);
        for (int i = 0; i < count; i++) {
            sb.append(c);
        }
        return sb.toString();
    }
}
