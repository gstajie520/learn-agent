package learn.agent.redis.lesson04;

import learn.agent.redis.lesson03.RedisCommandState;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;

import java.util.Collections;
import java.util.Map;

/**
 * 使用 StringRedisTemplate 保存和读取命令状态。
 *
 * <p>这个类只处理 Redis 数据结构，不决定业务状态是否允许流转。</p>
 */
public class SpringRedisCommandStateStore {
    private static final long STATE_TTL_SECONDS = 24 * 60 * 60;
    private static final DefaultRedisScript<Long> SAVE_STATE_SCRIPT =
            new DefaultRedisScript<Long>(
                    "redis.call('HSET', KEYS[1], "
                            + "'commandId', ARGV[1], "
                            + "'instruction', ARGV[2], "
                            + "'status', ARGV[3], "
                            + "'result', ARGV[4]) "
                            + "redis.call('EXPIRE', KEYS[1], ARGV[5]) "
                            + "return 1",
                    Long.class);

    private final StringRedisTemplate redisTemplate;

    public SpringRedisCommandStateStore(StringRedisTemplate redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

    /** 把命令四个字段保存为 Hash，并设置过期时间。 */
    public void save(RedisCommandState state) {
        validateState(state);
        String key = keyOf(state.getCommandId());

        // Lua 让写 Hash 和设置 TTL 在 Redis 内一次完成，避免只写入但没有过期时间。
        redisTemplate.execute(
                SAVE_STATE_SCRIPT,
                Collections.singletonList(key),
                state.getCommandId(),
                state.getInstruction(),
                state.getStatus(),
                state.getResult() == null ? "" : state.getResult(),
                String.valueOf(STATE_TTL_SECONDS)
        );
    }

    /** 根据 commandId 查询状态；不存在时返回 null。 */
    public RedisCommandState find(String commandId) {
        Map<Object, Object> fields = redisTemplate.opsForHash().entries(keyOf(commandId));
        if (fields == null || fields.isEmpty()) {
            return null;
        }
        return new RedisCommandState(
                valueOf(fields.get("commandId")),
                valueOf(fields.get("instruction")),
                valueOf(fields.get("status")),
                valueOf(fields.get("result"))
        );
    }

    /** 删除测试数据或已经不需要的短期状态。 */
    public void delete(String commandId) {
        redisTemplate.delete(keyOf(commandId));
    }

    private String keyOf(String commandId) {
        if (commandId == null || commandId.trim().isEmpty()) {
            throw new IllegalArgumentException("commandId 不能为空");
        }
        return "agent:command:state:" + commandId;
    }

    private String valueOf(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private void validateState(RedisCommandState state) {
        if (state == null) {
            throw new IllegalArgumentException("state 不能为空");
        }
        keyOf(state.getCommandId());
        if (state.getInstruction() == null || state.getInstruction().trim().isEmpty()) {
            throw new IllegalArgumentException("instruction 不能为空");
        }
        if (state.getStatus() == null || state.getStatus().trim().isEmpty()) {
            throw new IllegalArgumentException("status 不能为空");
        }
    }
}
