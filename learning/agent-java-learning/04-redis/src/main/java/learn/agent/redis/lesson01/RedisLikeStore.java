package learn.agent.redis.lesson01;

import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/**
 * 用 Java 模拟 Redis 的 SETNX + TTL 语义。
 *
 * <p>它不是 Redis 客户端，也不能跨 JVM 共享数据；它只是为了在没有 Redis
 * 服务时，先把“只有第一个消费者能成功写入”的原子规则看懂。</p>
 */
public class RedisLikeStore {
    /** 保存 key、value 和过期时间；只用于本课模拟，不能跨 JVM 共享。 */
    private final Map<String, ValueWithExpiry> values = new HashMap<String, ValueWithExpiry>();

    /**
     * 模拟 Redis SET key value NX EX seconds。
     *
     * @return true 表示 key 原来不存在，本次写入成功；false 表示 key 已存在
     */
    public synchronized boolean setIfAbsent(String key, String value, long ttlMillis) {
        if (ttlMillis <= 0) {
            throw new IllegalArgumentException("ttlMillis 必须大于 0");
        }
        removeExpiredValues();
        if (values.containsKey(key)) {
            return false;
        }
        values.put(key, new ValueWithExpiry(value, System.currentTimeMillis() + ttlMillis));
        return true;
    }

    /** 读取 key 当前值；key 不存在或已过期时返回 null。 */
    public synchronized String get(String key) {
        removeExpiredValues();
        ValueWithExpiry value = values.get(key);
        return value == null ? null : value.value;
    }

    /** 测试和故障恢复场景使用：删除幂等锁，允许命令重新被处理。 */
    public synchronized void delete(String key) {
        values.remove(key);
    }

    private void removeExpiredValues() {
        long now = System.currentTimeMillis();
        Iterator<Map.Entry<String, ValueWithExpiry>> iterator = values.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<String, ValueWithExpiry> entry = iterator.next();
            if (entry.getValue().expiresAtMillis <= now) {
                iterator.remove();
            }
        }
    }

    private static class ValueWithExpiry {
        /** Redis key 对应的字符串值，例如 PROCESSING。 */
        private final String value;

        /** 绝对过期时间，当前时间超过它时删除 key。 */
        private final long expiresAtMillis;

        private ValueWithExpiry(String value, long expiresAtMillis) {
            this.value = value;
            this.expiresAtMillis = expiresAtMillis;
        }
    }
}
