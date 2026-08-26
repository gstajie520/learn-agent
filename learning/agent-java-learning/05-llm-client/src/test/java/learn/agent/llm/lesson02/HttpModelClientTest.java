package learn.agent.llm.lesson02;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatResponse;
import learn.agent.llm.lesson01.ModelException;
import learn.agent.llm.lesson01.SceneSummaryService;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * HTTP 客户端测试。
 *
 * <p>分两类：</p>
 *
 * <ul>
 *   <li><b>离线测试</b>：超时配置校验、不可达地址的错误分类。
 *       这些不需要密钥，任何环境都会执行；</li>
 *   <li><b>真实调用测试</b>：需要 {@code OPENAI_BASE_URL}、{@code OPENAI_API_KEY}
 *       和 {@code OPENAI_MODEL}。未配置时<b>明确跳过</b>，
 *       绝不把「没配密钥」伪装成「测试通过」。</li>
 * </ul>
 *
 * <p>这个跳过策略和阶段 4 的真实 Redis 测试一致：环境缺失就跳过并说明原因，
 * 不静默通过，也不让整个构建失败。</p>
 */
public class HttpModelClientTest {

    /**
     * 规则：连接超时和读取超时都必须是正数，{@code 0} 要在构造时就被拒绝。
     *
     * <p><b>为什么重要：</b>{@code 0} 在 {@link java.net.HttpURLConnection} 里不是
     * 「立即超时」，而是「永不超时」——正好是最危险的那个含义，而且写 {@code 0}
     * 的人通常以为自己在设置一个很严格的限制。模型调用本身就慢（几秒到几十秒），
     * 所以超时值会调得比普通 HTTP 请求大得多，一路调到 {@code 0} 是很自然的手滑。</p>
     *
     * <p><b>违反会怎样：</b>线程泄漏。服务端不回包、连接被中间设备静默丢弃时，
     * 调用线程会永久阻塞在 {@code read()} 上，既不抛异常也不返回。
     * 固定大小的线程池被这样耗尽后，整个服务对所有请求都不再响应，
     * 而模型服务其实只是慢，并没有挂。这类故障在监控上表现为
     * 「线程数只增不减、无任何错误日志」，需要 dump 线程栈才能定位。</p>
     */
    @Test
    public void shouldRejectZeroTimeout() {
        // Arrange：一份合法配置。
        ModelSettings settings = ModelSettings.fromMap(fakeConfig());

        // Act + Assert：0 在 HttpURLConnection 里表示「永不超时」，必须拒绝。
        // 不拦住的话，服务端卡死时调用线程会一直挂着；
        // 固定大小线程池里几十个这样的请求就能让服务完全无响应，
        // 而模型服务其实只是慢，并没有挂。
        assertThrows(
                IllegalArgumentException.class,
                () -> new HttpModelClient(settings, 0, 60000)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new HttpModelClient(settings, 10000, 0)
        );
    }

    /**
     * 规则：{@code settings} 为 {@code null} 时构造函数直接抛异常，不接受半成品对象。
     *
     * <p><b>为什么重要：</b>这是「快速失败」的基本形态。构造时校验，
     * 问题出现在创建对象那一行；不校验，问题会推迟到第一次 {@code chat()} 调用，
     * 变成一个 {@link NullPointerException}，堆栈顶端指向客户端内部，
     * 完全看不出真正的原因是依赖注入配错了。</p>
     *
     * <p><b>违反会怎样：</b>故障点和根因在时间与空间上都被拉开。
     * 服务启动看起来一切正常，直到第一个真实用户请求进来才崩，
     * 而排查的人拿到的是一个内部 NPE，得反向推导才能回到「谁传了 null」。
     * 一个能构造出来的对象，就应该是能正常工作的对象。</p>
     */
    @Test
    public void shouldRejectNullSettings() {
        // Act + Assert：依赖缺失在构造时暴露，不要等第一次调用。
        assertThrows(
                IllegalArgumentException.class,
                () -> new HttpModelClient(null)
        );
    }

