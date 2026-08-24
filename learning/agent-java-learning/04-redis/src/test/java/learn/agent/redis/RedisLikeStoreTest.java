package learn.agent.redis;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Redis SETNX 和 TTL 语义测试。
 *
 * <p>这些测试验证的是幂等业务规则，不是为了测试 HashMap 本身。</p>
 */
public class RedisLikeStoreTest {

    /** 验证同一个 key 只有第一次 SETNX 能成功。 */
    @Test
    public void shouldOnlySetKeyOnce() {
        // Arrange：准备一个空的 Redis 模拟存储。
        RedisLikeStore store = new RedisLikeStore();

        // Act：第一次和第二次写入同一个幂等 key。
        boolean firstWrite = store.setIfAbsent("claim:cmd-001", "PROCESSING", 1000);
        boolean secondWrite = store.setIfAbsent("claim:cmd-001", "PROCESSING", 1000);

        // Assert：第一次成功，第二次失败，避免重复消费者同时执行。
        assertTrue(firstWrite);
        assertFalse(secondWrite);
        assertEquals("PROCESSING", store.get("claim:cmd-001"));
    }

    /** 验证 TTL 到期后 key 会失效，避免异常留下永久幂等锁。 */
    @Test
    public void shouldExpireKeyAfterTtl() throws Exception {
        // Arrange：写入一个 30 毫秒后过期的幂等 key。
        RedisLikeStore store = new RedisLikeStore();
        store.setIfAbsent("claim:cmd-002", "PROCESSING", 30);

        // Act：等待超过 TTL，再读取 key。
        Thread.sleep(50);

        // Assert：过期后读取不到，下一次可以重新抢占。
        assertNull(store.get("claim:cmd-002"));
        assertTrue(store.setIfAbsent("claim:cmd-002", "PROCESSING", 1000));
    }
}
