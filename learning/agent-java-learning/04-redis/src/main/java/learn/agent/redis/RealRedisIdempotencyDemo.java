package learn.agent.redis;

/** 真实 Redis 幂等教学入口。运行前请确认 127.0.0.1:6379 有 Redis 服务。 */
public class RealRedisIdempotencyDemo {

    public static void main(String[] args) {
        String key = "agent:learning:real-redis:cmd-001";

        try (RealRedisIdempotencyStore store = new RealRedisIdempotencyStore()) {
            // 清理上一次示例留下的 key，保证每次运行都从第一次抢占开始。
            store.delete(key);

            // 第一次 SET NX 成功，表示当前消费者抢到执行权。
            boolean firstClaim = store.setIfAbsent(key, "PROCESSING", 60);

            // 第二次 SET NX 失败，表示这是重复消息。
            boolean secondClaim = store.setIfAbsent(key, "PROCESSING", 60);

            System.out.println("第一次抢占：" + firstClaim);
            System.out.println("第二次抢占：" + secondClaim);
            System.out.println("Redis 中的状态：" + store.get(key));
            System.out.println("剩余 TTL（秒）：" + store.ttl(key));
        }
    }
}
