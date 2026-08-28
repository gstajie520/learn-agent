package learn.agent.llm.client;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
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
 * <p><b>两个读取入口，别用错</b>：</p>
 *
 * <ul>
 *   <li>{@link #fromEnvironmentOrDotEnv()}：先读工程根目录的 {@code .env}，
 *       再让操作系统环境变量覆盖。<b>本地开发和测试用这个</b>；</li>
 *   <li>{@link #fromEnvironment()}：只读操作系统环境变量。容器 / CI 用这个。</li>
 * </ul>
 *
 * <p><b>密钥绝不允许硬编码、写进日志或提交 Git。</b>本类的
 * {@link #toString()} 特意不打印 key，只打印长度；
 * {@code .env} 已被 {@code learning/agent-java-learning/.gitignore} 忽略。</p>
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

    /** 只从操作系统环境变量读取，不看 {@code .env}。 */
    public static ModelSettings fromEnvironment() {
        Map<String, String> env = System.getenv();
        return fromMap(env);
    }

    /**
     * 从 {@code .env} 文件 + 操作系统环境变量读取，<b>本地开发和测试用这个入口</b>。
     *
     * <p>为什么需要这个方法：{@link System#getenv()} 只读进程环境变量，
     * 不读文件。所以光把配置写进 {@code .env}，
     * {@link #fromEnvironment()} 依然读不到，表现为「文件明明写了却说没配置」。
     * 见 {@link EnvFile} 的说明。</p>
     *
     * <p><b>优先级：操作系统环境变量覆盖 {@code .env}。</b>
     * 和 {@code python-dotenv} 的 {@code load_dotenv()} 默认行为一致。
     * 这个方向不能反 —— CI 和容器靠真实环境变量注入密钥，
     * 如果镜像里不小心带了一个 {@code .env}，反向优先级会让线上悄悄用错密钥。</p>
     *
     * @throws ConfigurationException 两个来源合起来仍有字段缺失或格式非法
     */
    public static ModelSettings fromEnvironmentOrDotEnv() {
        return fromMap(mergedConfiguration());
    }

    /**
     * 合并 {@code .env} 与操作系统环境变量，后者优先。
     *
     * <p>包级可见，供测试和 {@link RealModelCallDemo} 检查「某个变量配了没」，
     * 避免它们各自再写一遍合并逻辑、把优先级写反。</p>
     */
    static Map<String, String> mergedConfiguration() {
        return merge(EnvFile.load(), System.getenv());
    }

    /**
     * 纯函数版的合并，两个来源都由调用方传入。
     *
     * <p>拆出这个方法是为了<b>让优先级可被测试</b>：Java 不能在进程内修改
     * 自己的环境变量，如果合并逻辑直接读 {@link System#getenv()}，
     * 「环境变量覆盖 .env」这条规则就只能写在注释里，无法用测试钉住。
     * 而这恰恰是最不能写反的一条规则。</p>
     *
     * @param fromDotEnv      {@code .env} 里的值，优先级低
     * @param fromEnvironment 操作系统环境变量，优先级高
     */
    static Map<String, String> merge(Map<String, String> fromDotEnv,
                                     Map<String, String> fromEnvironment) {
        Map<String, String> merged = new LinkedHashMap<String, String>();
        if (fromDotEnv != null) {
            merged.putAll(fromDotEnv);
        }
        if (fromEnvironment == null) {
            return merged;
        }

        for (Map.Entry<String, String> entry : fromEnvironment.entrySet()) {
            String value = entry.getValue();
            // 空白的环境变量视为「没配」，不允许它盖掉 .env 里的真实值。
            // 否则一个手滑设成空串的变量会让配置凭空消失，且极难看出原因：
            // 文件里明明写着，程序却报「未配置」。
            if (value != null && !value.trim().isEmpty()) {
                merged.put(entry.getKey(), value);
            }
        }
        return merged;
    }

    /**
     * 查一个配置项的最终值，遵循与 {@link #fromEnvironmentOrDotEnv()} 相同的优先级。
     *
     * @return 值；未配置或为空白时返回 {@code null}
     */
    static String lookup(String name) {
        String value = mergedConfiguration().get(name);
        if (value == null || value.trim().isEmpty()) {
            return null;
        }
        return value.trim();
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
