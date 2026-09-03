package learn.agent.llm.memory;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 测试 {@link MemoryRecord} 不可变值对象的契约。
 *
 * <p><strong>Arrange/Act/Assert 模式：</strong>
 * <ul>
 *   <li>Arrange：准备测试数据（name、description、kind、body）</li>
 *   <li>Act：创建 MemoryRecord 实例或调用方法</li>
 *   <li>Assert：验证字段值、equals/hashCode 行为、异常抛出</li>
 * </ul>
 */
class MemoryRecordTest {

    /**
     * 验证有效记忆记录的创建和字段访问。
     */
    @Test
    void testValidRecord() {
        // Arrange
        String name = "test-memory";
        String description = "测试记忆";
        MemoryType kind = MemoryType.USER;
        String body = "记忆正文内容";

        // Act
        MemoryRecord record = new MemoryRecord(name, description, kind, body);

        // Assert
        assertEquals(name, record.getName());
        assertEquals(description, record.getDescription());
        assertEquals(kind, record.getKind());
        assertEquals(body, record.getBody());
    }

    /**
     * 验证 name 为 null 时抛出异常。
     */
    @Test
    void testNullName() {
        // Arrange
        String name = null;
        String description = "描述";
        MemoryType kind = MemoryType.USER;
        String body = "正文";

        // Act & Assert
        assertThrows(IllegalArgumentException.class, () -> {
            new MemoryRecord(name, description, kind, body);
        });
    }

    /**
     * 验证 name 为空字符串时抛出异常。
     */
    @Test
    void testEmptyName() {
        // Arrange
        String name = "";
        String description = "描述";
        MemoryType kind = MemoryType.USER;
        String body = "正文";

        // Act & Assert
        assertThrows(IllegalArgumentException.class, () -> {
            new MemoryRecord(name, description, kind, body);
        });
    }

    /**
     * 验证 description 为 null 时抛出异常。
     */
    @Test
    void testNullDescription() {
        // Arrange
        String name = "test";
        String description = null;
        MemoryType kind = MemoryType.USER;
        String body = "正文";

        // Act & Assert
        assertThrows(IllegalArgumentException.class, () -> {
            new MemoryRecord(name, description, kind, body);
        });
    }

    /**
     * 验证 kind 为 null 时抛出异常。
     */
    @Test
    void testNullKind() {
        // Arrange
        String name = "test";
        String description = "描述";
        MemoryType kind = null;
        String body = "正文";

        // Act & Assert
        assertThrows(IllegalArgumentException.class, () -> {
            new MemoryRecord(name, description, kind, body);
        });
    }

    /**
     * 验证 body 为 null 时抛出异常。
     */
    @Test
    void testNullBody() {
        // Arrange
        String name = "test";
        String description = "描述";
        MemoryType kind = MemoryType.USER;
        String body = null;

        // Act & Assert
        assertThrows(IllegalArgumentException.class, () -> {
            new MemoryRecord(name, description, kind, body);
        });
    }

    /**
     * 验证相同内容的记忆记录 equals 返回 true。
     */
    @Test
    void testEquals() {
        // Arrange
        MemoryRecord record1 = new MemoryRecord("test", "描述", MemoryType.USER, "正文");
        MemoryRecord record2 = new MemoryRecord("test", "描述", MemoryType.USER, "正文");

        // Act & Assert
        assertEquals(record1, record2);
        assertEquals(record1.hashCode(), record2.hashCode());
    }

    /**
     * 验证不同 name 的记忆记录 equals 返回 false。
     */
    @Test
    void testNotEqualsDifferentName() {
        // Arrange
        MemoryRecord record1 = new MemoryRecord("test1", "描述", MemoryType.USER, "正文");
        MemoryRecord record2 = new MemoryRecord("test2", "描述", MemoryType.USER, "正文");

        // Act & Assert
        assertNotEquals(record1, record2);
    }

    /**
     * 验证不同 kind 的记忆记录 equals 返回 false。
     */
    @Test
    void testNotEqualsDifferentKind() {
        // Arrange
        MemoryRecord record1 = new MemoryRecord("test", "描述", MemoryType.USER, "正文");
        MemoryRecord record2 = new MemoryRecord("test", "描述", MemoryType.FEEDBACK, "正文");

        // Act & Assert
        assertNotEquals(record1, record2);
    }
}
