package learn.agent.redis;

/**
 * Redis 幂等入门的可运行教学入口。
 *
 * <p>场景：RabbitMQ 因为消费者 ACK 前宕机，重新投递了同一个 commandId。</p>
 */
public class RedisIdempotencyDemo {

    public static void main(String[] args) {
        RedisLikeStore store = new RedisLikeStore();
        IdempotencyService idempotencyService = new IdempotencyService(store);
        String commandId = "cmd-001";

        System.out.println("第一次消费消息：" + idempotencyService.claim(commandId));
        System.out.println("Redis 中记录的状态：" + idempotencyService.getClaimStatus(commandId));
        System.out.println("重复消费消息：" + idempotencyService.claim(commandId));
        System.out.println("结论：同一个 commandId 只有第一次消费可以继续执行");
    }
}
