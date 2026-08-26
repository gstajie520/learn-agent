package learn.agent.llm.lesson02;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 校验通过后的模型配置。
 *
 * <p>这个类的价值在于「校验一次，后面都不用再判空」。构造完成后，
 * 三个字段一定非空、base_url 一定是合法的 http/https 根地址。
 * 业务代码不需要到处写 {@code if (apiKey == null)}。</p>
 *
 * <p>环境变量名和 {@code python/ch01_agent} 完全一致，这样同一份 {@code .env}
 * 可以同时给 Python 和 Java 使用，不必维护两套配置：</p>
 *
 * <ul>
 *   <li>{@code OPENAI_BASE_URL}：服务根地址，<b>不含</b> {@code /chat/completions}；</li>
 *   <li>{@code OPENAI_API_KEY}：服务商密钥；</li>
 *   <li>{@code OPENAI_MODEL}：默认模型名，例如 {@code deepseek-v4-flash}。</li>
 * </ul>
 *
 * <p><b>密钥绝不允许硬编码、写进日志或提交 Git。</b>本类的
 * {@link #toString()} 特意不打印 key，只打印长度。</p>
 */
public class ModelSettings {

    /** OpenAI 兼容服务根地址，例如 {@code https://api.deepseek.com}。 */
    private final String baseUrl;

    /** 服务商密钥。 */
    private final String apiKey;

    /** 默认模型名称。 */
    private final String model;

    public ModelSettings(String baseUrl, String apiKey, String model) {
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        this.model = model;
    }

    /**
     * 从一个键值映射创建配置，并一次性报告所有问题。
     *
     * <p>为什么一次性收集全部缺失项，而不是发现第一个就抛：
     * 三个变量都没配时，逐个报错要改三次、重启三次。
     * 一次全报出来，运维改一遍就能起来。</p>
     *
     * @param values 配置来源，通常是环境变量
     * @throws ConfigurationException 有字段缺失或 baseUrl 格式非法
     */
    public static ModelSettings fromMap(Map<String, String> values) {
        if (values == null) {
            throw new IllegalArgumentException("values 不能为空");
        }

        List<String> invalid = new ArrayList<String>();
        String baseUrl = trimOrEmpty(values.get("OPENAI_BASE_URL"));
        String apiKey = trimOrEmpty(values.get("OPENAI_API_KEY"));
        String model = trimOrEmpty(values.get("OPENAI_MODEL"));

        if (baseUrl.isEmpty()) {
            invalid.add("OPENAI_BASE_URL");
        }
        if (apiKey.isEmpty()) {
            invalid.add("OPENAI_API_KEY");
        }
        if (model.isEmpty()) {
            invalid.add("OPENAI_MODEL");
        }
        // 只有 baseUrl 有值时才检查格式，否则会把「缺失」重复报成两条。
        if (!baseUrl.isEmpty() && !isValidBaseUrl(baseUrl)) {
            invalid.add("OPENAI_BASE_URL");
        }
        if (!invalid.isEmpty()) {
            throw new ConfigurationException(invalid);
        }
        return new ModelSettings(baseUrl, apiKey, model);
    }

    /** 直接从操作系统环境变量读取，容器和 CI 都用这个入口。 */
    public static ModelSettings fromEnvironment() {
        Map<String, String> env = System.getenv();
        return fromMap(env);
    }

    /**
     * 校验 baseUrl 是否是合法的服务根地址。
     *
     * <p>两条规则：必须是 http/https；<b>不能</b>以 {@code /chat/completions} 结尾。
     * 第二条是真实踩过的坑 —— 把完整端点当根地址配进去，
     * 拼接后会变成 {@code .../chat/completions/chat/completions}，
     * 服务端返回 404，但错误信息看起来像模型不存在，很难排查。</p>
     */
    private static boolean isValidBaseUrl(String baseUrl) {
        try {
            URI uri = new URI(baseUrl);
            String scheme = uri.getScheme();
            if (scheme == null) {
                return false;
            }
            if (!"http".equalsIgnoreCase(scheme) && !"https".equalsIgnoreCase(scheme)) {
                return false;
            }
            if (uri.getHost() == null || uri.getHost().trim().isEmpty()) {
                return false;
            }
            String path = uri.getPath() == null ? "" : uri.getPath();
            // 去掉结尾斜杠再判断，兼容 ".../chat/completions/" 这种写法。
            while (path.endsWith("/")) {
                path = path.substring(0, path.length() - 1);
            }
            return !path.endsWith("/chat/completions");
        } catch (URISyntaxException e) {
            return false;
        }
    }

    private static String trimOrEmpty(String value) {
        return value == null ? "" : value.trim();
    }

    public String getBaseUrl() {
        return baseUrl;
    }

    public String getApiKey() {
        return apiKey;
    }

    public String getModel() {
        return model;
    }

    /**
     * 拼出 Chat Completions 端点地址，自动处理结尾斜杠。
     *
     * <p>这里只追加 {@code /chat/completions}，<b>不</b>追加 {@code /v1}。
     * 原因是要和 Python 章节保持完全一致：OpenAI SDK 收到
     * {@code base_url=https://api.deepseek.com} 时，实际请求的是
     * {@code https://api.deepseek.com/chat/completions}。</p>
     *
     * <p>如果这里多加一个 {@code /v1}，同一份 {@code .env} 在 Python 能跑通、
     * 在 Java 却返回 404，而错误信息看起来像模型不存在 —— 这正是
     * 「两套配置各写一份」会踩的坑。需要 {@code /v1} 的服务商，
     * 应当把它写进 {@code OPENAI_BASE_URL} 本身。</p>
     */
    public String getChatCompletionsUrl() {
        String root = baseUrl;
        while (root.endsWith("/")) {
            root = root.substring(0, root.length() - 1);
        }
        return root + "/chat/completions";
    }

    @Override
    public String toString() {
        // 绝不打印 apiKey 本身；只打印长度，便于确认"配了但可能配错"。
        return "ModelSettings{baseUrl=" + baseUrl
                + ", model=" + model
                + ", apiKeyLength=" + apiKey.length()
                + "}";
    }
}
