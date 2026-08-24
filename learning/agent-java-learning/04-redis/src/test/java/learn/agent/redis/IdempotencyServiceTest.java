package learn.agent.redis;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/** 命令幂等服务的业务测试。 */
public class IdempotencyServiceTest {

    /** 验证重复 MQ 消息不会再次获得命令执行权。 */
    @Test
    public void shouldRejectDuplicateCommand() {
        // Arrange：两个消费者共享同一个 Redis 存储。
        RedisLikeStore sharedStore = new RedisLikeStore();
        IdempotencyService consumerA = new IdempotencyService(sharedStore);
        IdempotencyService consumerB = new IdempotencyService(sharedStore);

        // Act：两个消费者先后处理同一个 commandId。
        ClaimResult resultA = consumerA.claim("cmd-003");
        ClaimResult resultB = consumerB.claim("cmd-003");

        // Assert：只有第一个消费者抢占成功，第二个识别为重复消息。
        assertEquals(ClaimResult.CLAIMED, resultA);
        assertEquals(ClaimResult.ALREADY_CLAIMED, resultB);
    }

    /** 验证空 commandId 不会生成错误的共享幂等 key。 */
    @Test
    public void shouldRejectBlankCommandId() {
        // Arrange：创建幂等服务。
        IdempotencyService service = new IdempotencyService(new RedisLikeStore());

        // Act + Assert：空 commandId 必须在访问存储前被拒绝。
        IllegalArgumentException exception = assertThrows(
                IllegalArgumentException.class,
                () -> service.claim("   ")
        );
        assertEquals("commandId 不能为空", exception.getMessage());
    }
}
