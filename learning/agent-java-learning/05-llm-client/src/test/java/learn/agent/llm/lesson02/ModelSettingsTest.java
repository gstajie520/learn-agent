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

    /**
     * 规则：三个必填项全部缺失时，一次把三个字段名都报出来，而不是发现一个就抛。
     *
     * <p><b>为什么重要：</b>配置校验是「批量收集错误再一起抛」的典型场景。
     * 学习者第一次跑这个模块时，{@code .env} 通常一个变量都没配。
     * 如果实现是「遇到第一个缺失就 throw」，他要启动三次、每次改一个变量，
     * 才能凑齐一份可用配置。Spring 的配置绑定校验就是按这个思路做的：
     * 先遍历完所有字段收集到一个列表，最后统一抛出。</p>
     *
     * <p><b>违反会怎样：</b>排错变成一场猜谜。每次启动只得到一条线索，
     * 改完再启动又冒出新的一条。在容器环境里一次启动要几十秒，
     * 三轮下来就是几分钟的无谓等待——而这些信息第一次就能全部拿到。</p>
     */
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

    /**
     * 规则：只有空格、空串、制表符的值，一律按「缺失」处理，不能当成有效配置。
     *
     * <p><b>为什么重要：</b>{@code .env} 文件里写 {@code OPENAI_API_KEY=} 后面什么都不填，
     * 是极其常见的一种状态——占位行还没删、或者密钥被从共享文件里抹掉了。
     * 这时环境变量确实<b>存在</b>，只是值为空串。如果校验只判 {@code null}，
     * 这份配置会顺利通过，然后带着一个空的 Authorization 头发出真实请求。</p>
     *
     * <p><b>违反会怎样：</b>拿到一个语义不明的 401。「密钥没配」和「密钥配错了」
     * 是两个完全不同的问题，前者改 {@code .env} 就行，后者要去供应商后台查。
     * 但服务端返回的 401 对两者一视同仁，排查时只能从零开始猜。
     * 这类问题在启动阶段就能挡住，代价只是一次 {@code trim().isEmpty()}。</p>
     */
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

    /**
     * 规则：{@code OPENAI_BASE_URL} 必须是根地址，填成完整端点要在启动时就被拒绝。
     *
     * <p><b>为什么重要：</b>这是本课最值得记住的一条。客户端会自己在 base_url
     * 后面追加 {@code /chat/completions}，所以配置里只该写
     * {@code https://api.deepseek.com}。注意追加的是 {@code /chat/completions}
     * 而不是 {@code /v1/chat/completions}——{@code /v1} 属于 base_url 的一部分。
     * 供应商文档里给的示例常常是完整端点，照抄进 {@code .env} 是很自然的动作。</p>
     *
     * <p><b>违反会怎样：</b>拼出
     * {@code .../chat/completions/chat/completions}，服务端返回 404。
     * 麻烦的是这个 404 的响应体往往写着「模型不存在」或类似措辞，
     * 于是排查方向变成换模型名、查账号权限，而真正的问题在配置的一行地址上。
     * 这条校验也保证 Java 和 {@code python/ch01_agent} 共用同一份 {@code .env}
     * 时行为一致。</p>
     */
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

    /**
     * 规则：完整端点后面多一个结尾斜杠，同样要识别出来。
     *
     * <p><b>为什么重要：</b>校验逻辑通常写成「判断地址是否以
     * {@code /chat/completions} 结尾」。手写配置时在末尾多敲一个斜杠、
     * 或从浏览器地址栏复制时被自动补上斜杠，都很常见。
     * 校验必须先去掉结尾斜杠再比较，否则这条规则会被一个字符绕过。</p>
     *
     * <p><b>违反会怎样：</b>出现「同事的配置报错了，我的没报错，
     * 但两个人都是 404」这种最难解释的情况。校验规则一旦存在例外，
     * 学习者会怀疑校验本身不可信，进而绕过它。</p>
     */
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

    /**
     * 规则：协议只接受 {@code http} 和 {@code https}，其他一律拒绝。
     *
     * <p><b>为什么重要：</b>把配置错误挡在启动阶段，而不是等到运行时。
     * {@code ftp://} 或 {@code file://} 这类地址通常来自复制粘贴事故，
     * 但它们能通过「像个 URL」的粗略检查。真正调用时抛出的是
     * {@code UnknownServiceException} 之类的底层异常，
     * 和「配置写错了」之间没有任何字面联系。</p>
     *
     * <p><b>违反会怎样：</b>服务启动成功、健康检查通过，直到第一个真实用户
     * 触发模型调用才失败。而且异常发生在网络层，堆栈里只有 JDK 的类，
     * 看不到是哪个配置项的问题。启动即失败要好得多：至少部署时就能发现。</p>
     */
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

    /**
     * 规则：漏写协议、只有域名的地址要被拒绝。
     *
     * <p><b>为什么重要：</b>{@code api.deepseek.com} 在人眼里是个完整地址，
     * 在 {@link java.net.URL} 眼里不是。日常口头交流和文档里都省略
     * {@code https://}，所以照着说的内容填配置，很容易漏掉协议头。</p>
     *
     * <p><b>违反会怎样：</b>拼接出的字符串是
     * {@code api.deepseek.com/chat/completions}，构造 URL 时抛
     * {@code MalformedURLException: no protocol}。这条消息本身还算清楚，
     * 但它出现在第一次调用模型的时候，而不是启动的时候——
     * 在预发环境没人手动跑一次调用的情况下，问题会一路带到生产。</p>
     */
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

    /**
     * 规则：同一个字段在错误列表里只能出现一次，即使它同时触发了多条校验。
     *
     * <p><b>为什么重要：</b>{@code OPENAI_BASE_URL} 缺失时，它既满足「必填项为空」，
     * 也满足「不是合法的 http 地址」。两条校验都执行的话，同一个字段名会被加进列表两次。
     * 正确做法是缺失就直接报「缺失」并跳过格式校验——空值的格式错误是缺失的必然结果，
     * 不是一个独立问题。</p>
     *
     * <p><b>违反会怎样：</b>错误信息变成「OPENAI_BASE_URL, OPENAI_BASE_URL」，
     * 读的人会以为是两个不同的配置项，或者以为自己改了一处还有另一处没改。
     * 配好之后两条错误一起消失，更让人怀疑校验逻辑有问题。
     * 一份可信的错误列表，字段数就应该等于要改的地方数。</p>
     */
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

    /**
     * 规则：{@code getChatCompletionsUrl()} 只在根地址后追加 {@code /chat/completions}，
     * 不加 {@code /v1}。
     *
     * <p><b>为什么重要：</b>本仓库的 Java 版和 {@code python/ch01_agent} 共用同一份
     * {@code .env}，所以两边必须拼出完全相同的端点。OpenAI SDK 的做法是：
     * {@code /v1} 属于 {@code base_url} 的一部分（由用户配置），SDK 只负责追加
     * {@code /chat/completions}。Java 这边多加一个 {@code /v1}，
     * 就和这个约定分道扬镳了。</p>
     *
     * <p><b>违反会怎样：</b>同一份 {@code .env}，Python 跑得通、Java 返回 404。
     * 这种「换个语言就不好用」的差异极难归因：学习者会去怀疑密钥、怀疑模型名、
     * 怀疑网络，很少会想到是端点多了三个字符。</p>
     */
    @Test
    public void shouldBuildChatCompletionsUrlSameAsPython() {
        // Arrange：和 python/.env.example 里一样的根地址。
        ModelSettings settings = ModelSettings.fromMap(validValues());

        // Act + Assert：端点必须和 Python 章节完全一致。
        // OpenAI SDK 对 base_url 追加的是 /chat/completions，没有 /v1。
        // 这里多加一个 /v1，同一份 .env 在 Python 能跑、在 Java 会 404。
        assertEquals("https://api.deepseek.com/chat/completions", settings.getChatCompletionsUrl());
    }

    /**
     * 规则：根地址结尾带不带斜杠，拼出来的端点必须一样。
     *
     * <p><b>为什么重要：</b>{@code https://api.deepseek.com} 和
     * {@code https://api.deepseek.com/} 在人的理解里是同一个地址，
     * 所以配置里两种写法都会出现。字符串直接相加的话，后者会拼出
     * {@code https://api.deepseek.com//chat/completions}。
     * 这属于「合法但要靠对方宽容」的 URL：多数服务器会归一化处理，
     * 但反向代理、网关、签名校验都可能按字面路径匹配。</p>
     *
     * <p><b>违反会怎样：</b>产生一类间歇性故障——同样的代码，
     * 在某个环境正常、在另一个环境 404，唯一差别是 {@code .env} 里那个斜杠。
     * 由于双斜杠在日志里很不显眼，这种问题往往要盯着 URL 看很久才发现。</p>
     */
    @Test
    public void shouldHandleTrailingSlashInBaseUrl() {
        // Arrange：根地址结尾带斜杠，这是很常见的手写差异。
        Map<String, String> values = validValues();
        values.put("OPENAI_BASE_URL", "https://api.deepseek.com/");
        ModelSettings settings = ModelSettings.fromMap(values);

        // Act + Assert：拼接结果不能出现双斜杠。
        assertEquals("https://api.deepseek.com/chat/completions", settings.getChatCompletionsUrl());
    }

    /**
     * 规则：{@code toString()} 绝不能包含密钥原文，只输出密钥长度。
     *
     * <p><b>为什么重要：</b>配置对象被打印的次数远超预期：启动时打一次确认加载成功、
     * 异常堆栈里带上上下文、调试时随手 {@code log.debug(settings)}。
     * 而日志会被收集到集中平台、长期留存、被整个团队甚至外部支持人员查看。
     * 密钥一旦写进日志，就等于泄露给了所有能看日志的人，
     * 而且无法追溯谁看过。保留长度是有意的取舍：足够区分「密钥没配」
     * 和「密钥配错了」，又不泄露任何一个字符。</p>
     *
     * <p><b>违反会怎样：</b>只能作废密钥并重新签发，同时把受影响的日志全部清理干净
     * ——日志备份、归档、第三方平台的索引，一处不漏。相比之下，
     * {@code baseUrl} 和 {@code model} 不敏感，照常打印，
     * 这样才能一眼看出连的是哪个环境。</p>
     */
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

    /**
     * 规则：合法配置必须顺利通过，且构造成功后三个字段一定非空。
     *
     * <p><b>为什么重要：</b>前面九个测试都在验证「什么会被拒绝」，
     * 这一个验证「什么会被接受」。只有拒绝测试的校验逻辑有个隐蔽的失败模式：
     * 写得过于严格，把正常配置也挡住了，而所有拒绝测试依然全绿。
     * 另一半价值在于确立一条不变量——{@link ModelSettings} 存在，
     * 就意味着三个字段都有值。</p>
     *
     * <p><b>违反会怎样：</b>缺了正向测试，可能收紧校验后才在启动时发现配置全被拒；
     * 缺了这条不变量，业务代码就得在每个用到配置的地方判空，
     * 校验也就失去了意义——集中校验一次的目的，正是让后面的代码可以放心用。</p>
     */
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
