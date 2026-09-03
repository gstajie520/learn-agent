package learn.agent.llm.memory;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 测试 {@link MemoryStore} 持久化存储的文件操作和数据完整性。
 *
 * <p><strong>Arrange/Act/Assert 模式：</strong>
 * <ul>
 *   <li>Arrange：准备临时目录、记忆记录、文件内容</li>
 *   <li>Act：调用 extend、records、applyConsolidation 等方法</li>
 *   <li>Assert：验证返回值、文件存在性、文件内容、异常抛出</li>
 * </ul>
 */
class MemoryStoreTest {

    /**
     * 验证空目录返回空记忆列表。
     */
    @Test
    void testEmptyStore(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);

        // Act
        List<MemoryRecord> records = store.records();

        // Assert
        assertTrue(records.isEmpty());
    }

    /**
     * 验证追加单条记忆后能正确读取。
     */
    @Test
    void testExtendSingleRecord(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record = new MemoryRecord("test-memory", "测试记忆", MemoryType.USER, "这是测试内容");

        // Act
        store.extend(Collections.singletonList(record));
        List<MemoryRecord> records = store.records();

        // Assert
        assertEquals(1, records.size());
        assertEquals(record, records.get(0));
        assertTrue(Files.exists(tempDir.resolve("manifest.json")));
        assertTrue(Files.exists(tempDir.resolve("test-memory.md")));
        assertTrue(Files.exists(tempDir.resolve("MEMORY.md")));
    }

    /**
     * 验证追加多条记忆后能正确读取。
     */
    @Test
    void testExtendMultipleRecords(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条记忆", MemoryType.USER, "内容1");
        MemoryRecord record2 = new MemoryRecord("memory-2", "第二条记忆", MemoryType.FEEDBACK, "内容2");

        // Act
        store.extend(Arrays.asList(record1, record2));
        List<MemoryRecord> records = store.records();

        // Assert
        assertEquals(2, records.size());
        assertEquals(record1, records.get(0));
        assertEquals(record2, records.get(1));
    }

    /**
     * 验证追加重复 name 的记忆时抛出异常。
     */
    @Test
    void testExtendDuplicateName(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("test", "第一条", MemoryType.USER, "内容1");
        MemoryRecord record2 = new MemoryRecord("test", "第二条", MemoryType.USER, "内容2");
        store.extend(Collections.singletonList(record1));

        // Act & Assert
        assertThrows(MemoryStoreException.class, () -> {
            store.extend(Collections.singletonList(record2));
        });
    }

    /**
     * 验证 renderCatalog 返回正确的目录格式。
     */
    @Test
    void testRenderCatalog(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条记忆", MemoryType.USER, "内容1");
        MemoryRecord record2 = new MemoryRecord("memory-2", "第二条记忆", MemoryType.FEEDBACK, "内容2");
        store.extend(Arrays.asList(record1, record2));

        // Act
        String catalog = store.renderCatalog();

        // Assert
        assertTrue(catalog.contains("- memory-1: 第一条记忆"));
        assertTrue(catalog.contains("- memory-2: 第二条记忆"));
    }

    /**
     * 验证空存储的 renderCatalog 返回空字符串。
     */
    @Test
    void testRenderCatalogEmpty(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);

        // Act
        String catalog = store.renderCatalog();

        // Assert
        assertEquals("", catalog);
    }

    /**
     * 验证整理操作能正确删除源记忆并写入整理后的记忆。
     */
    @Test
    void testApplyConsolidation(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条", MemoryType.USER, "内容1");
        MemoryRecord record2 = new MemoryRecord("memory-2", "第二条", MemoryType.USER, "内容2");
        MemoryRecord record3 = new MemoryRecord("memory-3", "第三条", MemoryType.USER, "内容3");
        store.extend(Arrays.asList(record1, record2, record3));

        List<MemoryRecord> current = store.records();
        List<MemoryRecord> extracted = Collections.emptyList();
        List<String> sourceNames = Arrays.asList("memory-1", "memory-2");
        MemoryRecord consolidated = new MemoryRecord("memory-merged", "合并记忆", MemoryType.USER, "合并内容");
        List<MemoryRecord> consolidatedList = Collections.singletonList(consolidated);

        // Act
        store.applyConsolidation(current, extracted, sourceNames, consolidatedList);
        List<MemoryRecord> records = store.records();

        // Assert
        assertEquals(2, records.size());
        assertTrue(records.contains(record3));
        assertTrue(records.contains(consolidated));
        assertFalse(Files.exists(tempDir.resolve("memory-1.md")));
        assertFalse(Files.exists(tempDir.resolve("memory-2.md")));
        assertTrue(Files.exists(tempDir.resolve("memory-3.md")));
        assertTrue(Files.exists(tempDir.resolve("memory-merged.md")));
    }

    /**
     * 验证整理操作引用不存在的源名称时抛出异常。
     */
    @Test
    void testApplyConsolidationInvalidSource(@TempDir Path tempDir) throws IOException {
        // Arrange
        MemoryStore store = new MemoryStore(tempDir);
        MemoryRecord record1 = new MemoryRecord("memory-1", "第一条", MemoryType.USER, "内容1");
        store.extend(Collections.singletonList(record1));

        List<MemoryRecord> current = store.records();
        List<MemoryRecord> extracted = Collections.emptyList();
        List<String> sourceNames = Arrays.asList("memory-1", "nonexistent");
        MemoryRecord consolidated = new MemoryRecord("memory-merged", "合并", MemoryType.USER, "内容");

        // Act & Assert
        assertThrows(MemoryStoreException.class, () -> {
            store.applyConsolidation(current, extracted, sourceNames, Collections.singletonList(consolidated));
        });
    }

    /**
     * 验证解析有效的 frontmatter 格式文件。
     */
    @Test
    void testParseMemoryFile(@TempDir Path tempDir) throws IOException {
        // Arrange
        Path filePath = tempDir.resolve("test-memory.md");
        String content = "---\n" +
                "name: test-memory\n" +
                "description: 测试记忆\n" +
                "metadata:\n" +
                "  type: user\n" +
                "---\n\n" +
                "这是记忆正文";
        Files.write(filePath, content.getBytes(StandardCharsets.UTF_8));

        Files.write(tempDir.resolve("manifest.json"), "[\"test-memory.md\"]".getBytes(StandardCharsets.UTF_8));

        MemoryStore store = new MemoryStore(tempDir);

        // Act
        List<MemoryRecord> records = store.records();

        // Assert
        assertEquals(1, records.size());
        MemoryRecord record = records.get(0);
        assertEquals("test-memory", record.getName());
        assertEquals("测试记忆", record.getDescription());
        assertEquals(MemoryType.USER, record.getKind());
        assertEquals("这是记忆正文", record.getBody());
    }

    /**
     * 验证 manifest 引用不存在的文件时抛出异常。
     */
    @Test
    void testManifestReferencesMissingFile(@TempDir Path tempDir) throws IOException {
        // Arrange
        Files.write(tempDir.resolve("manifest.json"), "[\"nonexistent.md\"]".getBytes(StandardCharsets.UTF_8));
        MemoryStore store = new MemoryStore(tempDir);

        // Act & Assert
        assertThrows(MemoryStoreException.class, () -> {
            store.records();
        });
    }

    /**
     * 验证缺少 frontmatter 的文件抛出异常。
     */
    @Test
    void testInvalidFrontmatter(@TempDir Path tempDir) throws IOException {
        // Arrange
        Path filePath = tempDir.resolve("test-memory.md");
        String content = "没有 frontmatter 的内容";
        Files.write(filePath, content.getBytes(StandardCharsets.UTF_8));
        Files.write(tempDir.resolve("manifest.json"), "[\"test-memory.md\"]".getBytes(StandardCharsets.UTF_8));

        MemoryStore store = new MemoryStore(tempDir);

        // Act & Assert
        assertThrows(MemoryStoreException.class, () -> {
            store.records();
        });
    }
}
