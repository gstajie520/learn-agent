package learn.agent.llm.lesson02;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatResponse;
import learn.agent.llm.lesson01.ModelClient;
import learn.agent.llm.lesson01.ModelException;
import learn.agent.llm.lesson01.SceneSummaryService;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

/**
 * 阶段 5 第 2 课的教学入口。
 *
 * <p>按业务顺序演示五件事：</p>
 * <ol>
 *   <li>配置校验：三个环境变量缺一个会怎样；</li>
 *   <li>请求 JSON：一次模型调用真正发出去的字节；</li>
 *   <li>响应解析：服务端 JSON 如何变成内部对象，畸形响应如何被拦住；</li>
 *   <li>错误映射：HTTP 状态码如何决定「能不能重试」；</li>
 *   <li>退避序列：为什么重试要等，而且等待时间要带抖动。</li>
 * </ol>
 *
 * <p><b>前四步和第五步都不需要密钥</b>，没配置也能完整跑完。
 * 只有最后的真实调用会在缺少配置时跳过 —— 跳过时明确说明，
 * 不把「没配密钥」伪装成「测试通过」。</p>
 *
 * <p>运行：</p>
 * <pre>
 * mvn -o -pl 05-llm-client -am package -DskipTests
 * java -cp '05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.lesson02.RealModelCallDemo
 * </pre>
 */
public class RealModelCallDemo {

    public static void main(String[] args) {
        demoConfigValidation();
        demoRequestJson();
        demoResponseParsing();
        demoErrorMapping();
        demoBackoffSequence();
        demoRealCallIfConfigured();
    }

    /** 场景一：配置校验一次性报出所有问题。 */
    private static void demoConfigValidation() {
        System.out.println("=== 场景一：配置校验 ===");

        // Arrange：三个变量全都没配。
        try {
            ModelSettings.fromMap(new java.util.HashMap<String, String>());
        } catch (ConfigurationException e) {
            System.out.println("全部缺失：" + e.getMessage());
            System.out.println("要点：一次报出三个，改一遍就能启动，不必重启三次。");
        }

        // Arrange：把完整端点误当根地址配进去，这是真实踩过的坑。
        java.util.Map<String, String> wrong = new java.util.HashMap<String, String>();
        wrong.put("OPENAI_BASE_URL", "https://api.deepseek.com/chat/completions");
        wrong.put("OPENAI_API_KEY", "sk-fake");
        wrong.put("OPENAI_MODEL", "deepseek-v4-flash");
        try {
            ModelSettings.fromMap(wrong);
        } catch (ConfigurationException e) {
            System.out.println("端点当根地址：" + e.getMessage());
            System.out.println("要点：不拦住的话会拼成 .../chat/completions/chat/completions，");
            System.out.println("     服务端返回 404，但报错看起来像模型不存在，极难排查。");
        }

        // Arrange：正确配置。
        ModelSettings ok = ModelSettings.fromMap(sampleConfig());
        System.out.println("正确配置：" + ok);
        System.out.println("实际请求地址：" + ok.getChatCompletionsUrl());
        System.out.println("注意 toString 只打印密钥长度，不打印密钥本身。");
        System.out.println();
    }

    /** 场景二：看清一次调用真正发出去的 JSON。 */
    private static void demoRequestJson() {
        System.out.println("=== 场景二：真实请求 JSON ===");

        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system("你是场景描述助手。用一句中文总结用户提供的场景。"));
        messages.add(ChatMessage.user("在北侧生成一台雷达，并在东南角放置两台摄像头。"));
        ChatRequest request = new ChatRequest("deepseek-v4-flash", messages, 0.2, 200);

