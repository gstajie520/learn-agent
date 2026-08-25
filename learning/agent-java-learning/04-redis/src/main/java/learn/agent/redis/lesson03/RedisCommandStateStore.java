package learn.agent.redis.lesson03;

import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.TransactionResult;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;

import java.util.HashMap;
import java.util.Map;

/**
 * 使用 Redis Hash 保存命令状态。
 *
 * <p>它对应阶段 3 中的 CommandRecord，但状态不再只存在一个 JVM 内存里。
 * Hash 保存多个字段，事务同时写字段和 TTL，避免保存过程只完成一半。</p>
 */
public class RedisCommandStateStore implements AutoCloseable {
    private static final long STATE_TTL_SECONDS = 24 * 60 * 60;

    private final RedisClient redisClient;
    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> commands;

    /** 使用 REDIS_PASSWORD 连接本机 Redis。 */
    public RedisCommandStateStore() {
        this("127.0.0.1", 6379, System.getenv("REDIS_PASSWORD"));
    }

    /** 使用指定 Redis 连接信息创建状态存储。 */
    public RedisCommandStateStore(String host, int port, String password) {
        RedisURI.Builder uriBuilder = RedisURI.Builder.redis(host, port);
        if (password != null && !password.trim().isEmpty()) {
            uriBuilder.withPassword(password.toCharArray());
        }
        this.redisClient = RedisClient.create(uriBuilder.build());
        this.connection = redisClient.connect();
        this.commands = connection.sync();
    }

    /**
     * 保存命令的完整状态，并设置 24 小时 TTL。
     */
    public void save(RedisCommandState state) {
        validateState(state);
        String key = keyOf(state.getCommandId());
        Map<String, String> fields = new HashMap<String, String>();
        fields.put("commandId", state.getCommandId());
        fields.put("instruction", state.getInstruction());
        fields.put("status", state.getStatus());
        fields.put("result", state.getResult() == null ? "" : state.getResult());

        // MULTI/EXEC 让写 Hash 和设置 TTL 一起提交，减少半成功状态。
        commands.multi();
        commands.del(key);
        commands.hset(key, fields);
        commands.expire(key, STATE_TTL_SECONDS);
        TransactionResult transactionResult = commands.exec();
        if (transactionResult == null) {
            throw new IllegalStateException("Redis 保存命令状态失败");
        }
    }

    /** 查询命令状态；Redis 中没有该 key 时返回 null。 */
    public RedisCommandState find(String commandId) {
        Map<String, String> fields = commands.hgetall(keyOf(commandId));
        if (fields == null || fields.isEmpty()) {
            return null;
        }
        return new RedisCommandState(
                fields.get("commandId"),
                fields.get("instruction"),
                fields.get("status"),
                fields.get("result")
        );
    }

    /** 删除命令状态，主要用于测试清理。 */
    public void delete(String commandId) {
        commands.del(keyOf(commandId));
    }

    /** 查询命令状态还剩多少秒过期。 */
    public long ttl(String commandId) {
        return commands.ttl(keyOf(commandId));
    }

    private String keyOf(String commandId) {
        if (commandId == null || commandId.trim().isEmpty()) {
            throw new IllegalArgumentException("commandId 不能为空");
        }
        return "agent:command:state:" + commandId;
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

    @Override
    public void close() {
        connection.close();
        redisClient.shutdown();
    }
}
