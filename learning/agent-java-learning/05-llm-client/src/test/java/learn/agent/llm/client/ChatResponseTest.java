package learn.agent.llm.client;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 响应契约与错误分类的测试。
 *
 * <p>测试目标：证明「响应能不能用」和「失败要不要重试」这两个判断
 * 都由对象自己回答，业务代码不需要解析文本去猜。</p>
 *
 * <p>覆盖的规则：</p>
 * <ul>
 *   <li>只有正常结束且有内容的响应才可用；</li>
 *   <li>被截断的响应即使有正文也不可用；</li>
 *   <li>缺少 Token 统计的响应不允许进入业务层；</li>
 *   <li>网关不返回 requestId 时统一记为 unknown，日志里不会出现 null；</li>
 *   <li>可重试与不可重试的错误分类正确。</li>
 * </ul>
 */
public class ChatResponseTest {

    /** 可用的充要条件是 {@code STOP} 且正文非空白：判断散落到每个调用点，总会有人只写 {@code if (content != null)} 就往下走，漏掉 finishReason 的那几处就是将来的线上故障点。 */
    @Test
    public void shouldBeUsableOnlyWhenStoppedNormally() {
        // Arrange：模型自然说完，正文非空。
        ChatResponse response = new ChatResponse(
                "北侧新增一台雷达。",
                FinishReason.STOP,
                new TokenUsage(100, 12),
                "req-001");

        // Act + Assert：这是唯一可以放心读 content 的情况。
        assertTrue(response.isUsable());
        assertEquals("北侧新增一台雷达。", response.getContent());
    }

    /** {@code LENGTH} 截断时不可用，哪怕正文读起来通顺：截断走的是 HTTP 200，没有异常也没有错误码，只有 finishReason 在告诉你话没说完，放过去就是脏数据静默入库。 */
    @Test
    public void shouldNotBeUsableWhenTruncated() {
        // Arrange：正文看起来像正常文本，但结束原因是达到输出上限。
        ChatResponse response = new ChatResponse(
                "北侧新增一台雷达，东南角部署",
                FinishReason.LENGTH,
                new TokenUsage(100, 200),
                "req-002");

        // Act + Assert：残句不可用。只看 content 长度是发现不了的，必须看 finishReason。
        assertFalse(response.isUsable());
    }

    /** 结束原因正常但正文全是空白同样不可用（判断用 {@code trim().isEmpty()}）：空串写进下游会被缓存和幂等标记当成「已处理过」而不再重算，捞出来重跑得专门写数据修复任务。 */
    @Test
    public void shouldNotBeUsableWhenContentIsBlank() {
        // Arrange：结束原因正常，但模型什么都没输出，这在真实服务里确实会发生。
        ChatResponse response = new ChatResponse(
                "   ",
                FinishReason.STOP,
                new TokenUsage(100, 0),
                "req-003");

        // Act + Assert：空白内容同样不可用，避免把空串当有效结果写进下游。
        assertFalse(response.isUsable());
    }

    /** {@code usage} 为 null 就拒绝构造，异常里点明字段名：默认给零会让缺失伪装成「这次没花钱」，月底账单和统计数字差一截，而那些调用的记录看着是完整的，只能拿服务方原始账单逐条比对。 */
    @Test
    public void shouldRejectResponseWithoutUsage() {
        // Arrange + Act + Assert：没有 Token 统计就无法核算成本，直接拒绝构造。
        IllegalArgumentException exception = assertThrows(
                IllegalArgumentException.class,
                () -> new ChatResponse("内容", FinishReason.STOP, null, "req-004")
        );
        assertTrue(exception.getMessage().contains("usage"));
    }

