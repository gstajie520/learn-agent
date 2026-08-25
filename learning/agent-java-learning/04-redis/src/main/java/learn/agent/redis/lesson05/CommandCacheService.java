package learn.agent.redis.lesson05;

/**
 * 命令查询缓存服务。
 *
 * <p>流程是“先查缓存，未命中再查数据源，查到后写缓存”。
 * 空结果也短暂缓存，避免无效 commandId 持续打到数据库。</p>
 */
public class CommandCacheService {
    private static final String KEY_PREFIX = "agent:command:cache:";
    private static final String NULL_MARKER = "__CACHE_NULL__";

    private final CommandCacheClient cacheClient;
    private final long valueTtlSeconds;
    private final long nullTtlSeconds;

    public CommandCacheService(CommandCacheClient cacheClient,
                               long valueTtlSeconds,
                               long nullTtlSeconds) {
        if (cacheClient == null) {
            throw new IllegalArgumentException("cacheClient 不能为空");
        }
        if (valueTtlSeconds <= 0 || nullTtlSeconds <= 0) {
            throw new IllegalArgumentException("TTL 必须大于 0");
        }
        this.cacheClient = cacheClient;
        this.valueTtlSeconds = valueTtlSeconds;
        this.nullTtlSeconds = nullTtlSeconds;
    }

    /**
     * 查询命令结果。
     *
     * @param commandId 命令编号
     * @param loader 缓存未命中时访问数据库或其他数据源的动作
     * @return 命令结果；数据源也没有结果时返回 null
     */
    public String get(String commandId, CommandLoader loader) {
        validateCommandId(commandId);
        if (loader == null) {
            throw new IllegalArgumentException("loader 不能为空");
        }

        String key = keyOf(commandId);
        String cached = cacheClient.get(key);
        if (cached != null) {
            // NULL_MARKER 表示这个 commandId 确实不存在，避免穿透到数据源。
            return NULL_MARKER.equals(cached) ? null : cached;
        }

        /*
         * 这是单 JVM 的最小防击穿示例：同一个服务实例内只允许一个线程回源。
         * 多实例场景还需要 Redis 分布式锁或互斥 Lua，本课先不展开。
         */
        synchronized (this) {
            // 等待期间其他线程可能已经把结果写入缓存，所以必须再次检查。
            cached = cacheClient.get(key);
            if (cached != null) {
                return NULL_MARKER.equals(cached) ? null : cached;
            }

            String loaded = loader.load(commandId);
            if (loaded == null) {
                cacheClient.set(key, NULL_MARKER, nullTtlSeconds);
                return null;
            }

            cacheClient.set(key, loaded, valueTtlSeconds);
            return loaded;
        }
    }

    /** 删除缓存，写操作成功后调用，避免继续返回旧数据。 */
    public void evict(String commandId) {
        validateCommandId(commandId);
        cacheClient.delete(keyOf(commandId));
    }

    private String keyOf(String commandId) {
        return KEY_PREFIX + commandId;
    }

    private void validateCommandId(String commandId) {
        if (commandId == null || commandId.trim().isEmpty()) {
            throw new IllegalArgumentException("commandId 不能为空");
        }
    }

    /** 数据源回源动作，例如查询数据库或调用内部服务。 */
    public interface CommandLoader {
        String load(String commandId);
    }
}
