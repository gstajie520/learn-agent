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

    /** {@code KEY = value} 的键值都要 trim：留着空格，模型名就变成 {@code " deepseek-v4-flash"} 换回一句「模型不存在」，而肉眼看 {@code .env} 完全正确。 */
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

    /** {@code #} 注释行和空行必须跳过：注释里常带等号，朴素解析会让一行留作记录的旧地址反而生效，而正确的那行明明就在下面。 */
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

    /** 只在首尾引号成对时剥壳：不剥则密钥带着引号字符发出去，无脑剥又会吃掉密钥首尾各一个字符，两种错法都表现为 401，让人反复核对一个本来没错的密钥。 */
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

    /** 只按第一个等号切分：Base64 密钥的尾部填充和 URL 查询参数都含额外等号，切错会得到一个长度对不上的残缺密钥，而同一串复制进 curl 却能用，排查方向就被引向「Java 客户端有问题」。 */
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

    /** 兼容 {@code export KEY=value}、无等号的行整行丢弃：不剥 {@code export} 键名会变成 {@code "export OPENAI_API_KEY"}，明明配了却报「未配置」；给无等号的行猜个空值又会混淆「配了但为空」和「没配」。 */
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

    /** 文件缺失返回空 Map 而不抛异常：容器和 CI 里本来就不该有 {@code .env}，一抛异常那些根本不关心模型配置的离线测试全崩，报错还会用「找不到 .env」挤掉「你少配了 OPENAI_API_KEY」。 */
    @Test
    public void shouldReturnEmptyMapWhenFileMissing() {
        // Arrange：一个确定不存在的路径。
        File missing = new File(tempDir, "definitely-absent.env");

        // Act
        Map<String, String> values = EnvFile.loadFrom(missing);

        // Assert：空 Map 而不是异常，也不是 null。
        assertTrue(values.isEmpty());
    }

    /** 固定按 UTF-8 解码而不跟随平台默认编码：用 GBK 解 UTF-8 字节不只是乱码，还可能让原本的 {@code #} 消失或多出一个 {@code =}，把中文注释行注入成垃圾配置，且只在特定机器上复现。 */
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
     * 同名项由操作系统环境变量覆盖 {@code .env}：方向写反不会报错，只会让镜像里误打进的开发用 {@code .env}
     * 静默盖掉注入的生产密钥 —— 服务正常返回、日志干净，只有账单和调用来源对不上。
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

    /** 值为空白的环境变量算「没配」，不能盖掉 {@code .env}：否则 CI 里注入失败留下的空变量会让配好的密钥凭空消失，报「OPENAI_API_KEY 未配置」，而那个变量 {@code echo} 出来只是一行空白，没人会想到去查它。 */
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

    /** 文件 → 解析 → 合并 → 校验 → 拼端点整条链路要通：每层单测都绿、组装起来却不通是分层设计的典型盲区，缺了这条端到端确认，第一次发现问题就是真实调用返回 401 的时候。 */
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
