package learn.agent.redis;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;

import java.util.Collections;

/**
 * 负责命令状态的业务更新。
 *
 * <p>更新时必须同时检查旧状态和写入新状态。本课用 Lua 让“检查 + 更新”
 * 在 Redis 中一次完成，避免 Java 代码的先查再改被并发请求插队。</p>
 */
public class SpringRedisCommandStateService {
    private static final DefaultRedisScript<Long> UPDATE_STATUS_SCRIPT =
            new DefaultRedisScript<Long>(
                    "local current = redis.call('HGET', KEYS[1], 'status') "
                            + "if current == ARGV[1] then "
                            + "redis.call('HSET', KEYS[1], 'status', ARGV[2], 'result', ARGV[3]) "
                            + "return 1 "
                            + "end "
                            + "return 0",
                    Long.class);

    private final StringRedisTemplate redisTemplate;

    public SpringRedisCommandStateService(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    /**
     * 只有当前状态等于 expectedStatus 时，才更新为 targetStatus。
     *
     * @return true 表示更新成功，false 表示状态已被其他请求改变或 key 不存在
     */
    public boolean updateStatus(String commandId, String expectedStatus,
                                String targetStatus, String result) {
        String key = "agent:command:state:" + commandId;
        Long updated = redisTemplate.execute(
                UPDATE_STATUS_SCRIPT,
                Collections.singletonList(key),
                expectedStatus,
                targetStatus,
                result == null ? "" : result
        );
        return Long.valueOf(1L).equals(updated);
    }
}
