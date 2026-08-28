package learn.agent.llm.lesson02;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatResponse;
import learn.agent.llm.lesson01.FakeModelClient;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.ModelException;
import learn.agent.llm.lesson01.TokenUsage;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 退避重试的测试。
 *
 * <p>测试目标：证明重试<b>等了多久</b>是对的，而不只是最终结果对。
 * 这是通过注入 {@link Sleeper} 实现的 —— 测试用的实现只记录时长、
 * 不真正睡眠，所以断言「第一次等约 500ms、第二次等约 1000ms」
 * 依然是毫秒级完成。</p>
 *
 * <p>如果直接用 {@code Thread.sleep()}，这几个测试要跑好几秒。
 * 测试一慢就没人跑，没人跑的测试等于不存在。</p>
 *
 * <p>覆盖的规则：</p>
 * <ul>
 *   <li>可重试错误按指数退避重试；</li>
 *   <li>不可重试错误立即抛出，且<b>完全不等待</b>；</li>
 *   <li>退避时长指数增长并封顶；</li>
 *   <li>抖动让等待时间落在区间内而非固定值；</li>
 *   <li>最后一次失败后不再无谓等待。</li>
 * </ul>
 */
public class RetryingModelClientTest {

    /** 限流这类可重试错误自动重试、每次失败后等一次：不重试则一次偶发 429 就成了用户可见的失败，而每层各写一遍重试，三层嵌套会把 3 次放大成 27 次请求。 */
    @Test
    public void shouldRetryRetryableErrorAndSucceed() {
        // Arrange：前两次限流，第三次成功。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "429 第一次");
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "429 第二次");
        fake.enqueueResponse("南侧新增一道围栏。", FinishReason.STOP, new TokenUsage(90, 12));

        RecordingSleeper sleeper = new RecordingSleeper();
        RetryingModelClient client = new RetryingModelClient(
                fake, 3, 500, 8000, sleeper, new Random(1));

        // Act：调用方只调一次。
        ChatResponse response = client.chat(request());

        // Assert：最终成功，实际发了三次请求。
        assertEquals("南侧新增一道围栏。", response.getContent());
        assertEquals(3, fake.getCallCount());

