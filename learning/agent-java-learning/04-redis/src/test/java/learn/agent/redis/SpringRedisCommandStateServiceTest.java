package learn.agent.redis;

import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Spring Redis 条件更新的离线测试。
 *
 * <p>测试不连接真实 Redis。FakeRedisTemplate 只模拟本课用到的状态比较和更新，
 * 这样没有 Redis 密码时也能验证业务规则。</p>
 */
public class SpringRedisCommandStateServiceTest {

    @Test
    public void shouldUpdateWhenExpectedStatusMatches() {
        // Arrange：Redis 中当前状态是 PENDING。
        FakeRedisTemplate redisTemplate = new FakeRedisTemplate();
        redisTemplate.saveStatus("agent:command:state:cmd-001", "PENDING");
        SpringRedisCommandStateService service =
                new SpringRedisCommandStateService(redisTemplate);

        // Act：业务要求只有 PENDING 才能更新为 RUNNING。
        boolean updated = service.updateStatus("cmd-001", "PENDING", "RUNNING", "");

        // Assert：旧状态匹配，更新成功。
        assertTrue(updated);
        assertEquals("RUNNING", redisTemplate.findStatus("agent:command:state:cmd-001"));
    }

    @Test
    public void shouldRejectWhenExpectedStatusIsStale() {
        // Arrange：另一个消费者已经把状态更新成 RUNNING。
        FakeRedisTemplate redisTemplate = new FakeRedisTemplate();
        redisTemplate.saveStatus("agent:command:state:cmd-002", "RUNNING");
        SpringRedisCommandStateService service =
                new SpringRedisCommandStateService(redisTemplate);

        // Act：当前消费者仍然拿旧的 PENDING 状态来更新。
        boolean updated = service.updateStatus("cmd-002", "PENDING", "RUNNING", "");

        // Assert：旧状态不匹配，拒绝本次更新。
        assertFalse(updated);
        assertEquals("RUNNING", redisTemplate.findStatus("agent:command:state:cmd-002"));
    }

    /** 只模拟本课使用的 execute 方法，不模拟完整 Redis。 */
    private static class FakeRedisTemplate extends StringRedisTemplate {
        private final Map<String, String> statuses = new HashMap<String, String>();

        public void saveStatus(String key, String status) {
            statuses.put(key, status);
        }

        public String findStatus(String key) {
            return statuses.get(key);
        }

        @Override
        @SuppressWarnings("unchecked")
        public <T> T execute(RedisScript<T> script, List<String> keys, Object... args) {
            String key = keys.get(0);
            String expectedStatus = String.valueOf(args[0]);
            String targetStatus = String.valueOf(args[1]);
            String currentStatus = statuses.get(key);

            if (expectedStatus.equals(currentStatus)) {
                statuses.put(key, targetStatus);
                return (T) Long.valueOf(1L);
            }
            return (T) Long.valueOf(0L);
        }
    }
}
