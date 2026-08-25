package learn.agent.redis.lesson03;

/** 演示把阶段 3 的命令对象保存到真实 Redis Hash。 */
public class RedisCommandStateDemo {

    public static void main(String[] args) {
        String commandId = "cmd-state-demo-001";
        try (RedisCommandStateStore store = new RedisCommandStateStore()) {
            // 模拟 Java 接收到请求后，先保存 PENDING 状态。
            store.save(new RedisCommandState(
                    commandId,
                    "把机场场景生成预览",
                    "PENDING",
                    ""
            ));

            // 再从 Redis 读取，而不是从当前 JVM 的 Map 读取。
            RedisCommandState state = store.find(commandId);
            System.out.println("commandId：" + state.getCommandId());
            System.out.println("status：" + state.getStatus());
            System.out.println("instruction：" + state.getInstruction());
            System.out.println("TTL（秒）：" + store.ttl(commandId));

            store.delete(commandId);
        }
    }
}
