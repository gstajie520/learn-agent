package learn.agent.llm.lesson02;

import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 配置读取与校验的测试。
 *
 * <p>测试目标：证明配置错误在<b>启动阶段</b>就能被发现，而不是等第一次
 * 调用模型才暴露。覆盖的规则：</p>
 *
 * <ul>
 *   <li>缺失字段一次性全部报出，不是发现一个就抛；</li>
 *   <li>base_url 必须是 http/https 根地址；</li>
 *   <li>base_url 不能是完整端点（把 {@code /chat/completions} 当根地址是真实的坑）；</li>
 *   <li>端点拼接结果和 Python 章节一致；</li>
 *   <li>{@code toString()} 不泄露密钥。</li>
 * </ul>
 */
public class ModelSettingsTest {

    /** 必填项缺失要一次全报出来：遇到第一个就抛的话，配齐三个变量得启动三次、每次只拿到一条线索。 */
    @Test
    public void shouldReportAllMissingFieldsAtOnce() {
        // Arrange：三个必填项全都没配。
        Map<String, String> empty = new HashMap<String, String>();

        // Act：应当抛出配置异常。
        ConfigurationException exception = assertThrows(
                ConfigurationException.class,
                () -> ModelSettings.fromMap(empty)
        );

        // Assert：三个字段一次性全部报出。
        // 逐个报错的话，运维要改三次、重启三次才能起来。
        assertEquals(3, exception.getInvalidFields().size());
        assertTrue(exception.getInvalidFields().contains("OPENAI_BASE_URL"));
        assertTrue(exception.getInvalidFields().contains("OPENAI_API_KEY"));
        assertTrue(exception.getInvalidFields().contains("OPENAI_MODEL"));
    }

    /** 空白值等同缺失：只判 {@code null} 的话，{@code OPENAI_API_KEY=} 这种空值会带着空 Authorization 头发出去，换回一个分不清「没配」还是「配错」的 401。 */
    @Test
    public void shouldTreatBlankValuesAsMissing() {
        // Arrange：变量存在但只有空格。这在 .env 文件里非常常见。
        Map<String, String> blank = new HashMap<String, String>();
        blank.put("OPENAI_BASE_URL", "   ");
        blank.put("OPENAI_API_KEY", "");
        blank.put("OPENAI_MODEL", "\t");

        // Act + Assert：空白等同于缺失，不能让空字符串一路传到 HTTP 头里。
        ConfigurationException exception = assertThrows(
                ConfigurationException.class,
                () -> ModelSettings.fromMap(blank)
        );
        assertEquals(3, exception.getInvalidFields().size());
    }

    /** {@code OPENAI_BASE_URL} 必须是根地址：照抄文档里的完整端点会拼成 {@code .../chat/completions/chat/completions}，而那个 404 的响应体往往写着「模型不存在」，把排查方向带偏到模型名和账号权限上。 */
    @Test
    public void shouldRejectFullEndpointAsBaseUrl() {
        // Arrange：把完整端点误当根地址配进去。
        Map<String, String> values = validValues();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com/chat/completions");

        // Act + Assert：必须拦住。
        // 不拦的话会拼成 .../chat/completions/chat/completions，服务端返回 404，
        // 而错误信息看起来像模型不存在，排查方向会完全跑偏。
        ConfigurationException exception = assertThrows(
                ConfigurationException.class,
                () -> ModelSettings.fromMap(values)
        );
        assertTrue(exception.getInvalidFields().contains("OPENAI_BASE_URL"));
    }

    /** 结尾斜杠不能绕过端点校验：不先去掉斜杠再比较，就会出现「同事的配置报错、我的不报错，但两个人都是 404」这种最难解释的情况。 */
    @Test
    public void shouldRejectFullEndpointWithTrailingSlash() {
        // Arrange：同样的错误，但结尾多一个斜杠。
        Map<String, String> values = validValues();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com/chat/completions/");

        // Act + Assert：去掉结尾斜杠后仍然要识别出来。
        assertThrows(
                ConfigurationException.class,
                () -> ModelSettings.fromMap(values)
        );
    }

    /** 只接受 http/https：{@code ftp://} 能通过「像个 URL」的粗略检查，于是服务启动成功、健康检查通过，直到第一个真实用户触发调用才在网络层抛出一个和配置毫无字面联系的异常。 */
    @Test
    public void shouldRejectNonHttpScheme() {
        // Arrange：协议不是 http/https。
        Map<String, String> values = validValues();
        values.put("OPENAI_BASE_URL", "ftp://api.deepseek.com");

        // Act + Assert：只接受 http 和 https。
        assertThrows(
                ConfigurationException.class,
                () -> ModelSettings.fromMap(values)
        );
    }

    /** 漏写协议要在启动时拒绝：{@code api.deepseek.com} 在人眼里是完整地址，在 {@link java.net.URL} 眼里不是，不拦的话 {@code MalformedURLException} 会等到第一次真实调用才出现，预发没人手跑就一路带到生产。 */
    @Test
    public void shouldRejectUrlWithoutScheme() {
        // Arrange：漏写协议，只有域名。
        Map<String, String> values = validValues();
        values.put("OPENAI_BASE_URL", "api.deepseek.com");

        // Act + Assert：没有协议无法发起请求，启动时就该拒绝。
        assertThrows(
                ConfigurationException.class,
                () -> ModelSettings.fromMap(values)
        );
    }

