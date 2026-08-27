package learn.agent.llm.lesson02;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.File;
import java.io.IOException;
import java.nio.charset.Charset;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@code .env} 加载与配置合并的测试。
 *
 * <p>这些测试<b>不读真实的 {@code .env}</b>，全部用临时文件和显式传入的 Map。
 * 原因：真实文件的存在与否取决于机器，依赖它的测试会「在我这儿过、在你那儿挂」，
 * 而且一旦有人往 {@code .env} 里多加一行就可能弄坏测试。</p>
 *
 * <p>本类要钉住两组规则：<b>解析</b>（哪些行算配置、引号怎么处理）
 * 和<b>优先级</b>（环境变量覆盖 {@code .env}）。后者尤其重要 ——
 * 写反了不会报错，只会在某天悄悄用错密钥。</p>
 */
public class EnvFileTest {

    /** 临时目录，由 JUnit 在每个测试后自动清理。 */
    @TempDir
    File tempDir;

    /**
     * 规则：{@code KEY=value} 形式的行必须被解析出来，键和值都去掉首尾空格。
     *
     * <p><b>为什么重要：</b>这是整个配置链路的地基。{@link ModelSettings} 之后所有的
     * 校验、拼接端点、判断「配了没」，都建立在「文件确实被读进来了」之上。
     * 手写的 {@code .env} 里在等号两边留空格是极常见的习惯
     * （{@code OPENAI_MODEL = deepseek}），如果不 trim，值就会带上前导空格。</p>
     *
     * <p><b>违反会怎样：</b>值带上不可见的空格后，模型名变成 {@code " deepseek-v4-flash"}，
     * 服务端返回「模型不存在」。而人肉眼看 {@code .env} 完全正确，
     * 报错信息也不会显示引号，于是怀疑方向全跑偏到密钥和网络上去。
     * 密钥带空格更隐蔽，直接表现为 401，会被当成密钥失效。</p>
     */
    @Test
    public void shouldParseKeyValueAndTrimSpaces() throws IOException {
        // Arrange：故意在等号两边、行首都留空格。
        File file = write("  OPENAI_MODEL = deepseek-v4-flash  \nOPENAI_BASE_URL=https://api.deepseek.com\n");

        // Act
        Map<String, String> values = EnvFile.loadFrom(file);

        // Assert：空格被去掉，两行都读到了。
        assertEquals("deepseek-v4-flash", values.get("OPENAI_MODEL"));
        assertEquals("https://api.deepseek.com", values.get("OPENAI_BASE_URL"));
        assertEquals(2, values.size());
    }

    /**
     * 规则：以 {@code #} 开头的注释行和空行必须被跳过，不能变成配置项。
     *
     * <p><b>为什么重要：</b>{@code .env} 里写注释说明每一项是什么，是让配置可维护的
     * 基本手段（{@code .env.example} 整份文件几乎都是注释）。
     * 注释行里通常还包含 {@code =}，比如
     * {@code # OPENAI_MODEL=可选值见文档}，正好会被朴素的解析器当成真配置。</p>
     *
     * <p><b>违反会怎样：</b>被注释掉的那一行反而生效了。典型场景：有人把旧的
     * {@code # OPENAI_BASE_URL=http://old-proxy} 注释保留在文件里作为记录，
     * 结果程序一直在往那个已下线的旧地址发请求 —— 而当前生效的正确行明明就在下面。
     * 这类问题几乎不可能靠读代码发现，只能靠打印最终配置才看得出来。</p>
     */
    @Test
    public void shouldSkipCommentsAndBlankLines() throws IOException {
        // Arrange：注释行里也带等号，这是最容易被误解析的形态。
        File file = write("# OPENAI_BASE_URL=http://old-proxy\n"
                + "\n"
                + "   \n"
                + "OPENAI_MODEL=deepseek-v4-flash\n"
                + "# 下面这行是历史遗留，别删\n");

        // Act
        Map<String, String> values = EnvFile.loadFrom(file);

        // Assert：只有真正的那一行生效。
        assertEquals(1, values.size());
        assertEquals("deepseek-v4-flash", values.get("OPENAI_MODEL"));
        assertNull(values.get("OPENAI_BASE_URL"), "被注释掉的行绝不能生效");
    }

