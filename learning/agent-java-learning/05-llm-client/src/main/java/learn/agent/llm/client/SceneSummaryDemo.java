package learn.agent.llm.client;

/**
 * 阶段 5 第 1 课的教学入口。
 *
 * <p>按业务执行顺序打印一次模型调用的全过程，重点看四件事：</p>
 *
 * <ol>
 *   <li>请求里到底传了什么（模型名、消息条数、温度、输出上限）；</li>
 *   <li>响应里除了正文还有什么（结束原因、Token、请求 id）；</li>
 *   <li>被截断的输出为什么不能直接用；</li>
 *   <li>限流之后为什么可以重试，鉴权失败为什么不能。</li>
 * </ol>
 *
 * <p>全程使用 {@link FakeModelClient}，不需要密钥也不需要网络。
 * 阶段 5 第 2 课再换成真实 HTTP 客户端。</p>
 *
 * <p>运行：</p>
 * <pre>
 * mvn -o -pl 05-llm-client -am test-compile
 * java -cp '05-llm-client/target/classes' learn.agent.llm.client.SceneSummaryDemo
 * </pre>
 */
public class SceneSummaryDemo {

    public static void main(String[] args) {
        demoNormalCall();
        demoTruncatedOutput();
        demoRetryAfterRateLimit();
        demoNonRetryableError();
    }

    /** 场景一：正常调用，观察请求和响应的完整结构。 */
    private static void demoNormalCall() {
        System.out.println("=== 场景一：一次正常的模型调用 ===");

        // Arrange：预设模型会返回一句总结，输入 120 token、输出 18 token。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "北侧新增一台雷达，东南角部署两台摄像头。",
                FinishReason.STOP,
                new TokenUsage(120, 18));

        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：业务调用。
        String summary = service.summarize("在北侧生成一台雷达，并在东南角放置两台摄像头用于周界监控。");

        // Assert：打印真正发出去的请求，看清"一次调用传了什么"。
        ChatRequest sent = fake.getLastRequest();
        System.out.println("发出的请求：" + sent);
        System.out.println("消息列表：");
        for (ChatMessage message : sent.getMessages()) {
            System.out.println("  " + message);
        }
        System.out.println("模型返回的总结：" + summary);
        System.out.println("本次累计 Token：" + service.getTotalTokens()
                + "（输入 " + service.getTotalPromptTokens()
                + " + 输出 " + service.getTotalCompletionTokens() + "）");
        System.out.println("注意：系统规则和用户输入是两条独立消息，没有拼成一段文本。");
        System.out.println();
    }

    /** 场景二：输出被截断。这是最容易被忽略的生产故障。 */
    private static void demoTruncatedOutput() {
        System.out.println("=== 场景二：输出被 maxOutputTokens 截断 ===");

        // Arrange：模型话没说完就到达上限，finishReason 是 LENGTH。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                "北侧新增一台雷达，东南角部署",
                FinishReason.LENGTH,
                new TokenUsage(120, 200));

        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act + Assert：业务层必须拒绝这个响应，而不是把残句当结果。
        try {
            service.summarize("一段很长的场景描述……");
            System.out.println("不应该走到这里");
        } catch (ModelException e) {
            System.out.println("被业务层拦住了：" + e.getMessage());
            System.out.println("错误分类：" + e.getErrorType() + "，是否可重试：" + e.isRetryable());
        }
        System.out.println("要点：content 看起来像正常文本，只有 finishReason 能告诉你它是残缺的。");
        System.out.println("即使这次失败，Token 依然被计费：" + service.getTotalTokens());
        System.out.println();
    }

    /** 场景三：限流后重试成功。 */
    private static void demoRetryAfterRateLimit() {
        System.out.println("=== 场景三：先限流两次，第三次成功 ===");

        // Arrange：前两次抛 429，第三次正常返回。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "请求过于频繁（第 1 次）");
        fake.enqueueError(ModelException.ErrorType.RATE_LIMIT, "请求过于频繁（第 2 次）");
        fake.enqueueResponse("南侧新增一道围栏。", FinishReason.STOP, new TokenUsage(90, 12));

        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act：一次业务调用，内部自动重试。
        String summary = service.summarize("在南侧加一道围栏。");

        // Assert：业务成功，但实际发了三次请求。
        System.out.println("最终结果：" + summary);
        System.out.println("实际请求次数：" + fake.getCallCount() + "（业务只调用了 1 次）");
        System.out.println("要点：RATE_LIMIT 和 SERVER_ERROR 等一会儿就好，值得重试。");
        System.out.println("真实项目这里要加退避等待，不能立刻重试，见阶段 11。");
        System.out.println();
    }

    /** 场景四：鉴权失败，立即放弃。 */
    private static void demoNonRetryableError() {
        System.out.println("=== 场景四：鉴权失败不重试 ===");

        // Arrange：密钥错误。即使允许重试 3 次，也应该只发 1 次请求。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "API key 无效");

        SceneSummaryService service = new SceneSummaryService(fake, "gpt-4o-mini", 3);

        // Act + Assert：第一次失败就抛出，不消耗剩余重试次数。
        try {
            service.summarize("在西侧放置一台风速仪。");
            System.out.println("不应该走到这里");
        } catch (ModelException e) {
            System.out.println("立即失败：" + e.getMessage());
            System.out.println("实际请求次数：" + fake.getCallCount() + "（没有浪费重试）");
        }
        System.out.println("要点：密钥错、参数错、上下文超长，重试一万次结果一样。");
        System.out.println("把「能否重试」放进错误分类，调用方就不用猜。");
    }
}