    /** 同一字段只报一次：缺失后不跳过格式校验，错误列表会变成「OPENAI_BASE_URL, OPENAI_BASE_URL」，读的人以为是两个配置项或者还有一处没改。 */
    @Test
    public void shouldReportBaseUrlOnceWhenBothMissingAndInvalid() {
        // Arrange：baseUrl 缺失，另外两项正常。
        Map<String, String> values = new HashMap<String, String>();
        values.put("OPENAI_API_KEY", "sk-test");
        values.put("OPENAI_MODEL", "deepseek-v4-flash");

        // Act：baseUrl 为空时只按「缺失」报一次。
        ConfigurationException exception = assertThrows(
                ConfigurationException.class,
                () -> ModelSettings.fromMap(values)
        );

        // Assert：不能既报「缺失」又报「格式错误」，同一个字段重复出现会让人困惑。
        assertEquals(1, exception.getInvalidFields().size());
        assertEquals("OPENAI_BASE_URL", exception.getInvalidFields().get(0));
    }

    /** 只追加 {@code /chat/completions} 而不加 {@code /v1}：{@code /v1} 属于用户配的 base_url，多加三个字符就会让同一份 {@code .env} 在 Python 跑得通、在 Java 返回 404，而这种差异极难归因。 */
    @Test
    public void shouldBuildChatCompletionsUrlSameAsPython() {
        // Arrange：和 python/.env.example 里一样的根地址。
        ModelSettings settings = ModelSettings.fromMap(validValues());

        // Act + Assert：端点必须和 Python 章节完全一致。
        // OpenAI SDK 对 base_url 追加的是 /chat/completions，没有 /v1。
        // 这里多加一个 /v1，同一份 .env 在 Python 能跑、在 Java 会 404。
        assertEquals("https://api.deepseek.com/chat/completions", settings.getChatCompletionsUrl());
    }

    /** 根地址带不带结尾斜杠都要拼出同一个端点：直接字符串相加会产生双斜杠，多数服务器会归一化、但网关和签名校验按字面路径匹配，于是同样的代码在一个环境正常、另一个环境 404，而双斜杠在日志里很不显眼。 */
    @Test
    public void shouldHandleTrailingSlashInBaseUrl() {
        // Arrange：根地址结尾带斜杠，这是很常见的手写差异。
        Map<String, String> values = validValues();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com/");
        ModelSettings settings = ModelSettings.fromMap(values);

        // Act + Assert：拼接结果不能出现双斜杠。
        assertEquals("https://api.deepseek.com/chat/completions", settings.getChatCompletionsUrl());
    }

    /** {@code toString()} 只输出密钥长度、不输出原文：配置对象被打印的次数远超预期，密钥一旦进了集中日志平台就等于泄露给所有能看日志的人且无法追溯，只能作废重签并清理全部备份与归档。 */
    @Test
    public void shouldNotLeakApiKeyInToString() {
        // Arrange：一个可识别的假密钥。
        Map<String, String> values = validValues();
        values.put("OPENAI_API_KEY", "sk-super-secret-value-12345");
        ModelSettings settings = ModelSettings.fromMap(values);

        // Act：日志里经常直接打印配置对象。
        String printed = settings.toString();

        // Assert：密钥本身不出现，只暴露长度。
        // 密钥进了日志就等于泄露，日志通常还会被收集到第三方平台。
        assertFalse(printed.contains("sk-super-secret-value-12345"));
        assertTrue(printed.contains("apiKeyLength=27"));

        // Assert：baseUrl 和 model 不敏感，可以打印，便于确认配错了哪个环境。
        assertTrue(printed.contains("https://api.deepseek.com"));
        assertTrue(printed.contains("deepseek-v4-flash"));
    }

    /** 合法配置必须通过，且 {@link ModelSettings} 存在就意味着三个字段非空：只有拒绝测试的话，校验收紧到把正常配置也挡住时全部测试依然全绿，而少了这条不变量业务代码就得处处判空。 */
    @Test
    public void shouldAcceptValidConfiguration() {
        // Arrange + Act：完整正确的配置。
        ModelSettings settings = ModelSettings.fromMap(validValues());

        // Assert：构造成功后三个字段一定非空，业务代码不必再判空。
        assertEquals("https://api.deepseek.com", settings.getBaseUrl());
        assertEquals("sk-test-key", settings.getApiKey());
        assertEquals("deepseek-v4-flash", settings.getModel());
    }

    /** 一份合法配置，各测试按需覆盖其中某一项。 */
    private Map<String, String> validValues() {
        Map<String, String> values = new HashMap<String, String>();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com");
        values.put("OPENAI_API_KEY", "sk-test-key");
        values.put("OPENAI_MODEL", "deepseek-v4-flash");
        return values;
    }
}
