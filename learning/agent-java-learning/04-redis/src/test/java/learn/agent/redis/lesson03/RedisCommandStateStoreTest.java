package learn.agent.redis.lesson03;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import java.net.Socket;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 真实 Redis 命令状态存储测试。 */
public class RedisCommandStateStoreTest {

    /** 验证命令对象的多个字段可以保存到 Redis Hash 并读取回来。 */
    @Test
    public void shouldSaveAndFindCommandState() {
        // Arrange：没有 Redis 密码时跳过真实连接测试，避免把认证问题当成代码错误。
        Assumptions.assumeTrue(isRedisPortAvailable(), "Redis 端口不可用，跳过真实状态测试");
        String password = System.getenv("REDIS_PASSWORD");
        Assumptions.assumeTrue(password != null && !password.trim().isEmpty(), "REDIS_PASSWORD 未设置，跳过真实状态测试");
        String commandId = "cmd-state-test-" + UUID.randomUUID();

        try (RedisCommandStateStore store = new RedisCommandStateStore("127.0.0.1", 6379, password)) {
            // Act：保存一条 PENDING 命令，再从 Redis 查询。
            store.save(new RedisCommandState(commandId, "生成预览", "PENDING", ""));
            RedisCommandState state = store.find(commandId);

            // Assert：字段保持一致，并且状态设置了 TTL。
            assertNotNull(state);
            assertEquals(commandId, state.getCommandId());
            assertEquals("生成预览", state.getInstruction());
            assertEquals("PENDING", state.getStatus());
            assertTrue(store.ttl(commandId) > 0);
            store.delete(commandId);
        }
    }

    private boolean isRedisPortAvailable() {
        try (Socket socket = new Socket("127.0.0.1", 6379)) {
            return true;
        } catch (Exception exception) {
            return false;
        }
    }
}