    /**
     * 规则：值只在首尾<b>成对</b>出现引号时才剥壳。
     *
     * <p><b>为什么重要：</b>{@code .env} 里给值加引号是常见写法（尤其值里有空格时），
     * 而引号是语法不是内容。但「无脑剥掉首尾字符」会误伤值本身就以引号结尾的情况。
     * 成对判断是这两个需求唯一的兼容方式。</p>
     *
     * <p><b>违反会怎样：</b>不剥引号，密钥就变成 {@code "sk-abc"}（带引号字符）
     * 发给服务端，稳定 401；无脑剥则会把合法密钥的首尾字符吃掉一个，
     * 同样是 401。两种错法都指向「密钥无效」，而人对着文件反复核对密钥，
     * 每次都确认「没错啊」——因为错的不是密钥，是解析。</p>
     */
    @Test
    public void shouldStripOnlyPairedQuotes() throws IOException {
        // Arrange：三种形态 —— 双引号成对、单引号成对、引号不成对。
        File file = write("A=\"sk-double\"\n"
                + "B='sk-single'\n"
                + "C=sk-ends-with-quote\"\n");

        // Act
        Map<String, String> values = EnvFile.loadFrom(file);

        // Assert：成对的剥掉，不成对的原样保留。
        assertEquals("sk-double", values.get("A"));
        assertEquals("sk-single", values.get("B"));
        assertEquals("sk-ends-with-quote\"", values.get("C"), "引号不成对时不能剥");
    }

    /**
     * 规则：只按<b>第一个</b>等号切分，值里后续的等号属于值本身。
     *
     * <p><b>为什么重要：</b>密钥和 token 经常是 Base64 编码的，而 Base64 用
     * {@code =} 做尾部填充（{@code abc==}）。URL 里带查询参数时也会有等号
     * （{@code https://host/api?version=v1}）。按最后一个等号切、
     * 或者按等号 split 成数组再取 {@code [1]}，都会把这些值截断。</p>
     *
     * <p><b>违反会怎样：</b>Base64 密钥的尾部填充被切掉，得到一个长度对不上的
     * 残缺密钥，服务端返回 401。这是最难排查的一类：密钥「看起来」是对的，
     * 复制粘贴进 curl 却能用 —— 因为 curl 没经过这段解析。
     * 结论会被错误地引向「Java 客户端有问题」而不是「配置解析有问题」。</p>
     */
    @Test
    public void shouldSplitOnFirstEqualsOnly() throws IOException {
        // Arrange：Base64 尾部填充 + URL 查询参数，都含额外等号。
        File file = write("OPENAI_API_KEY=c2stYWJjZGVm==\n"
                + "OPENAI_BASE_URL=https://api.example.com/v1?flavor=openai\n");

        // Act
        Map<String, String> values = EnvFile.loadFrom(file);

        // Assert：等号后面的内容一个字符都不能丢。
        assertEquals("c2stYWJjZGVm==", values.get("OPENAI_API_KEY"));
        assertEquals("https://api.example.com/v1?flavor=openai", values.get("OPENAI_BASE_URL"));
    }

    /**
     * 规则：兼容 shell 习惯的 {@code export KEY=value}；没有等号的行整行忽略。
     *
     * <p><b>为什么重要：</b>很多人的 {@code .env} 是从 shell 脚本或
     * {@code ~/.bashrc} 里直接拷过来的，带着 {@code export} 前缀。
     * 反过来，没有等号的行（散落的说明文字、误粘贴的命令）不是配置，
     * 必须整行丢弃而不是猜一个空值出来。</p>
     *
     * <p><b>违反会怎样：</b>不处理 {@code export}，键名会变成
     * {@code "export OPENAI_API_KEY"}，于是 {@code OPENAI_API_KEY} 查不到，
     * 程序报「未配置」——但文件里那一行明明写着密钥，人会以为加载器根本没工作。
     * 反向上，如果给无等号的行猜一个空值，就会凭空多出一个空配置项，
     * 让「配了但是空的」和「没配」两种状态混在一起。</p>
     */
    @Test
    public void shouldSupportExportPrefixAndIgnoreLinesWithoutEquals() throws IOException {
        // Arrange
        File file = write("export OPENAI_MODEL=deepseek-v4-flash\n"
                + "这一行是随手写的说明，没有等号\n"
                + "=没有键名的行也要丢掉\n");

        // Act
        Map<String, String> values = EnvFile.loadFrom(file);

        // Assert：只留下那一条真配置。
        assertEquals(1, values.size());
        assertEquals("deepseek-v4-flash", values.get("OPENAI_MODEL"));
    }

