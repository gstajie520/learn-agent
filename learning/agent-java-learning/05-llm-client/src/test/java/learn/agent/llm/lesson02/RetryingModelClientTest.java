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

    /**
     * 规则：可重试错误（限流）应当自动重试，并在每次失败后等待一次。
     *
     * <p><b>为什么重要：</b>限流是模型调用最常见的暂时性故障。调用方写一行
     * {@code client.chat(request)}，不应该自己去数「这是第几次失败、该等多久」。
     * 重试是横切逻辑，包在客户端里，业务代码不需要知道它存在。</p>
     *
     * <p><b>违反会怎样：</b>如果不重试，一次偶发 429 就变成用户可见的失败；
     * 如果每层都自己写重试，三层嵌套会把 3 次放大成 27 次请求。</p>
     *
     * <p>断言 {@code sleeper.delays.size() == 2}：失败两次等两次，
     * 成功那次之后不再等待。</p>
     */
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

    /**
     * 规则：不可重试错误（密钥无效）必须立即抛出，而且<b>一次都不等待</b>。
     *
     * <p><b>为什么重要：</b>这条测试真正验证的是「等待次数为 0」，
     * 而不只是「只请求了一次」。两者是不同的 bug ——
     * 有种常见写法是先 sleep 再判断能不能重试，结果虽然没有重试，
     * 用户却白等了一次退避时间。</p>
     *
     * <p><b>违反会怎样：</b>密钥配错时，本该毫秒级返回的失败变成等好几秒才失败。
     * 排查阶段每改一次配置都要多等几秒，而且这种延迟在日志里看不出原因。</p>
     */
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

    /**
     * 规则：请求 N 次只等待 N-1 次，最后一次失败后不再等待。
     *
     * <p><b>为什么重要：</b>这是个差一错误（off-by-one）的典型位置。
     * 循环里习惯性地「失败就 sleep」，会在最后一次失败后也睡一觉，
     * 然后才发现次数用尽、抛出异常。</p>
     *
     * <p><b>违反会怎样：</b>每个最终失败的请求都白等一次最长退避时间。
     * 按本课配置（上限 8 秒），意味着每个失败请求多占用一个线程 8 秒 ——
     * 故障期间请求量大时，这足以拖垮线程池。</p>
     *
     * <p>断言是 3 次请求对 2 次等待，这个 1 的差值就是全部意义。</p>
     */
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

    /**
     * 规则：退避时长按 2 的幂次增长（500 → 1000 → 2000 → 4000），到上限后不再增长。
     *
     * <p><b>为什么重要：</b>指数增长的含义是「越失败越谦让」。
     * 服务端返回 429 是在说「你太快了」，固定间隔重试等于没听懂这句话。
     * 封顶则保证等待不会失控 —— 没有上限时第 10 次会等 500×2⁹ ≈ 4 分钟，
     * 用户早就关掉页面了。</p>
     *
     * <p><b>违反会怎样：</b>没有指数增长，限流会持续；没有上限，
     * 请求会挂在那里几分钟，占着线程且无法解释。</p>
     *
     * <p><b>为什么断言的是区间而不是精确值：</b>退避带随机抖动，
     * 抖动系数落在 [0.5, 1.0)，所以实际值落在 [理论值/2, 理论值)。
     * 断言精确值会让这个测试随机失败（flaky），而 flaky 测试比没有测试更糟 ——
     * 它会训练人忽略红色。这里直接测 {@code computeDelay()} 而不发请求，
     * 因为要验证的是计算规则本身。</p>
     */
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
     * 规则：同一轮次反复计算，退避时长不应每次都相同（必须带抖动）。
     *
     * <p><b>为什么重要：</b>这是分布式系统里的惊群效应（thundering herd）。
     * 假设 100 个实例在同一秒被限流，如果退避是固定的 500ms，
     * 它们会在 500ms 后<b>同时</b>重试，形成一个比原来更高的请求尖峰，
     * 于是再次被限流、再次同时重试。偶发限流就这样变成持续故障。</p>
     *
     * <p><b>违反会怎样：</b>重试机制本身成为故障放大器。
     * 这类问题在单机测试中完全看不出来，只在生产的多实例环境爆发。</p>
     *
     * <p><b>为什么这样测：</b>随机性无法断言具体值，只能断言「不是固定值」。
     * 采样 20 次，只要出现一个不同值就说明抖动生效。
     * 这里刻意用无种子的 {@code new Random()}，因为要验证的正是随机行为本身。</p>
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
     * 规则：重试用尽后抛出的异常，必须保留<b>原始</b>错误分类和原始错误信息。
     *
     * <p><b>为什么重要：</b>包装层很容易把底层错误吃掉，换成一个笼统的
     * 「重试 2 次后失败」。那样监控只能看到「重试失败」总数，
     * 无法区分是限流、是服务端 5xx，还是网络超时 —— 这三者的处理动作完全不同。</p>
     *
     * <p><b>违反会怎样：</b>告警失去分类能力。限流意味着要降低发送速率或加配额，
     * 5xx 意味着要找服务商，两者被混成一个指标后，值班的人无法判断该做什么。</p>
     *
     * <p>断言里同时检查异常消息含有原始文本和尝试次数：
     * 排查时「试了几次」和「最后为什么失败」都需要。</p>
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
     * 规则：{@code maxAttempts=1} 表示「只尝试一次、不重试」，即使错误可重试也不重试。
     *
     * <p><b>为什么重要：</b>重试是用<b>延迟</b>换<b>成功率</b>，这笔交易并非总是划算。
     * 用户正在等待的在线请求，宁可快速失败让前端提示「稍后再试」，
     * 也不要卡住十几秒；后台批处理任务才适合多次重试。
     * 所以重试次数必须可配，而不是写死。</p>
     *
     * <p><b>违反会怎样：</b>如果实现里写成「至少重试一次」，
     * 对延迟敏感的接口就无法关闭重试，只能被迫接受最坏情况的响应时间。</p>
     *
     * <p>这里同时断言 {@code sleeper} 没被调用：不重试就不该有任何等待。</p>
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
     * 规则：非法的重试配置必须在<b>构造时</b>就拒绝，不能等到真出错要重试时才发现。
     *
     * <p><b>为什么重要：</b>重试配置的特点是<b>平时用不到</b> ——
     * 只有模型服务出故障时才会走到退避逻辑。如果配置错误要等到那一刻才暴露，
     * 等于在故障现场再叠一个 bug，而这正是最不能出问题的时候。</p>
     *
     * <p><b>违反会怎样：</b>{@code maxAttempts=0} 会让请求一次都不发；
     * {@code baseDelay=0} 会退化成不等待的密集重试，把限流打成雪崩。
     * 这些都在构造时一眼可判，没有理由留到运行期。</p>
     *
     * <p>最后一条检查「上限 &lt; 基础值」：这是配置自相矛盾，
     * 说明写配置的人理解有误，应当直接报错而不是默默取较小值。</p>
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
     * 规则：第一次就成功的请求，必须原样透传，且<b>不产生任何额外延迟</b>。
     *
     * <p><b>为什么重要：</b>绝大多数请求是一次成功的。给包装层加重试后，
     * 最需要保证的恰恰是这条「什么都没发生」的正常路径没被拖慢。</p>
     *
     * <p><b>违反会怎样：</b>如果实现不小心在每次调用前先等一下（例如把等待
     * 写在循环开头而不是失败之后），那么<b>全部</b>请求都会凭空多出几百毫秒。
     * 这种问题在功能测试里看不出来，只会表现为「接口莫名变慢」。</p>
     *
     * <p>断言 {@code sleeper.delays} 为空，就是在守住这条底线。</p>
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
