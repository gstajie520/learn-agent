package learn.agent.llm.memory;

import learn.agent.llm.artifact.ChatMessage;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 测试 {@link MemorySession} 的回合生命周期和记忆选择逻辑。
 *
 * <p><strong>Arrange/Act/Assert 模式：</strong>
 * <ul>
 *   <li>Arrange：准备 MemoryStore、模拟选择器/提取器、会话历史</li>
 *   <li>Act：调用 beginTurn、beforeModel、complete 等生命周期方法</li>
 *   <li>Assert：验证选中记忆、注入消息、错误处理</li>
 * </ul>
 */
class MemorySessionTest {

    /**
     * 验证空存储时 beginTurn 不选择任何记忆。
     */
    @Test
    void testBeginTurnEmptyStore(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemorySession session = new MemorySession(store, null, null, null, 5, 10, true);

        // Act
        session.beginTurn("测试查询");

        // Assert
        assertTrue(session.getSelected().isEmpty());
    }

    /**
     * 验证无选择器时使用关键词回退逻辑。
     */
    @Test
    void testBeginTurnKeywordFallback(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("java-tips", "Java 编程技巧", MemoryType.USER, "Java 相关内容");
        MemoryRecord record2 = new MemoryRecord("python-tips", "Python 编程技巧", MemoryType.USER, "Python 相关内容");
        store.extend(Arrays.asList(record1, record2));

        MemorySession session = new MemorySession(store, null, null, null, 5, 10, true);

        // Act
        session.beginTurn("如何使用 Java");

        // Assert
        List<MemoryRecord> selected = session.getSelected();
        assertEquals(1, selected.size());
        assertEquals("java-tips", selected.get(0).getName());
    }

    /**
     * 验证选择器成功时优先使用模型选择。
     */
    @Test
    void testBeginTurnWithSelector(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条记忆", MemoryType.USER, "内容1");
        MemoryRecord record2 = new MemoryRecord("memory-2", "第二条记忆", MemoryType.USER, "内容2");
        store.extend(Arrays.asList(record1, record2));

        MemorySelector selector = (query, catalog) -> "[\"memory-2\"]";
        MemorySession session = new MemorySession(store, selector, null, null, 5, 10, true);

        // Act
        session.beginTurn("测试查询");

        // Assert
        List<MemoryRecord> selected = session.getSelected();
        assertEquals(1, selected.size());
        assertEquals("memory-2", selected.get(0).getName());
    }

    /**
     * 验证选择器返回无效名称时抛出异常并回退到关键词选择。
     */
    @Test
    void testBeginTurnSelectorInvalidName(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条记忆", MemoryType.USER, "内容1");
        store.extend(Collections.singletonList(record1));

        MemorySelector selector = (query, catalog) -> "[\"nonexistent\"]";
        MemorySession session = new MemorySession(store, selector, null, null, 5, 10, true);

        // Act
        session.beginTurn("memory");

        // Assert - 回退到关键词选择
        assertEquals(1, session.getSelected().size());
        assertNotNull(session.getLastError());
    }

    /**
     * 验证 maxSelected 限制选择数量。
     */
    @Test
    void testBeginTurnMaxSelected(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条记忆", MemoryType.USER, "内容1");
        MemoryRecord record2 = new MemoryRecord("memory-2", "第二条记忆", MemoryType.USER, "内容2");
        MemoryRecord record3 = new MemoryRecord("memory-3", "第三条记忆", MemoryType.USER, "内容3");
        store.extend(Arrays.asList(record1, record2, record3));

        MemorySelector selector = (query, catalog) -> "[\"memory-1\", \"memory-2\", \"memory-3\"]";
        MemorySession session = new MemorySession(store, selector, null, null, 2, 10, true);

        // Act
        session.beginTurn("测试查询");

        // Assert
        assertEquals(2, session.getSelected().size());
    }

    /**
     * 验证 beforeModel 返回正确的 system 消息。
     */
    @Test
    void testBeforeModel(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record = new MemoryRecord("test-memory", "测试记忆", MemoryType.USER, "记忆内容");
        store.extend(Collections.singletonList(record));

        MemorySelector selector = (query, catalog) -> "[\"test-memory\"]";
        MemorySession session = new MemorySession(store, selector, null, null, 5, 10, true);
        session.beginTurn("测试");

        // Act
        List<ChatMessage> messages = session.beforeModel();

        // Assert
        assertEquals(1, messages.size());
        ChatMessage.SystemMessage systemMessage = (ChatMessage.SystemMessage) messages.get(0);
        assertTrue(systemMessage.getContent().contains("test-memory"));
        assertTrue(systemMessage.getContent().contains("记忆内容"));
    }

