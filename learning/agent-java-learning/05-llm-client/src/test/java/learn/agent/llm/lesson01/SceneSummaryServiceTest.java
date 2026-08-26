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

    /**
     * 规则：系统规则和用户输入必须是两条独立消息，不能拼成一段文本。
     *
     * <p><b>为什么重要：</b>{@code SYSTEM} 是开发者设定的规则，模型会优先遵守。
     * 一旦把用户输入拼进系统消息，用户就能写「忽略上面的指令」来改写业务约束。</p>
     *
     * <p><b>违反会怎样：</b>提示注入。用户输入直接获得了系统级权限，
     * 业务设定的「只输出一句总结、不要提问」这类约束会被绕过。</p>
     *
     * <p>本测试顺便验证温度和输出上限确实按业务需要设置，没有用默认值。</p>
     */
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

    /**
     * 规则：{@code finishReason=LENGTH}（输出被截断）必须拒绝，不能把残句当结果返回。
     *
     * <p><b>为什么重要：</b>这是本课最容易被忽略、也最容易在生产出事的一条。
     * 被截断的 {@code content} 看起来是正常中文，没有任何异常标志，
     * 只有 {@code finishReason} 能告诉你它是残缺的。</p>
     *
     * <p><b>违反会怎样：</b>残句流进下游。如果下游要解析 JSON，会在
     * 「模型明明返回了内容」的情况下解析失败；如果直接写库，就产生了脏数据，
     * 而且事后无法区分是模型答错还是被截断。</p>
     *
     * <p>另外验证一个反直觉的点：这次调用业务失败了，但 Token 照样计费，
     * 所以成本统计不能只在成功分支里累加。</p>
     */
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

    /**
     * 规则：{@code finishReason=CONTENT_FILTER}（被内容安全策略拦截）必须拒绝，且不重试。
     *
     * <p><b>为什么重要：</b>安全拦截是<b>确定性</b>结果，不是偶发故障。
     * 同样的输入送过去，还会被同样拦截。</p>
     *
     * <p><b>违反会怎样：</b>如果误判成「服务暂时不可用」而去重试，
     * 每次重试都要付输入 Token 的钱，最后还是失败。用户等得更久、账单更高、
     * 日志里堆一片同样的错误。</p>
     */
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

    /**
     * 规则：限流（HTTP 429）属于暂时性故障，应当自动重试；业务方只调用一次。
     *
     * <p><b>为什么重要：</b>限流的含义是「你现在太快了，等一下再来」，
     * 不是「这个请求错了」。等一会儿重试通常就能成功。而且重试要发生在
     * <b>服务内部</b>，业务代码不该关心这件事。</p>
     *
     * <p><b>违反会怎样：</b>把 429 当致命错误直接抛给用户，
     * 高峰期会出现大量本可自动恢复的失败；反过来，如果让每个调用方
     * 自己写重试，重试逻辑会散落在几十处，改退避策略要改几十个地方。</p>
     *
     * <p>这个场景在真实环境很难复现（要正好撞上限流），但用
     * {@link FakeModelClient} 可以精确构造「前两次限流、第三次成功」。
     * 这就是引入 {@link ModelClient} 接口最直接的收益。</p>
     */
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

    /**
     * 规则：鉴权失败不可重试，第一次失败就立即抛出，不消耗剩余重试次数。
     *
     * <p><b>为什么重要：</b>密钥错了，重试一万次结果完全一样。
     * 这类失败需要人工改配置，不是等待就能恢复的。</p>
     *
     * <p><b>违反会怎样：</b>如果对所有异常一律重试，密钥配错时每个请求都会
     * 变成 3 次无用请求，用户要等 3 倍时间才看到错误，日志里也会出现
     * 3 倍噪音，掩盖真正的问题。</p>
     *
     * <p>注意断言的是 {@code getCallCount() == 1}：这里验证的不是「失败了」，
     * 而是「失败得足够快」。区分可重试和不可重试的价值就体现在这一个数字上。</p>
     */
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

    /**
     * 规则：重试次数用尽后必须失败，并且保留原始错误分类和尝试次数。
     *
     * <p><b>为什么重要：</b>重试不能无限进行。每次重试都在花钱、占线程、
     * 让用户多等一会儿。到了上限就必须放弃，把失败如实报出去。
     * 同时异常消息里要带上「尝试了几次」和原始错误，
     * 否则排查时只看到一句「调用失败」，不知道是试了 1 次还是 10 次。</p>
     *
     * <p><b>违反会怎样：</b>两种极端。一种是无限重试，一个持续 5xx 的上游
     * 会把线程池占满，故障从模型服务扩散成整个应用不可用；
     * 另一种是丢掉原始错误分类，监控上只看到「未知失败」，
     * 无法区分是限流、超时还是服务端故障。</p>
     */
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

    /**
     * 规则：Token 要跨多次调用累加，且输入和输出分开统计。
     *
     * <p><b>为什么重要：</b>输入和输出单价不同，输出通常更贵，
     * 只记总数无法准确核算成本。更关键的是输入 Token 会随对话历史
     * <b>线性增长</b>：第 10 轮对话要把前 9 轮全部重发一次，
     * 所以长会话的单次成本不是恒定的。这正是后面阶段要做上下文压缩的动机。</p>
     *
     * <p><b>违反会怎样：</b>账单失控且无法归因。月底看到费用超支，
     * 但不知道是调用次数涨了、还是单次对话变长了、还是重试放大了用量。
     * 没有分项数据就无法判断该优化哪一处。</p>
     */
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

    /**
     * 规则：空白输入在本地就要挡住，一次请求都不发。
     *
     * <p><b>为什么重要：</b>能在本地判断的错误就不要花一次网络往返去问模型。
     * 空输入发过去，模型不会报错，它会「自由发挥」编一段总结出来，
     * 那比直接失败更糟：你拿到了一个看起来正常、实际毫无根据的结果。</p>
     *
     * <p><b>违反会怎样：</b>既浪费钱又产生假数据。而且这类调用在监控上
     * 显示为「成功」，问题会被长期掩盖。</p>
     *
     * <p>注意这里抛的是 {@link IllegalArgumentException} 而不是
     * {@link ModelException}：这是<b>调用方的编程错误</b>，
     * 不是模型服务的问题，两者不应该混在同一个异常体系里。</p>
     */
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

    /**
     * 规则：依赖和配置在构造时校验，不允许创建出「半残」的服务对象。
     *
     * <p><b>为什么重要：</b>构造方法是最后一道能保证对象一定可用的关口。
     * 在这里挡住 null 依赖和非法配置，后面所有业务方法就不必再写防御性检查。
     * {@code maxAttempts=0} 意味着一次都不尝试，属于明显的配置错误。</p>
     *
     * <p><b>违反会怎样：</b>报错点远离真正的错误点。如果构造时不检查，
     * 空指针会在几小时后第一次真正调用模型时才出现，
     * 栈顶指向业务方法，而真正的问题是启动时依赖注入配错了。</p>
     */
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
