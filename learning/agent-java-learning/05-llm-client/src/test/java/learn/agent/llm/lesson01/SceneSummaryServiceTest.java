package learn.agent.llm.lesson01;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 场景总结服务的行为测试。
 *
 * <p>测试目标不是验证模型答得好不好（那是模型的事，也无法稳定断言），
 * 而是验证<b>业务代码在模型各种返回下的处理规则</b>：</p>
 *
 * <ul>
 *   <li>请求组装：系统规则和用户输入是否分成两条独立消息；</li>
 *   <li>截断处理：{@code finishReason=LENGTH} 时是否拒绝而不是把残句当结果；</li>
 *   <li>重试策略：可重试错误是否重试，不可重试错误是否立即失败；</li>
 *   <li>成本统计：Token 是否累加，失败的那次是否也计入。</li>
 * </ul>
 *
 * <p>全部使用 {@link FakeModelClient}，不需要密钥、不需要网络，
 * 而且能精确构造出真实环境里很难复现的场景（例如"前两次限流、第三次成功"）。</p>
 */
public class SceneSummaryServiceTest {

    /** 系统规则和用户输入分成两条消息：拼成一段文本，用户写一句「忽略上面的指令」就拿到了系统级权限。 */
    @Test
    public void shouldSendSystemRuleAndUserInputAsSeparateMessages() {
        // Arrange：预设一次正常返回，重点不在返回值，而在"发出去的请求长什么样"。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("北侧新增一台雷达。", FinishReason.STOP, new TokenUsage(120, 18));
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：执行一次业务调用。
        String summary = service.summarize("在北侧生成一台雷达。");

        // Assert：业务拿到了干净的总结文本。
        assertEquals("北侧新增一台雷达。", summary);

        // Assert：请求里是两条消息，系统规则在前、用户输入在后，没有被拼成一段文本。
        ChatRequest sent = fake.getLastRequest();
        List<ChatMessage> messages = sent.getMessages();
        assertEquals(2, messages.size());
        assertEquals(ChatRole.SYSTEM, messages.get(0).getRole());
        assertEquals(ChatRole.USER, messages.get(1).getRole());
        assertEquals("在北侧生成一台雷达。", messages.get(1).getContent());

        // Assert：用户输入没有渗进系统规则，否则等于让用户改写开发者设定的规则。
        assertFalse(messages.get(0).getContent().contains("在北侧生成一台雷达。"));

        // Assert：总结任务需要稳定输出，所以温度调低而不是用默认值。
        assertEquals("gpt-4o-mini", sent.getModel());
        assertEquals(0.2, sent.getTemperature(), 0.0001);
        assertEquals(200, sent.getMaxOutputTokens());
    }

    /** {@code finishReason=LENGTH} 必须拒绝：残句看起来是正常中文，只有 {@code finishReason} 能识别它，放过去就是脏数据入库，事后分不清是模型答错还是被截断。 */
    @Test
    public void shouldRejectTruncatedOutput() {
        // Arrange：模型话没说完就撞到 maxOutputTokens 上限，content 是一句残句。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("北侧新增一台雷达，东南角部署", FinishReason.LENGTH, new TokenUsage(120, 200));
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：业务调用应当失败，而不是把残句返回给下游。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> service.summarize("一段很长的场景描述……")
        );

        // Assert：分类为不可重试——原样重试还会被同样截断，得先调大上限或缩短输入。
        assertEquals(ModelException.ErrorType.INVALID_REQUEST, exception.getErrorType());
        assertFalse(exception.isRetryable());

        // Assert：只发了一次请求，没有因为"失败"就盲目重试。
        assertEquals(1, fake.getCallCount());