    /**
     * 验证未选中任何记忆时 beforeModel 返回空列表。
     */
    @Test
    void testBeforeModelNoSelection(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemorySession session = new MemorySession(store, null, null, null, 5, 10, true);
        session.beginTurn("测试");

        // Act
        List<ChatMessage> messages = session.beforeModel();

        // Assert
        assertTrue(messages.isEmpty());
    }

    /**
     * 验证 emitContextMessages 为 false 时 beforeModel 返回空列表。
     */
    @Test
    void testBeforeModelNoEmit(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record = new MemoryRecord("test-memory", "测试记忆", MemoryType.USER, "记忆内容");
        store.extend(Collections.singletonList(record));

        MemorySelector selector = (query, catalog) -> "[\"test-memory\"]";
        MemorySession session = new MemorySession(store, selector, null, null, 5, 10, false);
        session.beginTurn("测试");

        // Act
        List<ChatMessage> messages = session.beforeModel();

        // Assert
        assertTrue(messages.isEmpty());
    }

    /**
     * 验证 complete 成功提取并追加新记忆。
     */
    @Test
    void testCompleteExtract(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryExtractor extractor = (history, catalog) ->
            "[{\"name\":\"new-memory\",\"type\":\"user\",\"description\":\"新记忆\",\"body\":\"新内容\"}]";

        MemorySession session = new MemorySession(store, null, extractor, null, 5, 10, true);

        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("测试用户消息"),
            ChatMessage.assistant("测试助手回复")
        );

        // Act
        session.complete(history);

        // Assert
        List<MemoryRecord> records = store.records();
        assertEquals(1, records.size());
        assertEquals("new-memory", records.get(0).getName());
    }

    /**
     * 验证达到整理阈值时触发整理操作。
     */
    @Test
    void testCompleteConsolidate(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条", MemoryType.USER, "内容1");
        store.extend(Collections.singletonList(record1));

        MemoryExtractor extractor = (history, catalog) ->
            "[{\"name\":\"memory-2\",\"type\":\"user\",\"description\":\"第二条\",\"body\":\"内容2\"}]";

        MemoryConsolidator consolidator = (records) ->
            "{\"source_names\":[\"memory-1\",\"memory-2\"],\"records\":[{\"name\":\"merged\",\"type\":\"user\",\"description\":\"合并\",\"body\":\"合并内容\"}]}";

        MemorySession session = new MemorySession(store, null, extractor, consolidator, 5, 2, true);

        List<ChatMessage> history = Arrays.asList(
            ChatMessage.user("测试"),
            ChatMessage.assistant("回复")
        );

        // Act
        session.complete(history);

        // Assert
        List<MemoryRecord> records = store.records();
        assertEquals(1, records.size());
        assertEquals("merged", records.get(0).getName());
    }

    /**
     * 验证提取失败时设置错误信息但不抛出异常。
     */
    @Test
    void testCompleteExtractFailure(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryExtractor extractor = (history, catalog) -> {
            throw new RuntimeException("提取失败");
        };

        MemorySession session = new MemorySession(store, null, extractor, null, 5, 10, true);

        List<ChatMessage> history = Collections.singletonList(ChatMessage.user("测试"));

        // Act
        session.complete(history);

        // Assert
        assertNotNull(session.getLastError());
        assertEquals("Memory extraction failed", session.getLastError());
        assertTrue(store.records().isEmpty());
    }

    /**
     * 验证整理失败时设置错误信息但不抛出异常。
     */
    @Test
    void testCompleteConsolidateFailure(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条", MemoryType.USER, "内容1");
        MemoryRecord record2 = new MemoryRecord("memory-2", "第二条", MemoryType.USER, "内容2");
        store.extend(Arrays.asList(record1, record2));

        MemoryConsolidator consolidator = (records) -> {
            throw new RuntimeException("整理失败");
        };

        MemorySession session = new MemorySession(store, null, null, consolidator, 5, 2, true);

        List<ChatMessage> history = Collections.singletonList(ChatMessage.user("测试"));

        // Act
        session.complete(history);

        // Assert
        assertNotNull(session.getLastError());
        assertEquals("Memory consolidation failed", session.getLastError());
        // 原有记忆保持不变
        assertEquals(2, store.records().size());
    }

    /**
     * 验证中文关键词选择能正确匹配。
     */
    @Test
    void testKeywordSelectChinese(@TempDir Path tempDir) throws Exception {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("java-memory", "Java 编程技巧", MemoryType.USER, "内容");
        MemoryRecord record2 = new MemoryRecord("test-memory", "测试相关记忆", MemoryType.USER, "内容");
        store.extend(Arrays.asList(record1, record2));

        MemorySession session = new MemorySession(store, null, null, null, 5, 10, true);

        // Act
        session.beginTurn("如何进行测试");

        // Assert
        List<MemoryRecord> selected = session.getSelected();
        assertEquals(1, selected.size());
        assertEquals("test-memory", selected.get(0).getName());
    }
}
