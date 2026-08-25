package learn.agent.redis;

import org.springframework.context.annotation.AnnotationConfigApplicationContext;

/** 演示 Spring 管理 Redis 连接，以及条件状态更新。 */
public class SpringRedisCommandDemo {

    public static void main(String[] args) {
        AnnotationConfigApplicationContext context =
                new AnnotationConfigApplicationContext(SpringRedisConfig.class);
        try {
            SpringRedisCommandStateStore store = context.getBean(SpringRedisCommandStateStore.class);
            SpringRedisCommandStateService service = context.getBean(SpringRedisCommandStateService.class);

            String commandId = "cmd-spring-demo-001";
            store.save(new RedisCommandState(commandId, "生成场景预览", "PENDING", ""));
            System.out.println("保存初始状态：PENDING");

            boolean firstUpdate = service.updateStatus(commandId, "PENDING", "RUNNING", "");
            System.out.println("第一次 PENDING -> RUNNING：" + firstUpdate);

            // 第二次仍然要求从 PENDING 开始，但当前已是 RUNNING，所以更新失败。
            boolean duplicateUpdate = service.updateStatus(commandId, "PENDING", "RUNNING", "");
            System.out.println("重复 PENDING -> RUNNING：" + duplicateUpdate);

            RedisCommandState state = store.find(commandId);
            System.out.println("Redis 当前状态：" + state.getStatus());
            store.delete(commandId);
        } finally {
            // 关闭 Spring 容器，容器会释放 Redis 连接。
            context.close();
        }
    }
}
