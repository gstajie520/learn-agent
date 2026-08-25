package learn.agent.redis.lesson02;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import java.net.Socket;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 真实 Redis 客户端测试。
 *
 * <p>本机没有 Redis 时跳过真实连接测试，离线模拟测试仍会执行。</p>
 */
public class RealRedisIdempotencyStoreTest {

    /** 验证 Lettuce 发出的真实 SET NX EX 具备第一次成功、第二次失败的语义。 */
    @Test
    public void shouldUseRealRedisSetNx() {
        // Arrange：没有 Redis 服务时跳过本测试，避免环境问题阻断基础学习。
        Assumptions.assumeTrue(isRedisPortAvailable(), "127.0.0.1:6379 不可用，跳过真实 Redis 测试");
        String password = System.getenv("REDIS_PASSWORD");
        Assumptions.assumeTrue(
                password != null && !password.trim().isEmpty(),
                "本机 Redis 开启认证，但 REDIS_PASSWORD 未设置，跳过真实 Redis 测试"
        );
        String key = "agent:learning:test:" + UUID.randomUUID();

        try (RealRedisIdempotencyStore store = new RealRedisIdempotencyStore("127.0.0.1", 6379, password)) {
            // Act：第一次和第二次写入同一个真实 Redis key。
            boolean firstWrite = store.setIfAbsent(key, "PROCESSING", 30);
            boolean secondWrite = store.setIfAbsent(key, "PROCESSING", 30);

            // Assert：只有第一次写入成功，并且 Redis 已设置 TTL。
            assertTrue(firstWrite);
            assertFalse(secondWrite);
            assertEquals("PROCESSING", store.get(key));
            assertTrue(store.ttl(key) > 0);
            store.delete(key);
        }
    }

    /** 用 Socket 检查本机 Redis 端口，避免测试直接抛连接异常。 */
    private boolean isRedisPortAvailable() {
        try (Socket socket = new Socket("127.0.0.1", 6379)) {
            return true;
        } catch (Exception exception) {
            return false;
        }
    }
}