    /**
     * 规则：文件不存在时返回<b>空 Map</b>，不抛异常。
     *
     * <p><b>为什么重要：</b>没有 {@code .env} 是完全正常的部署形态 ——
     * 容器和 CI 只用真实环境变量，镜像里本来就不该有这个文件。
     * 「缺配置」的判断和报错属于 {@link ModelSettings} 的职责，
     * 加载器只负责「文件里有什么」，两件事不能混。</p>
     *
     * <p><b>违反会怎样：</b>加载器一抛异常，所有离线测试和不需要密钥的
     * 演示代码都会在没有 {@code .env} 的机器上直接崩掉，
     * 而它们本来根本不关心模型配置。更糟的是异常信息会变成
     * 「找不到 .env」，把「你少配了 OPENAI_API_KEY」这个真正有用的提示
     * 挤掉，引导人去创建一个其实不需要的文件。</p>
     */
    @Test
    public void shouldReturnEmptyMapWhenFileMissing() {
        // Arrange：一个确定不存在的路径。
        File missing = new File(tempDir, "definitely-absent.env");

        // Act
        Map<String, String> values = EnvFile.loadFrom(missing);

        // Assert：空 Map 而不是异常，也不是 null。
        assertTrue(values.isEmpty());
    }

    /**
     * 规则：文件固定按 UTF-8 解码，不跟随平台默认编码。
     *
     * <p><b>为什么重要：</b>Windows 的 {@code file.encoding} 默认是 GBK，
     * Linux 是 UTF-8。如果解析时用平台默认编码，同一份文件在两地解析结果不同。
     * {@code .env} 里的注释是中文（本仓库就是），值里也可能出现非 ASCII。</p>
     *
     * <p><b>违反会怎样：</b>中文注释按 GBK 解码 UTF-8 字节会变成乱码。
     * 单纯乱码还算好，真正的风险是乱码后的字节序列里可能<b>不再包含</b>
     * 原本的 {@code #}，或者反过来多出一个 {@code =}，于是注释行被当成配置行解析，
     * 凭空注入一个垃圾键值。这类故障只在特定机器上出现，
     * 在 CI 上永远复现不出来。</p>
     */
    @Test
    public void shouldReadFileAsUtf8() throws IOException {
        // Arrange：中文注释 + 中文值，用 UTF-8 字节写入。
        File file = write("# 模型服务地址（生产环境）\nREMARK=测试值\n");

        // Act
        Map<String, String> values = EnvFile.loadFrom(file);

        // Assert：中文值完整，中文注释没有变成配置项。
        assertEquals("测试值", values.get("REMARK"));
        assertEquals(1, values.size());
    }

    /**
     * 规则：同名配置项，<b>操作系统环境变量覆盖 {@code .env}</b>。
     *
     * <p><b>为什么重要：</b>这是本课最不能写反的一条。和
     * {@code python-dotenv} 的 {@code load_dotenv()} 默认行为一致，
     * 所以 Python 和 Java 两侧对同一份配置的解释是一样的。
     * 现实用法上，它让人可以不改文件就临时切换模型
     * （{@code $env:OPENAI_MODEL = '...'} 跑一次测试）。</p>
     *
     * <p><b>违反会怎样：</b>方向写反的后果不是报错，是<b>静默用错配置</b>。
     * 线上容器通过环境变量注入生产密钥，如果镜像里不小心打进了一个开发用的
     * {@code .env}，反向优先级会让生产流量一直走开发密钥 ——
     * 服务正常返回、日志没有任何异常，只有账单和调用来源对不上。
     * 等发现时已经跑了很久，而且无法从代码里看出问题，
     * 因为「读到了配置」这件事本身是成功的。</p>
     */
    @Test
    public void shouldLetEnvironmentVariableOverrideDotEnv() {
        // Arrange：两个来源给同一个键不同的值。
        Map<String, String> dotEnv = new LinkedHashMap<String, String>();
        dotEnv.put("OPENAI_MODEL", "来自-dotenv");
        dotEnv.put("OPENAI_BASE_URL", "https://from-dotenv.example.com");

        Map<String, String> osEnv = new HashMap<String, String>();
        osEnv.put("OPENAI_MODEL", "来自-环境变量");

        // Act
        Map<String, String> merged = ModelSettings.merge(dotEnv, osEnv);

        // Assert：冲突的键由环境变量胜出，不冲突的键从 .env 保留下来。
        assertEquals("来自-环境变量", merged.get("OPENAI_MODEL"));
        assertEquals("https://from-dotenv.example.com", merged.get("OPENAI_BASE_URL"),
                "环境变量里没有的键，必须保留 .env 的值");
    }

