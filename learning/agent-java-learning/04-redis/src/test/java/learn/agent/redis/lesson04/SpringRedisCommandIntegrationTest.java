package learn.agent.redis.lesson04;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import learn.agent.redis.lesson03.RedisCommandState;

import java.net.Socket;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 使用 Spring 容器和真实 Redis 验证条件状态更新。 */
public class SpringRedisCommandIntegrationTest {

    @Test
    public void shouldUpdateRealRedisStateOnlyOnce() {
        // Arrange：真实 Redis 或密码不可用时跳过，离线规则测试仍然执行。
        Assumptions.assumeTrue(isRedisPortAvailable(), "Redis 端口不可用，跳过 Spring Redis 集成测试");
        String password = System.getenv("REDIS_PASSWORD");
        Assumptions.assumeTrue(
                password != null && !password.trim().isEmpty(),
                "REDIS_PASSWORD 未设置，跳过 Spring Redis 集成测试"
        );

        AnnotationConfigApplicationContext context =
                new AnnotationConfigApplicationContext(SpringRedisConfig.class);
        String commandId = "cmd-spring-test-" + UUID.randomUUID();
        try {
            SpringRedisCommandStateStore store = context.getBean(SpringRedisCommandStateStore.class);
            SpringRedisCommandStateService service = context.getBean(SpringRedisCommandStateService.class);
            store.save(new RedisCommandState(commandId, "生成预览", "PENDING", ""));

            // Act：相同的 PENDING -> RUNNING 连续执行两次。
            boolean firstUpdate = service.updateStatus(commandId, "PENDING", "RUNNING", "");
            boolean secondUpdate = service.updateStatus(commandId, "PENDING", "RUNNING", "");

            // Assert：第一次成功，第二次因为旧状态不匹配而失败。
            assertTrue(firstUpdate);
            assertFalse(secondUpdate);
            store.delete(commandId);
        } finally {
            // 即使断言失败也关闭 Spring 容器，释放 Redis 连接。
            context.close();
        }
    }

    private boolean isRedisPortAvailable() {
        try (Socket socket = new Socket("127.0.0.1", 6379)) {
            return true;
        } catch (Exception exception) {
            return false;
        }
    }
}