        // Assert：失败两次就等待两次，成功后不再等待。
        assertEquals(2, sleeper.delays.size());
    }

    /** 不可重试错误立即抛出且等待次数为 0（不只是「只请求一次」）：先 sleep 再判断能否重试的写法虽然没重试，却让密钥配错这种毫秒级可知的失败白等一轮退避，延迟在日志里还看不出原因。 */
    @Test
    public void shouldNotSleepAtAllForNonRetryableError() {
        // Arrange：密钥错误。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");

        RecordingSleeper sleeper = new RecordingSleeper();
        RetryingModelClient client = new RetryingModelClient(
                fake, 5, 500, 8000, sleeper, new Random(1));

        // Act：应当立即失败。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> client.chat(request())
        );

        // Assert：只请求一次。
        assertEquals(ModelException.ErrorType.AUTHENTICATION, exception.getErrorType());
        assertEquals(1, fake.getCallCount());

        // Assert：一次都没等待。这一条很关键 ——
        // 对着必然失败的请求做退避等待，只是让用户白等几秒。
        assertEquals(0, sleeper.delays.size());
    }

    /** 请求 N 次只等待 N-1 次：循环里习惯性「失败就 sleep」会在次数用尽前多睡一觉，每个最终失败的请求白占一个线程满一轮上限（本课 8 秒），故障期间足以拖垮线程池。 */
    @Test
    public void shouldNotSleepAfterFinalAttempt() {
        // Arrange：一直 5xx，最多尝试 3 次。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.SERVER_ERROR, "502");
        fake.enqueueError(ModelException.ErrorType.SERVER_ERROR, "502");
        fake.enqueueError(ModelException.ErrorType.SERVER_ERROR, "502");

        RecordingSleeper sleeper = new RecordingSleeper();
        RetryingModelClient client = new RetryingModelClient(
                fake, 3, 500, 8000, sleeper, new Random(1));

        // Act：重试用尽后失败。
        assertThrows(ModelException.class, () -> client.chat(request()));

        // Assert：请求 3 次，但只等待 2 次。
        // 最后一次失败后已经不会再尝试了，再等待纯属浪费用户的时间。
        assertEquals(3, fake.getCallCount());
        assertEquals(2, sleeper.delays.size());
    }

    /** 退避按 2 的幂次增长（500 → 1000 → 2000 → 4000）并封顶：固定间隔等于没听懂 429 那句「你太快了」，限流会持续；不封顶第 10 次要等 500×2⁹ ≈ 4 分钟，请求挂着占线程还无法解释。断言区间而非精确值是因为抖动系数落在 [0.5, 1.0)，钉死数值会让测试变 flaky。 */
    @Test
    public void shouldGrowDelayExponentiallyAndCapIt() {
        // Arrange：base=500ms，上限 4000ms。用固定种子让抖动可预测。
        RetryingModelClient client = new RetryingModelClient(
                new FakeModelClient(), 10, 500, 4000, new RecordingSleeper(), new Random(7));

        // Act + Assert：抖动系数在 [0.5, 1.0)，所以每次退避落在
        // [理论值/2, 理论值) 区间内。
        assertDelayInRange(client.computeDelay(1), 500);
        assertDelayInRange(client.computeDelay(2), 1000);
        assertDelayInRange(client.computeDelay(3), 2000);
        assertDelayInRange(client.computeDelay(4), 4000);

        // Assert：到上限后不再增长，否则第 10 次会等好几分钟。
        assertDelayInRange(client.computeDelay(5), 4000);
        assertDelayInRange(client.computeDelay(10), 4000);
    }

    /**
     * 同一轮次的退避不能是固定值（必须带抖动）：固定 500ms 会让同时被限流的上百个实例在同一刻一起重试，
     * 形成比原来更高的尖峰，重试机制自己变成故障放大器，而这在单机测试里完全看不出来。
     */
    @Test
    public void shouldApplyJitterSoDelaysAreNotIdentical() {
        // Arrange：同一个 attempt 反复计算多次。
        RetryingModelClient client = new RetryingModelClient(
                new FakeModelClient(), 5, 1000, 8000, new RecordingSleeper(), new Random());

        // Act：收集 20 次同一轮次的退避时长。
        boolean foundDifferent = false;
        long first = client.computeDelay(3);
        for (int i = 0; i < 20; i++) {
            if (client.computeDelay(3) != first) {
                foundDifferent = true;
                break;
            }
        }

        // Assert：结果不应该每次都一样。
        // 固定退避时，同时被限流的多个客户端会在同一时刻一起重试，
        // 形成新的请求尖峰（惊群），把偶发限流变成持续故障。
        assertTrue(foundDifferent, "退避时长应当带抖动，不应是固定值");
    }

    /**
     * 重试用尽后抛出的异常要保留原始分类和原始信息：包装成笼统的「重试 2 次后失败」后，
     * 监控就分不清限流、5xx 和超时，而这三者的处置动作完全不同，值班的人无从判断该加配额还是找服务商。
     */
    @Test
    public void shouldPreserveErrorTypeAfterExhaustingRetries() {
        // Arrange：一直限流。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "429 一直限流");
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "429 一直限流");

        RetryingModelClient client = new RetryingModelClient(
                fake, 2, 100, 1000, new RecordingSleeper(), new Random(1));

        // Act：重试用尽。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> client.chat(request())
        );

        // Assert：保留原始分类和原始信息，便于监控按错误类型聚合。
        assertEquals(ModelException.ErrorType.RATE_LIMIT, exception.getErrorType());
        assertTrue(exception.getMessage().contains("429 一直限流"));
        assertTrue(exception.getMessage().contains("2"));
    }

    /**
     * {@code maxAttempts=1} 就是一次都不重试，哪怕错误可重试：重试是拿延迟换成功率，
     * 实现里写成「至少重试一次」的话，对延迟敏感的在线接口就没法关掉它，只能被迫接受最坏响应时间。
     */
    @Test
    public void shouldNotRetryWhenMaxAttemptsIsOne() {
        // Arrange：maxAttempts=1 表示不重试，常用于对延迟敏感的在线请求。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "429");

        RecordingSleeper sleeper = new RecordingSleeper();
        RetryingModelClient client = new RetryingModelClient(
                fake, 1, 500, 8000, sleeper, new Random(1));

        // Act + Assert：即使错误可重试，也只尝试一次、不等待。
        assertThrows(ModelException.class, () -> client.chat(request()));
        assertEquals(1, fake.getCallCount());
        assertEquals(0, sleeper.delays.size());
    }

    /**
     * 非法重试配置在构造时就拒绝：退避逻辑平时走不到，留到运行期暴露等于在故障现场再叠一个 bug，
     * 而 {@code maxAttempts=0} 一次都不发、{@code baseDelay=0} 退化成密集重试把限流打成雪崩，都在构造时一眼可判。
     */
    @Test
    public void shouldRejectInvalidConfiguration() {
        FakeModelClient fake = new FakeModelClient();

        // Act + Assert：配置错误在构造时就要暴露。
        assertThrows(
                IllegalArgumentException.class,
                () -> new RetryingModelClient(null, 3, 500, 8000)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new RetryingModelClient(fake, 0, 500, 8000)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new RetryingModelClient(fake, 3, 0, 8000)
        );
        // 上限小于基础值属于配置矛盾。
        assertThrows(
                IllegalArgumentException.class,
                () -> new RetryingModelClient(fake, 3, 5000, 1000)
        );
    }

    /**
     * 一次就成功的请求原样透传、零额外延迟：把等待写在循环开头而不是失败之后，
     * 全部请求都会凭空多出几百毫秒，功能测试全绿，只表现为「接口莫名变慢」。
     */
    @Test
    public void shouldPassThroughSuccessWithoutSleeping() {
        // Arrange：第一次就成功。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("一次就成功。", FinishReason.STOP, new TokenUsage(10, 5));

        RecordingSleeper sleeper = new RecordingSleeper();
        RetryingModelClient client = new RetryingModelClient(
                fake, 3, 500, 8000, sleeper, new Random(1));

        // Act：正常调用。
        ChatResponse response = client.chat(request());

        // Assert：成功路径不该有任何额外延迟。
        assertEquals("一次就成功。", response.getContent());
        assertEquals(1, fake.getCallCount());
        assertEquals(0, sleeper.delays.size());
    }

    /** 断言退避时长落在 [理论值/2, 理论值) 区间内。 */
    private void assertDelayInRange(long actual, long expectedBase) {
        long lowerBound = expectedBase / 2;
        assertTrue(actual >= lowerBound && actual <= expectedBase,
                "退避时长 " + actual + "ms 应落在 [" + lowerBound + ", " + expectedBase + "] 区间内");
    }

    private ChatRequest request() {
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.user("在南侧加一道围栏。"));
        return new ChatRequest("deepseek-v4-flash", messages, 0.2, 200);
    }

    /** 只记录时长、不真正睡眠的测试替身，让退避测试保持毫秒级。 */
    private static class RecordingSleeper implements Sleeper {
        private final List<Long> delays = new ArrayList<Long>();

        @Override
        public void sleep(long millis) {
            delays.add(millis);
        }
    }
}