    /**
     * 规则：网络层失败（连接被拒、DNS 解析失败、TLS 握手失败）要映射成
     * <b>可重试</b>的 {@link ModelException}，而不是原样抛出
     * {@link java.io.IOException}。
     *
     * <p><b>为什么重要：</b>两件事在这一条里同时完成。一是<b>翻译</b>：
     * 上层的 {@link RetryingModelClient} 和第 1 课的 {@link SceneSummaryService}
     * 只认识 {@code ModelException} 和它的 {@code isRetryable()}，
     * 让 {@code IOException} 漏上去，等于要求每个调用方都懂 HTTP。
     * 二是<b>分类</b>：连接被拒、网络抖动、服务滚动重启、DNS 短暂失效，
     * 都是「现在不行，等一下可能就行」的暂时性故障，重试是有意义的。</p>
     *
     * <p><b>违反会怎样：</b>如果误判成不可重试，一次网络抖动就变成一个用户可见的错误，
     * 而这个错误本来重试一次就没了——上游滚动发布期间会集中爆发。
     * 如果干脆不翻译，异常类型会直接击穿抽象层：业务代码要么捕获
     * {@code IOException}（于是被绑死在 HTTP 实现上，换成 gRPC 就得重写），
     * 要么根本没捕获，让一个网络异常冒到最外层。</p>
     *
     * <p>测试用 {@code 127.0.0.1:1} 触发：这个端口不会有服务监听，
     * 连接会被立刻拒绝，不依赖外网，也不用等超时。</p>
     */
    @Test
    public void shouldClassifyUnreachableHostAsRetryableServerError() {
        // Arrange：指向一个保留给文档用途、不会真实响应的地址。
        Map<String, String> values = fakeConfig();
        // 端口 1 上不会有服务监听，连接会被立刻拒绝。
        values.put("OPENAI_BASE_URL", "http://127.0.0.1:1");
        ModelSettings settings = ModelSettings.fromMap(values);
        HttpModelClient client = new HttpModelClient(settings, 1000, 1000);

        // Act：网络层失败。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> client.chat(request("deepseek-v4-flash"))
        );

