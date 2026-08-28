package learn.agent.llm.lesson02;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatResponse;
import learn.agent.llm.lesson01.FinishReason;
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
 * <p><b>怎么配</b>：在 {@code learning/agent-java-learning/.env} 里写三行
 * （文件已被 gitignore，永不提交；模板见同目录的 {@code .env.example}）：</p>
 *
 * <pre>
 * OPENAI_BASE_URL=https://api.deepseek.com
 * OPENAI_API_KEY=sk-你的密钥
 * OPENAI_MODEL=deepseek-v4-flash
 * </pre>
 *
 * <p>这份文件和 {@code python/.env} 内容一致，Python 和 Java 共用同一套配置。
 * 读取入口是 {@link ModelSettings#fromEnvironmentOrDotEnv()}，
 * 操作系统环境变量优先级更高，可以临时覆盖某一项。</p>
 *
 * <p>这个跳过策略和阶段 4 的真实 Redis 测试一致：环境缺失就跳过并说明原因，
 * 不静默通过，也不让整个构建失败。</p>
 */
public class HttpModelClientTest {

    /**
     * 两个超时都必须为正数、{@code 0} 在构造时就拒绝：{@code 0} 在 {@link java.net.HttpURLConnection}
     * 里是「永不超时」而非写的人以为的「立即超时」，服务端不回包时调用线程永久阻塞在 {@code read()} 上，
     * 线程池被耗尽后整个服务无响应，监控上只看到线程数只增不减、没有一条错误日志。
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
     * {@code settings} 为 {@code null} 时构造就抛，不接受半成品对象：不校验的话故障推迟到第一次
     * {@code chat()}，表现为堆栈指向客户端内部的 {@link NullPointerException} —— 服务启动一切正常，
     * 直到第一个真实用户请求才崩，排查的人得反向推导才回到「谁传了 null」。
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
     * 网络层失败要翻译成可重试的 {@link ModelException} 而不是漏出 {@link java.io.IOException}：
     * 误判成不可重试，一次上游滚动发布期间的网络抖动就变成用户可见的错误；不翻译则异常类型击穿抽象层，
     * 业务代码被绑死在 HTTP 实现上，换 gRPC 就得重写。
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
     * 真实调用要拿到非空内容并带上 Token 用量和请求 ID（三项配置缺任一即跳过，跳过不等于通过）：
     * 各家供应商在 OpenAI 兼容协议上的细微差异只有真发一次请求才暴露，否则离线测试全绿而上线第一个请求就失败。
     * 接受 {@code STOP} 和 {@code LENGTH} 而不断言 {@code isUsable()}，是因为模型话长话短不由被测代码决定，钉死它测试就会时绿时红。
     */
    @Test
    public void shouldCallRealModelWhenConfigured() {
        // Arrange：只有三项配置都齐时才执行这个测试。
        ModelSettings settings = readSettingsOrSkip();

        HttpModelClient client = new HttpModelClient(settings, 10000, 60000);

        // Act：发起一次真实调用。
        ChatResponse response = client.chat(request(settings.getModel()));

        // Assert：拿到内容非空的响应，并且关键信息都在。
        assertNotNull(response);
        assertTrue(response.getContent().length() > 0,
                "真实调用应当返回非空内容，finishReason=" + response.getFinishReason());
        // 真实调用一定有 Token 消耗，这也是成本可观测的基础。
        assertTrue(response.getUsage().getTotalTokens() > 0,
                "真实调用应当返回 Token 用量");
        assertNotNull(response.getRequestId());
        // STOP 是正常收尾，LENGTH 是撞到上限被截断。两者都说明响应解析成功；
        // 出现其它值（比如 CONTENT_FILTER 或解析不出来的 null）才说明有问题。
        assertTrue(response.getFinishReason() == FinishReason.STOP
                        || response.getFinishReason() == FinishReason.LENGTH,
                "finishReason 应为 STOP 或 LENGTH，实际=" + response.getFinishReason());
    }

    /**
     * 第 1 课的 {@link SceneSummaryService} 一行不改就能从 Fake 换成真实 HTTP 客户端（未配置密钥时跳过）：
     * 这是第 1 课那层看似多余的接口抽象在兑现回报 —— 换实现只动一行装配代码，重试还是靠
     * {@link RetryingModelClient} 叠加上去而非写进 HTTP 客户端。业务若直接依赖具体实现，
     * 换供应商、加重试、测试里替假实现都得改业务代码，而且再也无法脱离网络做单元测试。
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
     * 401/403 要归成不可重试的 {@code AUTHENTICATION} 并立刻抛出（需真实 {@code OPENAI_BASE_URL} 与
     * {@code OPENAI_MODEL}，密钥故意填无效值，未配置时跳过）：状态码只有 HTTP 客户端看得见，它把 401 归成
     * {@code SERVER_ERROR}，上层重试逻辑再对也救不回来 —— 首次部署配错密钥这种最常见的故障会跑完整轮退避，
     * 用户等十几秒才看到一个第一毫秒就已确定的失败，日志里三倍的重复错误还盖住了真正的原因。
     */
    @Test
    public void shouldFailFastWithInvalidApiKey() {
        // Arrange：用真实地址配一个错误密钥。
        // 只在配置了 base_url 时执行，避免对着不存在的服务发请求。
        String baseUrl = ModelSettings.lookup("OPENAI_BASE_URL");
        String model = ModelSettings.lookup("OPENAI_MODEL");
        Assumptions.assumeTrue(
                baseUrl != null && model != null,
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
     *
     * <p>走 {@link ModelSettings#lookup(String)} 而不是
     * {@link System#getenv(String)}：前者会把工程根目录的 {@code .env} 也算进来。
     * 如果这里只看进程环境变量，就会出现「{@code .env} 配好了、
     * 真实调用却仍然被跳过」——而跳过在报告里是绿的，
     * 很容易被当成「测过了」。</p>
     */
    private ModelSettings readSettingsOrSkip() {
        boolean configured = isConfigured("OPENAI_BASE_URL")
                && isConfigured("OPENAI_API_KEY")
                && isConfigured("OPENAI_MODEL");

        // 明确跳过，不是通过。构建输出里会显示这条原因。
        Assumptions.assumeTrue(configured,
                "OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL 未全部配置"
                        + "（.env 与环境变量都没有），跳过真实调用测试");

        return ModelSettings.fromEnvironmentOrDotEnv();
    }

    /** 判断某个配置项是否有非空值（{@code .env} 或环境变量任一即可）。 */
    private boolean isConfigured(String name) {
        return ModelSettings.lookup(name) != null;
    }

    private ChatRequest request(String model) {
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system("你是场景描述助手。用一句中文总结用户提供的场景，不要提问。"));
        messages.add(ChatMessage.user("在北侧生成一台雷达。"));
        // 输出上限给 300：既控制成本，又让「一句话中文总结」有充裕空间正常结束。
        // 之前给 100 太紧 —— 中文很吃 token，模型稍微多说两句就会以
        // finishReason=LENGTH 截断，把测试变成「看模型这次啰嗦不啰嗦」。
        return new ChatRequest(model, messages, 0.2, 300);
    }

    private Map<String, String> fakeConfig() {
        Map<String, String> values = new HashMap<String, String>();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com");
        values.put("OPENAI_API_KEY", "sk-fake");
        values.put("OPENAI_MODEL", "deepseek-v4-flash");
        return values;
    }
}