    /**
     * 规则：值为空白的环境变量视为「没配」，不允许它盖掉 {@code .env} 里的真实值。
     *
     * <p><b>为什么重要：</b>「变量存在」和「变量有值」是两件事。
     * 空环境变量的来源很多：{@code $env:OPENAI_API_KEY = ''} 想清除却没清干净、
     * CI 里配置了变量名但秘密注入失败、Docker 的 {@code -e OPENAI_API_KEY}
     * 不带值。这些场景下人的意图都不是「用空密钥」。</p>
     *
     * <p><b>违反会怎样：</b>一个空环境变量会让 {@code .env} 里配好的密钥凭空消失，
     * 程序报「OPENAI_API_KEY 未配置」。这是最令人困惑的一种报错：
     * 文件里明明写着，{@code cat .env} 看得见，加载器也确实读到了 ——
     * 但被一个看不见、且 {@code echo} 出来是空行的环境变量盖掉了。
     * 排查时几乎不会有人想到去查一个空的环境变量。</p>
     */
    @Test
    public void shouldNotLetBlankEnvironmentVariableShadowDotEnv() {
        // Arrange：环境变量存在但是空白（空串、纯空格）。
        Map<String, String> dotEnv = new LinkedHashMap<String, String>();
        dotEnv.put("OPENAI_API_KEY", "sk-real-key-from-dotenv");
        dotEnv.put("OPENAI_MODEL", "deepseek-v4-flash");

        Map<String, String> osEnv = new HashMap<String, String>();
        osEnv.put("OPENAI_API_KEY", "");
        osEnv.put("OPENAI_MODEL", "   ");

        // Act
        Map<String, String> merged = ModelSettings.merge(dotEnv, osEnv);

        // Assert：.env 的值必须活下来。
        assertEquals("sk-real-key-from-dotenv", merged.get("OPENAI_API_KEY"));
        assertEquals("deepseek-v4-flash", merged.get("OPENAI_MODEL"));
    }

    /**
     * 规则：合并结果能直接喂给 {@link ModelSettings#fromMap(Map)} 并通过校验。
     *
     * <p><b>为什么重要：</b>前面的测试各自验证了解析和合并，但没有验证
     * 「两段拼起来真的能产出一个可用的配置对象」。这个测试走完
     * {@code .env} 文件 → 解析 → 合并 → 校验 → 拼端点的完整链路，
     * 是对整条路径的一次端到端确认（唯一被替换掉的是操作系统环境变量，
     * 因为进程内改不了它）。</p>
     *
     * <p><b>违反会怎样：</b>各段单测都绿、组装起来却不通，是分层设计最典型的盲区。
     * 比如解析出的键名多了个前缀、或者 {@code trim} 漏在某一层，
     * 单看每一层都「符合自己的规格」，只有端到端才暴露。
     * 缺了这一条，第一次发现问题的时机就会是真实调用返回 401 的时候。</p>
     */
    @Test
    public void shouldProduceUsableSettingsFromDotEnvFile() throws IOException {
        // Arrange：一份形态贴近真实的 .env —— 带中文注释、带引号、带 export。
        File file = write("# 模型服务配置（Python 与 Java 共用）\n"
                + "OPENAI_BASE_URL=\"https://api.deepseek.com\"\n"
                + "export OPENAI_API_KEY=sk-abcdefghijklmn\n"
                + "OPENAI_MODEL = deepseek-v4-flash\n");

        // Act：解析文件，再与一份空的「环境变量」合并，最后走校验。
        Map<String, String> merged = ModelSettings.merge(
                EnvFile.loadFrom(file), new HashMap<String, String>());
        ModelSettings settings = ModelSettings.fromMap(merged);

        // Assert：三项都对，端点拼接正确（不含 /v1，与 Python SDK 一致）。
        assertEquals("https://api.deepseek.com", settings.getBaseUrl());
        assertEquals("sk-abcdefghijklmn", settings.getApiKey());
        assertEquals("deepseek-v4-flash", settings.getModel());
        assertEquals("https://api.deepseek.com/chat/completions",
                settings.getChatCompletionsUrl());

        // toString 只暴露长度，绝不暴露密钥本身。
        assertTrue(settings.toString().contains("apiKeyLength="));
        assertTrue(!settings.toString().contains("sk-abcdefghijklmn"),
                "toString 绝不能打印密钥");
    }

    /** 把内容以 UTF-8 写进临时文件。 */
    private File write(String content) throws IOException {
        File file = new File(tempDir, "test.env");
        Files.write(file.toPath(), content.getBytes(Charset.forName("UTF-8")));
        return file;
    }
}
