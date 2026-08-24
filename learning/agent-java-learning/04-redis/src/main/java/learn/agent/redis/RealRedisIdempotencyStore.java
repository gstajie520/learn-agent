package learn.agent.redis;

import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisURI;
import io.lettuce.core.SetArgs;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;

/**
 * 使用真实 Redis 保存幂等抢占记录。
 *
 * <p>本类只负责 Redis 连接和命令，不决定业务是否重复；业务规则仍由
 * {@link IdempotencyService} 负责。连接使用完必须显式关闭。</p>
 */
public class RealRedisIdempotencyStore implements AutoCloseable {
    /** Lettuce 管理 Redis 客户端连接。 */
    private final RedisClient redisClient;
    /** 与 Redis 服务建立的连接。 */
    private final StatefulRedisConnection<String, String> connection;
    /** 同步命令接口，便于按顺序阅读 Redis 操作。 */
    private final RedisCommands<String, String> commands;

    /** 连接本机 Redis 默认端口 6379。 */
    public RealRedisIdempotencyStore() {
        this("127.0.0.1", 6379, System.getenv("REDIS_PASSWORD"));
    }

    /**
     * @param host Redis 主机
     * @param port Redis 端口
     */
    public RealRedisIdempotencyStore(String host, int port, String password) {
        RedisURI.Builder redisUriBuilder = RedisURI.Builder.redis(host, port);

        // 密码只能从运行环境传入，不能硬编码到源码或提交到 Git。
        if (password != null && !password.trim().isEmpty()) {
            redisUriBuilder.withPassword(password.toCharArray());
        }

        RedisURI redisUri = redisUriBuilder.build();
        this.redisClient = RedisClient.create(redisUri);
        this.connection = redisClient.connect();
        this.commands = connection.sync();
    }

    /** 执行 Redis SET key value NX EX seconds。 */
    public boolean setIfAbsent(String key, String value, long ttlSeconds) {
        if (ttlSeconds <= 0) {
            throw new IllegalArgumentException("ttlSeconds 必须大于 0");
        }
        String result = commands.set(key, value, SetArgs.Builder.nx().ex(ttlSeconds));
        return "OK".equals(result);
    }

    /** 读取 Redis 中的幂等状态。 */
    public String get(String key) {
        return commands.get(key);
    }

    /** 删除测试 key 或明确需要释放的幂等记录。 */
    public void delete(String key) {
        commands.del(key);
    }

    /** 读取 key 剩余 TTL，单位为秒。 */
    public long ttl(String key) {
        return commands.ttl(key);
    }

    /** 先关闭连接，再关闭 Redis 客户端。 */
    @Override
    public void close() {
        connection.close();
        redisClient.shutdown();
    }
}
