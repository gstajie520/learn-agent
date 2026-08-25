package learn.agent.redis.lesson05;

/**
 * 命令查询缓存的最小读写边界。
 *
 * <p>业务服务只依赖这三个动作，真实 Redis 和离线测试都可以提供自己的实现。</p>
 */
public interface CommandCacheClient {

    /** 读取缓存；key 不存在时返回 null。 */
    String get(String key);

    /** 写入缓存并设置 TTL。 */
    void set(String key, String value, long ttlSeconds);

    /** 删除指定缓存。 */
    void delete(String key);
}