    /** {@code requestId} 缺失兜底成 {@code "unknown"}：第三方网关不返回这个头是常态，不该为一个日志字段把成功调用判死，留 null 又可能让排障字段反过来打挂主流程。 */
    @Test
    public void shouldFallBackToUnknownRequestId() {
        // Arrange：部分兼容网关不返回请求 id。
        ChatResponse response = new ChatResponse(
                "内容",
                FinishReason.STOP,
                new TokenUsage(10, 5),
                null);

        // Act + Assert：统一成 unknown，日志里不会出现 null，排查时也能看出是网关没给。
        assertEquals("unknown", response.getRequestId());
    }

    /** 限流、5xx、超时可重试，失败原因和请求内容无关：不重试的话，服务方一次滚动发布期间的零星 503 会原样报给用户，高峰期偶发 429 也等于白砍掉一块有效容量。 */
    @Test
    public void shouldClassifyRetryableErrors() {
        // Arrange + Act + Assert：等一会儿就可能成功的错误，标记为可重试。
        assertTrue(ModelException.ErrorType.RATE_LIMIT.isRetryable());
        assertTrue(ModelException.ErrorType.SERVER_ERROR.isRetryable());
        assertTrue(ModelException.ErrorType.TIMEOUT.isRetryable());
    }

    /** 参数越界、密钥无效、超窗口、被安全拦截都是确定性失败，标记为不可重试：重试只是为注定的错误反复付输入 Token 的钱，监控上还看着像「外部服务不稳定」。 */
    @Test
    public void shouldClassifyNonRetryableErrors() {
        // Arrange + Act + Assert：输入或配置本身就是错的，重试多少次结果都一样。
        assertFalse(ModelException.ErrorType.INVALID_REQUEST.isRetryable());
        assertFalse(ModelException.ErrorType.AUTHENTICATION.isRetryable());
        assertFalse(ModelException.ErrorType.CONTEXT_LENGTH_EXCEEDED.isRetryable());
        assertFalse(ModelException.ErrorType.CONTENT_FILTERED.isRetryable());
    }

    /** {@code catch} 接住的是异常不是枚举，所以 {@link ModelException} 自己就要能回答「要不要重试」：否则调用方退回到 {@code e.getMessage().contains("429")} 这种写法，等服务方改掉提示语，判断就静默失效、从此不再重试。 */
    @Test
    public void shouldExposeRetryableFlagOnException() {
        // Arrange：业务代码拿到的是异常对象，不是枚举。
        ModelException rateLimit = new ModelException(
                ModelException.ErrorType.RATE_LIMIT, "429 Too Many Requests");
        ModelException authFailure = new ModelException(
                ModelException.ErrorType.AUTHENTICATION, "API key 无效");

        // Act + Assert：异常自己就能回答「要不要重试」，调用方不必解析错误文本。
        assertTrue(rateLimit.isRetryable());
        assertFalse(authFailure.isRetryable());
    }

    /** {@link TokenUsage} 分别保留输入和输出、总数算出来而非存进来：两者单价不同，同样 138 个 Token 全是输入和全是输出差好几倍钱，只记总数就只知道「用量涨了」，却不知道该优化提示词、裁剪历史还是收紧输出上限。 */
    @Test
    public void shouldAccumulateTokensSeparately() {
        // Arrange：输入和输出单价不同，必须分开统计。
        TokenUsage usage = new TokenUsage(120, 18);

        // Act + Assert：总数只用于粗略判断是否接近上下文窗口，对账要看分项。
        assertEquals(120, usage.getPromptTokens());
        assertEquals(18, usage.getCompletionTokens());
        assertEquals(138, usage.getTotalTokens());
    }

    /** 负数 Token 拒绝构造 {@link TokenUsage}：负数表达的不是用量而是解析代码错了，放过去它会悄悄让成本统计越算越少，数字看着有、在增长、只是偏低，没有任何报警会响。 */
    @Test
    public void shouldRejectNegativeTokens() {
        // Arrange + Act + Assert：负数说明解析响应时出了错，不能静默接受。
        assertThrows(
                IllegalArgumentException.class,
                () -> new TokenUsage(-1, 10)
        );
    }
}