        // Assert：连接被拒属于暂时性故障，归类为可重试。
        // 网络抖动、服务重启、DNS 短暂失败都落在这一类。
        assertTrue(exception.isRetryable(),
                "网络层失败应当可重试，实际分类：" + exception.getErrorType());
    }

    /**
     * 规则：真实调用能拿到可用响应，且响应里必须带 Token 用量和请求 ID。
     *
     * <p><b>需要真实密钥。</b>三个环境变量没配齐时，这个测试会被
     * {@link Assumptions#assumeTrue} <b>跳过</b>。请务必分清：
     * <b>跳过不等于通过</b>。它跳过时，真实网络路径完全没有被验证过——
     * TLS 握手、请求体序列化是否被供应商接受、响应 JSON 的实际字段结构、
     * 连接复用行为，这些都还是未知的。前面那些离线测试再绿，也证明不了
     * 这条链路能通。配好 {@code OPENAI_BASE_URL} / {@code OPENAI_API_KEY} /
     * {@code OPENAI_MODEL} 后重跑，才是真的验证过。</p>
     *
     * <p><b>为什么重要：</b>{@link ChatJsonCodec} 的解析逻辑是照着文档写的，
     * 而各家供应商在 OpenAI 兼容协议上都有细微差异（{@code usage} 可能缺字段、
     * 请求 ID 放在响应体还是 HTTP 头、{@code finish_reason} 的取值拼写）。
     * 只有真发一次请求才能发现这些差异。断言 Token 用量大于 0 还有另一层意思：
     * 用量是成本可观测的唯一数据来源，解析丢了它，线上就没法归因账单。</p>
     *
     * <p><b>违反会怎样：</b>所有离线测试全绿，一上线第一个请求就失败，
     * 因为解析代码和供应商的真实返回格式对不上。这类问题只会在真实环境暴露，
     * 而那时暴露的成本远高于现在。</p>
     */
    @Test
    public void shouldCallRealModelWhenConfigured() {
        // Arrange：只有三个环境变量都配齐时才执行这个测试。
        ModelSettings settings = readSettingsOrSkip();

        HttpModelClient client = new HttpModelClient(settings, 10000, 60000);

        // Act：发起一次真实调用。
        ChatResponse response = client.chat(request(settings.getModel()));

        // Assert：拿到可用响应，并且四项关键信息都在。
        assertNotNull(response);
        assertTrue(response.isUsable(),
                "响应应当可用，实际 finishReason=" + response.getFinishReason());
        assertTrue(response.getContent().length() > 0);
        // 真实调用一定有 Token 消耗，这也是成本可观测的基础。
        assertTrue(response.getUsage().getTotalTokens() > 0,
                "真实调用应当返回 Token 用量");
        assertNotNull(response.getRequestId());
    }

    /**
     * 规则：{@link SceneSummaryService} 一行代码都不用改，就能从 {@code FakeModelClient}
     * 切换到真实 HTTP 客户端。
     *
     * <p><b>需要真实密钥，未配置时跳过</b>（同 {@code shouldCallRealModelWhenConfigured}，
     * 跳过意味着这条集成路径未被验证）。</p>
     *
     * <p><b>为什么重要：</b>这是整个课程里最值得停下来看的一个测试——它是第 1 课那个
     * 设计决定的<b>回报兑现</b>。第 1 课让业务只依赖
     * {@link learn.agent.llm.lesson01.ModelClient ModelClient} 接口，
     * 当时看起来像是多写了一层没必要的抽象。现在换实现只需改一行装配代码：
     * {@code SceneSummaryService} 的源文件保持原样，连重新编译的理由都没有。
     * 顺便注意装配方式：{@code HttpModelClient} 被 {@link RetryingModelClient} 包了一层，
     * 再传给业务。重试是<b>叠加</b>上去的，不是写进 HTTP 客户端里的——
     * 两个类各管一件事，都实现同一个接口，所以能自由组合。</p>
     *
     * <p><b>违反会怎样：</b>如果业务代码直接依赖具体实现（自己 new 一个 HTTP 客户端、
     * 或者方法签名里出现 {@code HttpModelClient}），那么换供应商、加重试、
     * 在测试里替换成假实现，每一件都要改业务代码。更要紧的是：
     * 业务逻辑将再也无法脱离网络做单元测试，第 1 课那些「前两次限流、第三次成功」
     * 之类的场景根本构造不出来。抽象层的价值不在写的时候，在改的时候。</p>
     */
    @Test
    public void shouldWorkWithLesson01ServiceUnchanged() {
        // Arrange：这个测试证明第 1 课那层接口的价值 ——
        // SceneSummaryService 是第 1 课写的类，一行都没改，
        // 只是把注入的 FakeModelClient 换成了真实 HTTP 客户端。
        ModelSettings settings = readSettingsOrSkip();

        HttpModelClient httpClient = new HttpModelClient(settings, 10000, 60000);
        RetryingModelClient withRetry = new RetryingModelClient(httpClient, 3, 500, 8000);
        SceneSummaryService service = new SceneSummaryService(withRetry, settings.getModel(), 1);

        // Act：调用第 1 课的业务方法。
        String summary = service.summarize(
                "在北侧生成一台雷达，并在东南角放置两台摄像头用于周界监控。");

        // Assert：拿到真实模型的总结，且 Token 被正确累计。
        assertNotNull(summary);
        assertTrue(summary.length() > 0);
        assertTrue(service.getTotalTokens() > 0);
    }

    /**
     * 规则：密钥错误（HTTP 401/403）必须归类为 {@code AUTHENTICATION} 且
     * <b>不可重试</b>，第一次失败就立刻抛出。
     *
     * <p><b>需要真实的 {@code OPENAI_BASE_URL} 和 {@code OPENAI_MODEL}</b>
     * （密钥由测试故意填一个无效值），未配置时跳过。跳过时，
     * 「本客户端能否正确识别供应商返回的鉴权错误」这一点是未经验证的。</p>
     *
     * <p><b>为什么重要：</b>这里验证的是<b>状态码到错误类型的映射</b>在真实供应商上成立。
     * 第 1 课已经用 Fake 验证过「不可重试错误不该重试」的逻辑，
     * 但那前提是错误被正确分类。分类发生在 HTTP 客户端里：
     * 只有它看得见状态码，一旦它把 401 归成 {@code SERVER_ERROR}，
     * 上层再正确也救不回来。密钥错了重试一万次结果一样，
     * 这类失败需要人改配置，不是等待能恢复的。</p>
     *
     * <p><b>违反会怎样：</b>把 401 误判成可重试，那么密钥配错时——这恰好是最常见的
     * 首次部署故障——每个请求都会跑完整轮指数退避（本例是 3 次，退避到 8 秒），
     * 用户要等十几秒才看到一个从第一毫秒就已经确定的失败。
     * 日志里堆满三倍的重复错误，反而掩盖了真正的原因。
     * 更糟的情况是密钥过期时线上突然出现大面积超时而不是清晰的鉴权报错，
     * 排查方向会被彻底带偏。</p>
     */
    @Test
    public void shouldFailFastWithInvalidApiKey() {
        // Arrange：用真实地址配一个错误密钥。
        // 只在配置了 base_url 时执行，避免对着不存在的服务发请求。
        String baseUrl = System.getenv("OPENAI_BASE_URL");
        String model = System.getenv("OPENAI_MODEL");
        Assumptions.assumeTrue(
                baseUrl != null && !baseUrl.trim().isEmpty()
                        && model != null && !model.trim().isEmpty(),
                "OPENAI_BASE_URL / OPENAI_MODEL 未配置，跳过鉴权失败测试");

        Map<String, String> values = new HashMap<String, String>();
        values.put("OPENAI_BASE_URL", baseUrl);
        values.put("OPENAI_MODEL", model);
        values.put("OPENAI_API_KEY", "sk-definitely-invalid-key-for-testing");
        ModelSettings settings = ModelSettings.fromMap(values);

        HttpModelClient client = new HttpModelClient(settings, 10000, 30000);

        // Act：服务端应当返回 401 或 403。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> client.chat(request(model))
        );

        // Assert：归类为不可重试的鉴权错误。
        // 这一条很重要：密钥错了重试一万次结果一样，
        // 但如果误判成可重试，就会白等好几轮退避才失败。
        assertEquals(ModelException.ErrorType.AUTHENTICATION, exception.getErrorType(),
                "错误信息：" + exception.getMessage());
        assertTrue(!exception.isRetryable());
    }

    /**
     * 读取真实配置，缺失时跳过测试并说明原因。
     *
     * <p>用 {@code assumeTrue} 而不是 {@code Assumptions.abort}：
     * 后者是 JUnit 5.9 才加入的，本模块用的是 5.8.2。</p>
     */
    private ModelSettings readSettingsOrSkip() {
        boolean configured = isConfigured("OPENAI_BASE_URL")
                && isConfigured("OPENAI_API_KEY")
                && isConfigured("OPENAI_MODEL");

        // 明确跳过，不是通过。构建输出里会显示这条原因。
        Assumptions.assumeTrue(configured,
                "OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL 未全部配置，跳过真实调用测试");

        return ModelSettings.fromEnvironment();
    }

    /** 判断某个环境变量是否有非空值。 */
    private boolean isConfigured(String name) {
        String value = System.getenv(name);
        return value != null && !value.trim().isEmpty();
    }

    private ChatRequest request(String model) {
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system("你是场景描述助手。用一句中文总结用户提供的场景，不要提问。"));
        messages.add(ChatMessage.user("在北侧生成一台雷达。"));
        // 测试用的输出上限给小一点，控制成本。
        return new ChatRequest(model, messages, 0.2, 100);
    }

    private Map<String, String> fakeConfig() {
        Map<String, String> values = new HashMap<String, String>();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com");
        values.put("OPENAI_API_KEY", "sk-fake");
        values.put("OPENAI_MODEL", "deepseek-v4-flash");
        return values;
    }
}
