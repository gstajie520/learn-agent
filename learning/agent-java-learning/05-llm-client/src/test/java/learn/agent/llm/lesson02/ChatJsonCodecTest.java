package learn.agent.llm.lesson02;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatResponse;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.ModelException;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * JSON 编解码测试。
 *
 * <p>这是本课最有价值的测试类，因为它<b>不需要网络也不需要密钥</b>，
 * 却能覆盖真实环境里最难复现的情况：服务端返回畸形 JSON、缺字段、
 * 返回未知的 finish_reason、返回 HTML 错误页。</p>
 *
 * <p>核心立场：服务端响应是<b>不可信边界</b>。文档写了某个字段一定存在，
 * 不等于它真的一定存在 —— 网关故障、版本升级、限流页面都会破坏契约。</p>
 */
public class ChatJsonCodecTest {

    private final ChatJsonCodec codec = new ChatJsonCodec();

    private final ObjectMapper mapper = new ObjectMapper();

    /**
     * 规则：请求 JSON 的字段名和角色值必须用协议规定的写法，不能直接套用 Java 的命名习惯。
     *
     * <p><b>为什么重要：</b>Java 这边叫 {@code maxOutputTokens}、{@code ChatRole.SYSTEM}，
     * 协议那边是 {@code max_tokens}、{@code "system"}。两套命名之间必须有一次显式转换，
     * 因为服务端既不认识驼峰字段名，也不认识大写的角色值。</p>
     *
     * <p><b>违反会怎样：</b>{@code max_tokens} 写成驼峰会被服务端当未知字段直接忽略，
     * 输出长度上限失效，账单按模型愿意写多长来算；角色发成 {@code "SYSTEM"} 好一点是被
     * 拒绝返回 400，坏一点是某些兼容网关静默降级成 {@code user} —— 系统规则变成了
     * 普通用户输入，防提示注入的那道边界就没了。</p>
     */
    @Test
    public void shouldSerializeRequestToExpectedJsonShape() throws IOException {
        // Arrange：一个标准的两条消息请求。
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system("你是场景助手。"));
        messages.add(ChatMessage.user("在北侧生成一台雷达。"));
        ChatRequest request = new ChatRequest("deepseek-v4-flash", messages, 0.2, 200);

        // Act：转成要发送的 JSON。
        JsonNode json = mapper.readTree(codec.toRequestJson(request));

        // Assert：字段名必须是协议要求的下划线风格，不是 Java 的驼峰。
        assertEquals("deepseek-v4-flash", json.get("model").asText());
        assertEquals(0.2, json.get("temperature").asDouble(), 0.0001);
        assertEquals(200, json.get("max_tokens").asInt());

