package learn.agent.llm.client;


import java.util.Random;

/**
 * 带指数退避的重试包装。
 *
 * <p>这个类兑现了第 1 课的说法：重试是<b>横切逻辑</b>，可以做成包装实现，
 * 不用污染业务代码。它本身实现 {@link ModelClient}，内部又持有一个
 * {@code ModelClient}，所以可以套在任何实现外面：</p>
 *
 * <pre>{@code
 * ModelClient client = new RetryingModelClient(
 *         new HttpModelClient(settings), 3, 500, 8000);
 * // SceneSummaryService 完全不知道自己被包了一层重试
 * }</pre>
 *
 * <p><b>为什么第 1 课的立即重试不够用</b>：限流（429）意味着服务端已经
 * 处理不过来了。立刻重试只会让它更忙，多个客户端同时这样做还会形成
 * 同步的请求尖峰，把偶发限流变成持续故障。正确做法是每次失败后等待更久，
 * 并加入随机抖动把重试时间打散。</p>
 *
 * <p>退避序列（base=500ms，倍数 2）：500ms → 1000ms → 2000ms → 4000ms，
 * 到 {@code maxDelayMillis} 后不再增长。每次实际等待会再乘一个随机系数。</p>
 */
public class RetryingModelClient implements ModelClient {

    /** 被包装的真实客户端。 */
    private final ModelClient delegate;

    /** 最大尝试次数（含第一次）。 */
    private final int maxAttempts;

    /** 首次退避的基础时长，毫秒。 */
    private final long baseDelayMillis;

    /** 退避时长上限，避免指数增长到几分钟。 */
    private final long maxDelayMillis;

    private final Sleeper sleeper;

    /** 抖动用的随机源；测试可以注入固定种子让退避序列可预测。 */
    private final Random random;

    public RetryingModelClient(ModelClient delegate,
                               int maxAttempts,
                               long baseDelayMillis,
                               long maxDelayMillis) {
        this(delegate, maxAttempts, baseDelayMillis, maxDelayMillis, Sleeper.REAL, new Random());
    }

    public RetryingModelClient(ModelClient delegate,
                               int maxAttempts,
                               long baseDelayMillis,
                               long maxDelayMillis,
                               Sleeper sleeper,
                               Random random) {
        if (delegate == null) {
            throw new IllegalArgumentException("delegate 不能为空");
        }
        if (maxAttempts < 1) {
            throw new IllegalArgumentException("maxAttempts 至少为 1");
        }
        if (baseDelayMillis <= 0) {
            throw new IllegalArgumentException("baseDelayMillis 必须大于 0");
        }
        if (maxDelayMillis < baseDelayMillis) {
            throw new IllegalArgumentException("maxDelayMillis 不能小于 baseDelayMillis");
        }
        if (sleeper == null) {
            throw new IllegalArgumentException("sleeper 不能为空");
        }
        if (random == null) {
            throw new IllegalArgumentException("random 不能为空");
        }
        this.delegate = delegate;
        this.maxAttempts = maxAttempts;
        this.baseDelayMillis = baseDelayMillis;
        this.maxDelayMillis = maxDelayMillis;
        this.sleeper = sleeper;
        this.random = random;
    }

    @Override
    public ChatResponse chat(ChatRequest request) throws ModelException {
        ModelException lastError = null;

        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                return delegate.chat(request);
            } catch (ModelException e) {
                lastError = e;

                if (!e.isRetryable()) {
                    // 鉴权错、参数错、上下文超长：重试纯属浪费时间和钱。
                    throw e;
                }
                if (attempt == maxAttempts) {
                    // 最后一次尝试也失败了，不用再等，直接跳出去报错。
                    break;
                }
                waitBeforeRetry(attempt);
            }
        }

        throw new ModelException(
                lastError.getErrorType(),
                "重试 " + maxAttempts + " 次后仍然失败：" + lastError.getMessage(),
                lastError.getRequestId(),
                lastError);
    }

    /** 按指数退避加抖动等待一段时间。 */
    private void waitBeforeRetry(int attempt) {
        long delay = computeDelay(attempt);
        try {
            sleeper.sleep(delay);
        } catch (InterruptedException e) {
            // 必须恢复中断标志：吞掉它会让上层线程池无法正常关闭。
            Thread.currentThread().interrupt();
            throw new ModelException(
                    ModelException.ErrorType.TIMEOUT,
                    "重试等待被中断",
                    null,
                    e);
        }
    }

    /**
     * 计算第 n 次失败后应该等多久。
     *
     * <p>公式：{@code base * 2^(attempt-1)}，封顶到 {@code maxDelay}，
     * 再乘一个 [0.5, 1.0) 的随机系数做抖动。</p>
     *
     * <p>抖动这一步很容易被省掉，但它解决的是真实问题：如果 100 个客户端
     * 在同一秒被限流，没有抖动的话它们会在同一时刻同时重试，
     * 形成一个新的请求尖峰，服务端再次限流，如此循环。
     * 这个现象叫「惊群」，抖动把重试时间打散来避免它。</p>
     */
    long computeDelay(int attempt) {
        long delay = baseDelayMillis;
        for (int i = 1; i < attempt; i++) {
            delay = delay * 2;
            if (delay >= maxDelayMillis) {
                delay = maxDelayMillis;
                break;
            }
        }
        // 抖动系数落在 [0.5, 1.0)，所以实际等待是计算值的一半到全额之间。
        double jitterFactor = 0.5 + (random.nextDouble() * 0.5);
        long jittered = (long) (delay * jitterFactor);
        // 至少等 1 毫秒，避免抖动后变成 0 导致空转重试。
        return jittered < 1 ? 1 : jittered;
    }
}
