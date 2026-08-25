package learn.agent.redis.lesson05;

import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * 缓存服务的离线行为测试。
 *
 * <p>测试目标不是验证 Map，而是验证缓存命中、空值缓存和删除缓存这三条业务规则。</p>
 */
public class CommandCacheServiceTest {

    @Test
    public void shouldReadFromCacheAfterFirstLoad() {
        // Arrange：准备空缓存和一个会记录调用次数的数据源。
        InMemoryCacheClient cache = new InMemoryCacheClient();
        CommandCacheService service = new CommandCacheService(cache, 60, 10);
        AtomicInteger loaderCalls = new AtomicInteger();
        CommandCacheService.CommandLoader loader = new CommandCacheService.CommandLoader() {
            @Override
            public String load(String commandId) {
                loaderCalls.incrementAndGet();
                return "preview";
            }
        };

        // Act：连续查询同一个命令两次。
        String first = service.get("cmd-001", loader);
        String second = service.get("cmd-001", loader);

        // Assert：结果一致，但数据源只调用一次，第二次来自缓存。
        assertEquals("preview", first);
        assertEquals("preview", second);
        assertEquals(1, loaderCalls.get());
    }

    @Test
    public void shouldCacheNullResultForUnknownCommand() {
        // Arrange：数据源明确返回 null，代表 commandId 不存在。
        InMemoryCacheClient cache = new InMemoryCacheClient();
        CommandCacheService service = new CommandCacheService(cache, 60, 10);
        AtomicInteger loaderCalls = new AtomicInteger();
        CommandCacheService.CommandLoader loader = new CommandCacheService.CommandLoader() {
            @Override
            public String load(String commandId) {
                loaderCalls.incrementAndGet();
                return null;
            }
        };

        // Act：连续查询不存在的命令两次。
        String first = service.get("missing", loader);
        String second = service.get("missing", loader);

        // Assert：两次都是 null，但第二次没有再次访问数据源，避免缓存穿透。
        assertNull(first);
        assertNull(second);
        assertEquals(1, loaderCalls.get());
    }

    @Test
    public void shouldLoadAgainAfterEvict() {
        // Arrange：第一次查询会把 preview 放入缓存。
        InMemoryCacheClient cache = new InMemoryCacheClient();
        CommandCacheService service = new CommandCacheService(cache, 60, 10);
        AtomicInteger loaderCalls = new AtomicInteger();
        CommandCacheService.CommandLoader loader = new CommandCacheService.CommandLoader() {
            @Override
            public String load(String commandId) {
                loaderCalls.incrementAndGet();
                return "preview-" + loaderCalls.get();
            }
        };
        service.get("cmd-002", loader);

        // Act：业务写入成功后主动删除缓存，再查询一次。
        service.evict("cmd-002");
        String result = service.get("cmd-002", loader);

        // Assert：删除成功，第二次查询重新访问数据源并拿到新结果。
        assertEquals("preview-2", result);
        assertEquals(2, loaderCalls.get());
    }

    /** 离线测试用的最小缓存实现，不依赖 Redis 服务。 */
    private static class InMemoryCacheClient implements CommandCacheClient {
        private final Map<String, String> values = new HashMap<String, String>();

        @Override
        public String get(String key) {
            return values.get(key);
        }

        @Override
        public void set(String key, String value, long ttlSeconds) {
            values.put(key, value);
        }

        @Override
        public void delete(String key) {
            values.remove(key);
        }
    }
}
