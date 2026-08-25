package learn.agent.redis.lesson05;

import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import learn.agent.redis.lesson04.SpringRedisConfig;

/** 演示真实 Spring Redis 缓存的命中、空值缓存和主动删除。 */
public class CommandCacheDemo {

    public static void main(String[] args) {
        AnnotationConfigApplicationContext context =
                new AnnotationConfigApplicationContext(SpringRedisConfig.class);
        String commandId = "cmd-cache-demo-001";
        try {
            SpringRedisStringCacheClient client =
                    context.getBean(SpringRedisStringCacheClient.class);
            CommandCacheService cacheService = new CommandCacheService(client, 60, 10);

            // 用计数器模拟数据库调用，方便观察第二次查询是否命中缓存。
            final int[] databaseCalls = new int[]{0};
            CommandCacheService.CommandLoader loader = new CommandCacheService.CommandLoader() {
                @Override
                public String load(String id) {
                    databaseCalls[0]++;
                    return "scene preview for " + id;
                }
            };

            System.out.println("第一次查询：" + cacheService.get(commandId, loader));
            System.out.println("第二次查询：" + cacheService.get(commandId, loader));
            System.out.println("数据源调用次数：" + databaseCalls[0]);

            cacheService.evict(commandId);
            System.out.println("删除缓存后，下一次查询会重新访问数据源："
                    + cacheService.get(commandId, loader));
        } finally {
            // Spring 容器负责释放 Redis 连接。
            context.close();
        }
    }
}