        String json = new ChatJsonCodec().toRequestJson(request);
        System.out.println(json);
        System.out.println("要点：所谓「调用大模型」，本质就是 POST 这样一段 JSON。");
        System.out.println("     role 是小写的 system/user，不是 Java 枚举的 SYSTEM/USER。");
        System.out.println();
    }

    /** 场景三：响应解析，包括畸形响应被拦住。 */
    private static void demoResponseParsing() {
        System.out.println("=== 场景三：响应解析 ===");
        ChatJsonCodec codec = new ChatJsonCodec();

        // Arrange：一段正常的服务端响应。
        String good = "{"
                + "\"id\":\"chatcmpl-abc123\","
                + "\"choices\":[{\"message\":{\"role\":\"assistant\","
                + "\"content\":\"北侧新增一台雷达，东南角部署两台摄像头。\"},"
                + "\"finish_reason\":\"stop\"}],"
                + "\"usage\":{\"prompt_tokens\":120,\"completion_tokens\":18}"
                + "}";
        ChatResponse response = codec.parseResponse(good, null);
        System.out.println("解析成功：" + response);
        System.out.println("正文：" + response.getContent());
        System.out.println("可用吗：" + response.isUsable());

        // Arrange：被截断的响应。正文看着正常，finish_reason 才是真相。
        String truncated = "{"
                + "\"id\":\"chatcmpl-def456\","
                + "\"choices\":[{\"message\":{\"role\":\"assistant\","
                + "\"content\":\"北侧新增一台雷达，东南角部署\"},"
                + "\"finish_reason\":\"length\"}],"
                + "\"usage\":{\"prompt_tokens\":120,\"completion_tokens\":200}"
                + "}";
        ChatResponse cut = codec.parseResponse(truncated, null);
        System.out.println("截断响应：finishReason=" + cut.getFinishReason() + "，可用吗=" + cut.isUsable());

        // Arrange：畸形响应，缺少 choices。不可信边界必须挡住它。
        try {
            codec.parseResponse("{\"id\":\"x\"}", null);
        } catch (ModelException e) {
            System.out.println("畸形响应被拦住：" + e.getMessage());
            System.out.println("要点：不校验就直接空指针。响应和外部请求一样不可信。");
        }
        System.out.println();
    }

    /** 场景四：HTTP 状态码到「能否重试」的映射。 */
    private static void demoErrorMapping() {
        System.out.println("=== 场景四：错误映射 ===");
        ChatJsonCodec codec = new ChatJsonCodec();

        printMapping(codec, 401, "{\"error\":{\"message\":\"Invalid API key\"}}");
        printMapping(codec, 429, "{\"error\":{\"message\":\"Rate limit reached\"}}");
        printMapping(codec, 503, "{\"error\":{\"message\":\"Service unavailable\"}}");
        printMapping(codec, 400, "{\"error\":{\"message\":\"Invalid temperature\"}}");
        printMapping(codec, 400,
                "{\"error\":{\"message\":\"Too many tokens\",\"code\":\"context_length_exceeded\"}}");

        System.out.println("要点：同样是 400，上下文超长要压缩后重发，参数错要改代码。");
        System.out.println("     状态码是主依据，error.code 用来细分。");
        System.out.println();
    }

    private static void printMapping(ChatJsonCodec codec, int status, String body) {
        ModelException e = codec.toException(status, body, "req-demo");
        System.out.println("HTTP " + status + " → " + e.getErrorType()
                + "，可重试=" + e.isRetryable());
    }

    /** 场景五：退避序列，展示为什么要等以及抖动的作用。 */
    private static void demoBackoffSequence() {
        System.out.println("=== 场景五：指数退避与抖动 ===");

        // 固定随机种子，让演示输出可复现。
        RetryingModelClient client = new RetryingModelClient(
                new AlwaysRateLimitedClient(), 5, 500, 8000, Sleeper.REAL, new Random(42));

        System.out.println("base=500ms，上限 8000ms，每次再乘 [0.5,1.0) 抖动系数：");
        for (int attempt = 1; attempt <= 5; attempt++) {
            System.out.println("  第 " + attempt + " 次失败后等待约 "
                    + client.computeDelay(attempt) + "ms");
        }
        System.out.println("要点：不等待地重试会让被限流的服务端更忙。");
        System.out.println("     抖动把多个客户端的重试时间打散，避免同时重试形成新尖峰。");
        System.out.println();
    }

    /** 场景六：真实调用。没有配置时明确跳过。 */
    private static void demoRealCallIfConfigured() {
        System.out.println("=== 场景六：真实模型调用 ===");

        ModelSettings settings;
        try {
            // 走 .env + 环境变量的合并入口，不是只看环境变量。
            settings = ModelSettings.fromEnvironmentOrDotEnv();
        } catch (ConfigurationException e) {
            System.out.println("跳过真实调用：" + e.getMessage());
            System.out.println();
            System.out.println("要运行这一步，在 learning/agent-java-learning/.env 里写三行：");
            System.out.println("  OPENAI_BASE_URL=https://api.deepseek.com");
            System.out.println("  OPENAI_API_KEY=你的密钥");
            System.out.println("  OPENAI_MODEL=deepseek-v4-flash");
            System.out.println("模板见同目录的 .env.example。该文件已被 gitignore，不会提交。");
            System.out.println();
            System.out.println("也可以用环境变量临时覆盖某一项（PowerShell）：");
            System.out.println("  $env:OPENAI_MODEL = 'deepseek-v4-flash'");
            System.out.println("环境变量优先级高于 .env，和 python-dotenv 的默认行为一致。");
            System.out.println();
            System.out.println("这是「明确跳过」，不是「测试通过」。");
            System.out.println("密钥只从 .env 或环境变量读取，不要写进代码或提交 Git。");
            return;
        }

        System.out.println("已读取配置：" + settings);

        // 真实客户端外面套一层退避重试，业务代码完全不知道这件事。
        ModelClient httpClient = new HttpModelClient(settings, 10000, 60000);
        ModelClient withRetry = new RetryingModelClient(httpClient, 3, 500, 8000);

        // 关键：第 1 课写的业务类一行没改，只是换了注入的实现。
        SceneSummaryService service = new SceneSummaryService(withRetry, settings.getModel(), 1);

        try {
            String summary = service.summarize(
                    "在北侧生成一台雷达，并在东南角放置两台摄像头用于周界监控。");
            System.out.println("模型返回：" + summary);
            System.out.println("Token 消耗：" + service.getTotalTokens()
                    + "（输入 " + service.getTotalPromptTokens()
                    + " + 输出 " + service.getTotalCompletionTokens() + "）");
            System.out.println("要点：SceneSummaryService 是第 1 课的类，一行都没改。");
            System.out.println("     这就是那层 ModelClient 接口的回报。");
        } catch (ModelException e) {
            System.out.println("调用失败：" + e.getMessage());
            System.out.println("错误分类：" + e.getErrorType() + "，可重试=" + e.isRetryable());
            System.out.println("requestId=" + e.getRequestId() + "（排查时提供给服务商）");
        }
    }

    private static java.util.Map<String, String> sampleConfig() {
        java.util.Map<String, String> values = new java.util.HashMap<String, String>();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com");
        values.put("OPENAI_API_KEY", "sk-fake-key-for-demo");
        values.put("OPENAI_MODEL", "deepseek-v4-flash");
        return values;
    }

    /** 演示退避用的桩：永远返回限流。 */
    private static class AlwaysRateLimitedClient implements ModelClient {
        @Override
        public ChatResponse chat(ChatRequest request) {
            throw new ModelException(ModelException.ErrorType.RATE_LIMIT, "429");
        }
    }
}