        // Assert：消息顺序保持不变，角色是小写字面值。
        // 直接用 enum.name() 会发出 "SYSTEM"，服务端不认。
        assertEquals(2, json.get("messages").size());
        assertEquals("system", json.get("messages").get(0).get("role").asText());
        assertEquals("你是场景助手。", json.get("messages").get(0).get("content").asText());
        assertEquals("user", json.get("messages").get(1).get("role").asText());
    }

    /**
     * 规则：一次正常响应要同时取到四项信息 —— 正文、结束原因、Token 用量、请求 id。
     *
     * <p><b>为什么重要：</b>只取 {@code content} 是最常见的偷懒写法，但另外三项
     * 各自解决一个具体问题：结束原因决定这段正文能不能用；用量是成本核算的唯一依据；
     * 请求 id 是出问题时唯一能和模型服务方对上的凭证。这条测试锁定了
     * {@link ChatResponse} 的完整形状，后续所有异常分支都是在它的基础上做减法。</p>
     *
     * <p><b>违反会怎样：</b>解析层漏了哪一项，上层就永远拿不到。等到线上要查
     * 「昨天下午那次调用为什么返回半句话」，才发现日志里既没有结束原因也没有请求 id，
     * 只能靠猜。补这类字段往往要改一整条调用链。</p>
     */
    @Test
    public void shouldParseNormalResponse() {
        // Arrange：一段典型的成功响应。
        String body = "{"
                + "\"id\":\"chatcmpl-abc\","
                + "\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"北侧新增一台雷达。\"},"
                + "\"finish_reason\":\"stop\"}],"
                + "\"usage\":{\"prompt_tokens\":120,\"completion_tokens\":18}"
                + "}";

        // Act：解析成内部对象。
        ChatResponse response = codec.parseResponse(body, null);

        // Assert：四项关键信息都正确落位。
        assertEquals("北侧新增一台雷达。", response.getContent());
        assertEquals(FinishReason.STOP, response.getFinishReason());
        assertEquals(120, response.getUsage().getPromptTokens());
        assertEquals(18, response.getUsage().getCompletionTokens());
        assertEquals("chatcmpl-abc", response.getRequestId());
        assertTrue(response.isUsable());
    }

    /**
     * 规则：{@code finish_reason} 为 {@code "length"} 时，解析要成功，但结果必须标成不可用。
     *
     * <p><b>为什么重要：</b>截断不是解析错误，JSON 本身完全合法，正文也是通顺的中文。
     * 解析层的职责是把「这段话没说完」这个事实<b>如实传上去</b>，而不是自己决定拒绝。
     * 判断能不能用交给 {@link ChatResponse#isUsable()}，
     * 让上层业务在一个地方统一处理。</p>
     *
     * <p><b>违反会怎样：</b>如果解析层直接抛异常，那些「宁可要半句也不要报错」的场景
     * （比如流式预览）就没法实现了；反过来如果映射成 {@code STOP}，残句会被当成完整答案
     * 写进数据库或喂给下游解析器 —— 而且事后无法区分是模型答错还是被截断。</p>
     */
    @Test
    public void shouldMapTruncatedFinishReason() {
        // Arrange：正文看起来正常，但 finish_reason 是 length。
        String body = "{"
                + "\"choices\":[{\"message\":{\"content\":\"北侧新增一台雷达，东南角部署\"},"
                + "\"finish_reason\":\"length\"}],"
                + "\"usage\":{\"prompt_tokens\":120,\"completion_tokens\":200}"
                + "}";

        // Act：解析本身应该成功 —— 截断是业务问题，不是解析问题。
        ChatResponse response = codec.parseResponse(body, null);

        // Assert：结束原因正确映射，且判定为不可用。
        // 只看 content 是发现不了这个问题的。
        assertEquals(FinishReason.LENGTH, response.getFinishReason());
        assertFalse(response.isUsable());
    }

    /**
     * 规则：没见过的 {@code finish_reason} 映射成 {@link FinishReason#UNKNOWN}，
     * 既不抛异常，也不当成 {@code STOP}。
     *
     * <p><b>为什么重要：</b>这条规则要同时躲开两个方向的坑，所以比它看起来更难。
     * 服务商加一个新的结束原因是常态（工具调用、推理中断、内容改写都曾这样加进来），
     * 你的代码不会提前知道。为了一个没见过的字符串让整次调用失败，代价太大；
     * 但反过来把它当成正常结束，等于替服务端做了一个你没有依据的乐观假设。</p>
     *
     * <p><b>违反会怎样：</b>选「抛异常」，供应商某天上线新枚举值，你的服务在没有发版的
     * 情况下大面积报错，而日志只会说「未知的 finish_reason」；选「当成 STOP」，
     * 一批实际上异常结束的响应被当成正常结果落库，问题会在下游很远的地方才暴露，
     * 到那时已经查不回是哪次调用出的错。归到 {@code UNKNOWN} 加不可用，
     * 是「不崩溃，但也不装作没事」的中间路线。</p>
     */
    @Test
    public void shouldMapUnknownFinishReasonToUnknownInsteadOfFailing() {
        // Arrange：服务商新增了一个本地没见过的结束原因。
        String body = "{"
                + "\"choices\":[{\"message\":{\"content\":\"内容\"},"
                + "\"finish_reason\":\"some_new_reason\"}],"
                + "\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":5}"
                + "}";

        // Act：不该抛异常。服务商随时可能新增枚举值，
        // 因此解析失败会让整个调用挂掉，代价过大。
        ChatResponse response = codec.parseResponse(body, null);

        // Assert：归为 UNKNOWN，同时判定不可用。
        // 关键是不能当成 STOP —— 那会把异常结束误判成正常完成。
        assertEquals(FinishReason.UNKNOWN, response.getFinishReason());
        assertFalse(response.isUsable());
    }

    /**
     * 规则：{@code content} 是 JSON null 时转成空字符串，不把 null 交给业务层。
     *
     * <p><b>为什么重要：</b>这不是罕见的异常情况，而是协议的正常路径 ——
     * 模型决定调用工具时，{@code content} 就是 null，该看的信息在 {@code tool_calls} 里。
     * 也就是说，只要接了工具调用，这条分支一定会走到。</p>
     *
     * <p><b>违反会怎样：</b>业务层拿到 null 去调 {@code trim()} 或 {@code contains()} 就是
     * 空指针，而且崩的位置离真正的原因很远：堆栈指向某个字符串处理方法，看不出
     * 「模型这次是想调工具，本来就没有正文」。更麻烦的是这类崩溃只在模型选择调工具时
     * 才出现，本地测试往往碰不上，上线后随机复现。</p>
     *
     * <p>注意配套断言 {@code isUsable()} 为 false：转成空串是为了不崩，
     * 不是为了把空内容当成有效答案。</p>
     */
    @Test
    public void shouldTreatNullContentAsEmptyString() {
        // Arrange：模型决定调工具时，content 是 JSON null。
        String body = "{"
                + "\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":null},"
                + "\"finish_reason\":\"tool_calls\"}],"
                + "\"usage\":{\"prompt_tokens\":50,\"completion_tokens\":20}"
                + "}";

        // Act：解析成功。
        ChatResponse response = codec.parseResponse(body, null);

        // Assert：转成空字符串而不是留 null，避免空指针传到业务层。
        assertEquals("", response.getContent());
        assertEquals(FinishReason.TOOL_CALLS, response.getFinishReason());
        assertFalse(response.isUsable());
    }

    /**
     * 规则：缺少 {@code choices} 时抛出说明原因的 {@link ModelException}，而不是让它自然空指针。
     *
     * <p><b>为什么重要：</b>协议文档写了 {@code choices} 必然存在，但真实链路上很多环节
     * 会返回一个「格式像是成功响应」的残缺 JSON：网关只透传了 {@code id}、鉴权中间件
     * 塞了自己的响应体、供应商内部错误被包装成 200。这里的关键不是「能不能挡住」，
     * 而是<b>挡住时说清了什么</b>：异常消息里带 {@code choices} 字样，看日志的人立刻知道
     * 是服务端返回不对，不用怀疑自己的代码。</p>
     *
     * <p><b>违反会怎样：</b>{@code choices.get(0)} 直接空指针，堆栈只显示解析代码的某一行，
     * 完全看不出服务端到底返回了什么。这类线上问题往往要靠加日志重新发版才能定位，
     * 而它本来一次就能查清。</p>
     */
    @Test
    public void shouldRejectResponseWithoutChoices() {
        // Arrange：缺少 choices 数组，例如网关返回了一个残缺响应。
        String body = "{\"id\":\"chatcmpl-x\"}";

        // Act + Assert：必须显式报错。
        // 不校验的话，取 choices.get(0) 直接空指针，
        // 而堆栈里看不出「是服务端返回不对」这个真正原因。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> codec.parseResponse(body, null)
        );
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.getMessage().contains("choices"));
    }

    /**
     * 规则：{@code choices} 是空数组，和字段缺失一样要拦住。
     *
     * <p><b>为什么重要：</b>「字段存在」和「字段有内容」是两件事，而防御性校验最常见的
     * 写法只查了前者：{@code if (root.has("choices"))} 通过了，接着 {@code get(0)} 照样炸。
     * 空数组不是假设出来的场景 —— 内容安全策略在某些供应商上会返回一个 200 加空 choices，
     * 部分网关的降级逻辑也会这么干。</p>
     *
     * <p><b>违反会怎样：</b>抛出的是 {@link IndexOutOfBoundsException} 或空指针，
     * 而不是分类明确的 {@link ModelException}。上层的重试和降级逻辑是按
     * {@code ErrorType} 分派的，认不出这个异常，它就会一路冒泡到用户界面。</p>
     */
    @Test
    public void shouldRejectResponseWithEmptyChoicesArray() {
        // Arrange：choices 存在但是空数组。
        String body = "{\"id\":\"x\",\"choices\":[]}";

        // Act + Assert：空数组和缺失一样要挡住。
        assertThrows(
                ModelException.class,
                () -> codec.parseResponse(body, null)
        );
    }

    /**
     * 规则：响应体不是合法 JSON 时，归类为可重试的 {@code SERVER_ERROR}。
     *
     * <p><b>为什么重要：</b>拿到一段 HTML 说明请求<b>根本没到模型服务</b>，
     * 是中间的网关、负载均衡或反向代理自己应答的。这类故障通常是瞬时的
     * （某个后端实例正在重启、连接池打满），所以判定可重试是对的。
     * 注意这里的推断方向：不是从状态码看出问题，而是从「响应体的格式」看出问题 ——
     * 这种响应完全可能带着 200 状态码过来。</p>
     *
     * <p><b>违反会怎样：</b>Jackson 的 {@code JsonParseException} 直接漏到上层。
     * 它不带重试语义，一次本可自动恢复的网关抖动变成用户可见的失败；
     * 而且异常类型指向「JSON 解析」，排查方向会偏到序列化配置上，
     * 真正的原因（流量没打到模型服务）反而被掩盖。</p>
     */
    @Test
    public void shouldRejectMalformedJson() {
        // Arrange：响应根本不是 JSON，例如网关返回了 HTML 错误页。
        String body = "<html><body>502 Bad Gateway</body></html>";

        // Act + Assert：归类为可重试的服务端错误。
        ModelException exception = assertThrows(
                ModelException.class,
                () -> codec.parseResponse(body, null)
        );
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.isRetryable());
    }

    /**
     * 规则：空响应体必须抛出说明原因的异常，不能是空指针。
     *
     * <p><b>为什么重要：</b>连接被中途掐断、上游超时后关闭连接、代理返回
     * {@code 204 No Content}，都会让你拿到一个空串。空串是所有解析路径上最容易漏掉的输入，
     * 因为它既不是 null 也不会触发格式错误 —— {@code readTree("")} 在多数 Jackson 版本里
     * 返回一个「缺失节点」，然后错误在几行之后才爆出来，且爆的位置和原因无关。</p>
     *
     * <p><b>违反会怎样：</b>日志里是一行 {@code NullPointerException}，堆栈指向解析
     * {@code choices} 的那行代码。你会去怀疑自己的解析逻辑，而真相是服务端什么都没返回。
     * 在解析入口就挡住，错误消息才能直接说出这件事。</p>
     */
    @Test
    public void shouldRejectEmptyResponseBody() {
        // Arrange + Act + Assert：空响应体也要有明确错误，而不是空指针。
        assertThrows(
                ModelException.class,
                () -> codec.parseResponse("", null)
        );
    }

    /**
     * 规则：{@code usage} 缺失要容忍并记为 0，不能让这一次业务调用失败。
     *
     * <p><b>为什么重要：</b>这条规则和上面几条方向相反，值得对照着看：<b>缺字段并不总是该报错，
     * 判断标准是这个字段对本次业务是否必需</b>。{@code choices} 缺了就没有结果可用，
     * 必须报错；{@code usage} 只影响成本统计，模型已经把答案给你了。不少兼容网关和自建代理
     * 就是不转发 {@code usage}。</p>
     *
     * <p><b>违反会怎样：</b>接一个不返回 usage 的网关，全部请求 100% 失败 ——
     * 为了记账把主流程搞挂了。反过来也要清楚记 0 的代价：{@code totalTokens} 是 0
     * 不代表没有计费，所以成本看板上这部分会凭空消失，做容量规划时会低估用量。
     * 这是刻意选择的取舍，不是没有代价。</p>
     */
    @Test
    public void shouldTolerateMissingUsage() {
        // Arrange：部分兼容网关不返回 usage。
        String body = "{"
                + "\"choices\":[{\"message\":{\"content\":\"内容\"},\"finish_reason\":\"stop\"}]"
                + "}";

        // Act：不该失败 —— 拿不到用量是可观测性问题，
        // 不该让一次本来成功的业务调用变成失败。
        ChatResponse response = codec.parseResponse(body, null);

        // Assert：记 0。但要清楚：记 0 不代表没有计费。
        assertEquals(0, response.getUsage().getTotalTokens());
        assertTrue(response.isUsable());
    }

    /**
     * 规则：{@code requestId} 优先取响应体里的 {@code id}，取不到就退回 HTTP 响应头。
     *
     * <p><b>为什么重要：</b>{@code requestId} 是出问题时<b>唯一能和模型服务方对上的凭证</b>。
     * 你说"昨天下午有个请求返回结果不对"，对方查不了；你给出 requestId，对方能在自己的日志里
     * 直接定位到那一次调用。两个来源都要试，是因为不同供应商放的位置不一样 ——
     * 有的在响应体，有的只放在 {@code x-request-id} 这类响应头里，还有的两处都给。</p>
     *
     * <p><b>违反会怎样：</b>只读响应体，遇到只在头里返回 id 的供应商就永远拿不到，
     * 而这件事在一切正常时完全没有症状，等到真出问题、真要提工单时才发现日志里全是空的。
     * 那时候已经没法回溯了。</p>
     */
    @Test
    public void shouldFallBackToHeaderRequestIdWhenBodyHasNone() {
        // Arrange：响应体里没有 id，但 HTTP 头里有。
        String body = "{"
                + "\"choices\":[{\"message\":{\"content\":\"内容\"},\"finish_reason\":\"stop\"}],"
                + "\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1}"
                + "}";

        // Act：传入响应头里的请求 id。
        ChatResponse response = codec.parseResponse(body, "header-req-123");

        // Assert：用响应头的值兜底。requestId 是排查时唯一能和服务商对上的凭证，
        // 能拿到就不该丢。
        assertEquals("header-req-123", response.getRequestId());
    }

    /**
     * 规则：401 映射成 {@code AUTHENTICATION} 且不可重试，同时把服务端原文带进异常消息。
     *
     * <p><b>为什么重要：</b>密钥错了、过期了、或者用错了环境的密钥，重试一万次结果一样。
     * 这类失败要人去改配置，等待不会让它恢复。而"带出原文"这半条同样关键：
     * 401 的具体原因差别很大 —— key 拼错、key 被吊销、组织欠费、这个 key 没有该模型的权限，
     * 只有服务端的 message 能区分。</p>
     *
     * <p><b>违反会怎样：</b>分类错了就会白等：把 401 当可重试，配错密钥时每个请求变成 N 次
     * 无用调用，用户等 N 倍时间，日志里 N 倍噪音盖住真问题。丢掉原文则是另一种卡死：
     * 你只知道"鉴权失败"，反复检查密钥有没有拼错，而真正的原因是账户余额不足。</p>
     */
    @Test
    public void shouldMapAuthenticationError() {
        // Arrange + Act：401 通常是密钥错误。
        ModelException exception = codec.toException(
                401, "{\"error\":{\"message\":\"Invalid API key\"}}", "req-1");

        // Assert：不可重试，需要人工改配置。
        assertEquals(ModelException.ErrorType.AUTHENTICATION, exception.getErrorType());
        assertFalse(exception.isRetryable());
        // 服务端的原始错误信息要带出来，否则排查时只有一个状态码。
        assertTrue(exception.getMessage().contains("Invalid API key"));
        assertEquals("req-1", exception.getRequestId());
    }

    /**
     * 规则：429 映射成 {@code RATE_LIMIT} 且标记为可重试。
     *
     * <p><b>为什么重要：</b>429 的语义是"你现在太快了，等一下再来"，不是"这个请求错了"。
     * 请求本身完全合法，隔几百毫秒重发大概率就成功。这是所有错误分类里最值得自动恢复的一类，
     * 因为它几乎必然会发生 —— 只要并发上去，就一定会撞上供应商的配额。</p>
     *
     * <p><b>违反会怎样：</b>当成不可重试直接抛给用户，高峰期会出现一大片本可自动恢复的失败，
     * 而且是在流量最大、最不该出错的时候。注意"可重试"必须配合退避等待：
     * 立刻原样重发只会让限流窗口更满，把偶发限流变成持续限流。</p>
     */
    @Test
    public void shouldMapRateLimitAsRetryable() {
        // Arrange + Act：429 是限流。
        ModelException exception = codec.toException(
                429, "{\"error\":{\"message\":\"Rate limit reached\"}}", null);

        // Assert：可重试，但必须配合退避等待。
        assertEquals(ModelException.ErrorType.RATE_LIMIT, exception.getErrorType());
        assertTrue(exception.isRetryable());
    }

    /**
     * 规则：5xx 映射成 {@code SERVER_ERROR} 且标记为可重试。
     *
     * <p><b>为什么重要：</b>5xx 表示"你的请求没问题，是我这边出问题了"。
     * 模型服务是重负载的分布式系统，单个节点重启、扩容中、后端模型实例被抢占，
     * 都会返回 503。这类故障通常只持续几秒，且换一次重试很可能落到健康节点上。
     * 注意这里用 {@code >= 500} 而不是逐个枚举状态码，因为供应商用什么具体码不可控。</p>
     *
     * <p><b>违反会怎样：</b>把 5xx 当致命错误，你的服务可用性就直接等于上游可用性，
     * 上游抖一下你就跟着掉一片请求 —— 而这些请求原本重发一次就能成。</p>
     */
    @Test
    public void shouldMapServerErrorAsRetryable() {
        // Arrange + Act：5xx 是服务端问题。
        ModelException exception = codec.toException(503, "{\"error\":{\"message\":\"unavailable\"}}", null);

        // Assert：可重试。
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.isRetryable());
    }

    /**
     * 规则：同样是 400，要靠 {@code error.code} 把"上下文超长"从"参数写错"里分出来。
     *
     * <p><b>为什么重要：</b>这是整张错误映射表里最能体现"光看状态码不够"的一条。
     * 两者的补救动作没有任何交集：普通 400 是代码 bug（温度传了 3.0、模型名拼错），
     * 要人去改代码，重发一万次都是同样结果；上下文超长是运行时状态问题
     * （对话历史攒长了、检索出来的文档太大），代码完全正确，
     * 压缩上下文或截断历史后重发就能成功。</p>
     *
     * <p><b>违反会怎样：</b>混成一类的话，两个方向都会错。上下文超长被当成
     * "参数写错"上报，值班的人去翻代码找不出问题，而真正该做的是接一个摘要压缩策略 ——
     * 长会话应用会在这里持续失败。反过来如果把所有 400 都当上下文超长去自动压缩，
     * 会把用户的对话历史白白删掉，问题依旧存在。</p>
     */
    @Test
    public void shouldDistinguishContextLengthFromOtherBadRequests() {
        // Arrange：两个都是 400，但处理方式完全不同。
        ModelException plainBadRequest = codec.toException(
                400, "{\"error\":{\"message\":\"Invalid temperature\"}}", null);
        ModelException contextTooLong = codec.toException(
                400,
                "{\"error\":{\"message\":\"Too many tokens\",\"code\":\"context_length_exceeded\"}}",
                null);

        // Assert：普通 400 是参数写错了，要改代码。
        assertEquals(ModelException.ErrorType.INVALID_REQUEST, plainBadRequest.getErrorType());

        // Assert：上下文超长要先压缩上下文再重发，是完全不同的补救动作。
        // 只看状态码会把这两种情况混为一谈。
        assertEquals(ModelException.ErrorType.CONTEXT_LENGTH_EXCEEDED, contextTooLong.getErrorType());
        assertFalse(contextTooLong.isRetryable());
    }

    /**
     * 规则：408 映射成 {@code TIMEOUT} 且可重试，即使响应体是空的也要能分类。
     *
     * <p><b>为什么重要：</b>大模型调用天生慢，几十秒的响应很常见，超时是常态而非例外。
     * 而超时响应往往没有响应体（连接就断了），所以分类只能靠状态码，
     * {@code toException} 必须在 {@code body} 为空时仍然工作。</p>
     *
     * <p><b>违反会怎样：</b>超时不重试会让用户在正常波动下频繁看到失败。
     * 但这里有个必须知道的陷阱：超时只说明"我没收到响应"，不说明"服务端没执行"。
     * 上一次可能已经生成完并计了费，重试等于付两次钱；如果这次调用带副作用
     * （写库、调工具、发消息），重试还可能造成重复执行 —— 所以副作用型调用
     * 需要幂等键，不能只靠 {@code isRetryable()} 就无脑重发。</p>
     */
    @Test
    public void shouldMapTimeoutStatus() {
        // Arrange + Act：408 请求超时。
        ModelException exception = codec.toException(408, "", null);

        // Assert：可重试，但要注意上一次可能已在服务端执行并计费。
        assertEquals(ModelException.ErrorType.TIMEOUT, exception.getErrorType());
        assertTrue(exception.isRetryable());
    }

    /**
     * 规则：错误响应体不是 JSON 时，不能自己再抛异常，而要把原文片段带进异常消息。
     *
     * <p><b>为什么重要：</b>{@code toException} 是错误路径上的最后一环，
     * 它自己绝不能失败。而"响应体是 HTML"这件事本身就是最有价值的线索：
     * 说明请求根本没到模型服务，是被中间某个网关、负载均衡或公司代理拦下的。
     * HTML 里的标题（这里是 {@code 504 Gateway Timeout}）、nginx 版本号、
     * 甚至某个内网错误页的样式，往往是判断"哪一跳出了问题"的唯一依据。</p>
     *
     * <p><b>违反会怎样：</b>解析错误体时抛出 {@code JsonParseException}，
     * 原始的 504 信息被彻底吃掉，日志里只剩一个 Jackson 的解析栈 ——
     * 看起来像是自己代码的 bug，实际是网关故障，排查方向从一开始就是错的。
     * 另一种常见错法是只记状态码丢掉响应体，那就永远分不清
     * "模型服务 500" 和 "网关 500"，而这两者要找的人完全不同。</p>
     */
    @Test
    public void shouldIncludeNonJsonErrorBodyAsDiagnosticClue() {
        // Arrange：错误响应体是 HTML，不是 JSON。
        String html = "<html><head><title>504 Gateway Timeout</title></head></html>";

        // Act：解析错误体失败时不该再抛异常。
        ModelException exception = codec.toException(504, html, null);

        // Assert：把原始内容带出来。「响应不是 JSON」本身就是关键线索 ——
        // 说明请求可能没打到模型服务，而是被中间的网关拦住了。
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.getMessage().contains("504 Gateway Timeout"));
    }

    /**
     * 规则：服务端只给状态码、没有响应体时，异常消息里至少要有状态码。
     *
     * <p><b>为什么重要：</b>这是错误路径的最低保障。空响应体在真实环境很常见 ——
     * 负载均衡直接掐断、服务实例 OOM 被杀、Ingress 超时。此时唯一存在的信息
     * 就是状态码和 {@code requestId}，两者都必须出现在异常里。</p>
     *
     * <p><b>违反会怎样：</b>如果消息拼接依赖响应体（比如只写
     * {@code providerMessage}），空响应体会产生一条空消息或
     * {@code "模型服务返回 HTTP null"} 这样的垃圾日志。
     * 告警群里收到一条不带状态码的失败通知，等于什么都没收到 ——
     * 连"该不该重试"都判断不了。</p>
     */
    @Test
    public void shouldHandleEmptyErrorBody() {
        // Arrange + Act：服务端只给状态码，没有响应体。
        ModelException exception = codec.toException(500, "", "req-9");

        // Assert：仍要给出可用的错误信息和分类。
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.getMessage().contains("500"));
    }
}