        // Assert：这次调用虽然业务失败，Token 依然被计费，成本统计不能漏掉它。
        assertEquals(320, service.getTotalTokens());
    }

    /** {@code finishReason=CONTENT_FILTER} 必须拒绝且不重试：安全拦截是确定性结果，误判成「服务暂时不可用」去重试，每次都要付输入 Token 的钱，最后照样失败。 */
    @Test
    public void shouldRejectContentFilteredOutput() {
        // Arrange：输出被内容安全策略拦截，此时 content 不可用。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("", FinishReason.CONTENT_FILTER, new TokenUsage(80, 0));
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：业务层必须显式拒绝。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> service.summarize("一段触发安全策略的描述。")
        );

        // Assert：同样输入重试没有意义，所以归类为不可重试。
        assertEquals(ModelException.ErrorType.CONTENT_FILTERED, exception.getErrorType());
        assertFalse(exception.isRetryable());
        assertEquals(1, fake.getCallCount());
    }

    /** 限流要在服务内部自动重试，业务方只调用一次：把 429 当致命错误抛给用户，高峰期会出现大量本可自动恢复的失败；让每个调用方自己写重试，改退避策略就要改几十个地方。 */
    @Test
    public void shouldRetryRateLimitAndSucceed() {
        // Arrange：前两次限流（HTTP 429），第三次正常返回。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "请求过于频繁（第 1 次）");
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "请求过于频繁（第 2 次）");
        fake.enqueueResponse("南侧新增一道围栏。", FinishReason.STOP, new TokenUsage(90, 12));
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：业务只调用一次，重试在服务内部完成。
        String summary = service.summarize("在南侧加一道围栏。");

        // Assert：最终成功，且确实发了三次请求。
        assertEquals("南侧新增一道围栏。", summary);
        assertEquals(3, fake.getCallCount());

        // Assert：只有成功那次返回了 usage，所以只累加这一次的 Token。
        assertEquals(102, service.getTotalTokens());
    }

    /** 鉴权失败第一次就抛出，不消耗剩余重试次数：断言 {@code getCallCount() == 1} 验的不是「失败了」而是「失败得足够快」，一律重试的话密钥配错会让用户等 3 倍时间、日志出现 3 倍噪音。 */
    @Test
    public void shouldNotRetryAuthenticationError() {
        // Arrange：密钥无效。即使允许重试 3 次，也不该浪费在这上面。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：第一次失败就应该抛出。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> service.summarize("在西侧放置一台风速仪。")
        );

        // Assert：错误分类保持原样，调用方不需要解析错误文本来判断能否重试。
        assertEquals(ModelException.ErrorType.AUTHENTICATION, exception.getErrorType());

        // Assert：只请求了一次，剩下两次重试次数没有被消耗。
        assertEquals(1, fake.getCallCount());
    }

    /** 重试用尽要失败并保留原始分类和尝试次数：无限重试会让一个持续 5xx 的上游占满线程池，把故障从模型服务扩散成整个应用不可用；丢掉分类则只剩一句「未知失败」。 */
    @Test
    public void shouldFailAfterExhaustingRetries() {
        // Arrange：服务端一直 5xx，重试次数设为 2。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.SERVER_ERROR, "上游 502");
        fake.enqueueError(ModelException.ErrorType.SERVER_ERROR, "上游 502");
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 2);

        // Act：重试用尽后仍然失败。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> service.summarize("在东侧放置一台摄像头。")
        );

        // Assert：请求次数等于 maxAttempts，没有无限重试。
        assertEquals(2, fake.getCallCount());

        // Assert：保留原始错误分类，并在消息里说明尝试了几次，便于排查。
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.getMessage().contains("2"));
        assertTrue(exception.getMessage().contains("上游 502"));
    }

    /** Token 跨多次调用累加且输入输出分开统计：输入会随对话历史线性增长（第 10 轮要把前 9 轮全部重发），只记总数的话月底费用超支也说不清是调用变多了、对话变长了还是重试放大了用量。 */
    @Test
    public void shouldAccumulateTokensAcrossCalls() {
        // Arrange：两次成功调用，Token 消耗不同。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("第一条总结。", FinishReason.STOP, new TokenUsage(100, 10));
        fake.enqueueResponse("第二条总结。", FinishReason.STOP, new TokenUsage(50, 5));
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：同一个 service 连续处理两个请求。
        service.summarize("第一个场景。");
        service.summarize("第二个场景。");

        // Assert：输入和输出分别累加——两者单价不同，不能只记总数。
        assertEquals(150, service.getTotalPromptTokens());
        assertEquals(15, service.getTotalCompletionTokens());
        assertEquals(165, service.getTotalTokens());
    }

    /** 空白输入在本地挡住，一次请求都不发：空输入送过去模型不会报错，它会自由发挥编一段总结，你拿到的是看起来正常、实际毫无根据的假数据，而监控上这次调用显示为成功。 */
    @Test
    public void shouldRejectBlankSceneDescriptionWithoutCallingModel() {
        // Arrange：空白输入。
        FakeModelClient fake = new FakeModelClient();
        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：参数校验应该在本地就挡住。
        assertThrows(
                IllegalArgumentException.class,
                () -> service.summarize("   ")
        );

        // Assert：一次请求都没发出，省下费用也避免模型自由发挥。
        assertEquals(0, fake.getCallCount());
    }

    /** 依赖和配置在构造时校验：不检查的话空指针要等几小时后第一次真正调用模型才出现，栈顶指向业务方法，而真正的问题是启动时依赖注入配错了。 */
    @Test
    public void shouldRejectInvalidConstructorArguments() {
        // Arrange + Act + Assert：依赖和配置在构造时校验，避免服务半初始化就被使用。
        assertThrows(
                IllegalArgumentException.class,
                () -> new SceneSummaryService(null, "gpt-4o-mini", 3)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new SceneSummaryService(new FakeModelClient(), "  ", 3)
        );
        // maxAttempts 为 0 意味着一次都不尝试，属于配置错误。
        assertThrows(
                IllegalArgumentException.class,
                () -> new SceneSummaryService(new FakeModelClient(), "gpt-4o-mini", 0)
        );
    }
}
