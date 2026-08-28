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
     * 请求 JSON 必须用协议的下划线字段名和小写角色值：{@code max_tokens} 写成驼峰会被当未知字段忽略、
     * 输出上限失效，角色发成 {@code "SYSTEM"} 轻则 400、重则被兼容网关降级成 {@code user}，防提示注入的边界就没了。
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

    /** 正常响应要同时取到正文、结束原因、Token 用量和请求 id：解析层漏了哪一项上层就永远拿不到，等线上要查「为什么返回半句话」时只能靠猜。 */
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

    /** {@code finish_reason} 为 {@code "length"} 时解析成功但标为不可用：映射成 {@code STOP} 会让残句被当成完整答案落库，事后还分不清是模型答错还是被截断。 */
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
     * 没见过的 {@code finish_reason} 归到 {@link FinishReason#UNKNOWN} 并判不可用：抛异常会让供应商新增枚举值时
     * 你的服务不发版也大面积报错，当成 {@code STOP} 则把异常结束悄悄写成正常结果，到下游暴露时已查不回是哪次调用。
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
     * {@code content} 为 JSON null 时转成空串：模型调工具走的就是这条正常路径，留着 null 会在业务层某个字符串方法上空指针，
     * 堆栈还看不出「本来就没有正文」，而且只在模型选择调工具时才随机复现。
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

    /** 缺 {@code choices} 要抛出带该字段名的 {@link ModelException}：否则 {@code choices.get(0)} 直接空指针，堆栈只指向解析代码，看不出是服务端返回了残缺 JSON。 */
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
     * {@code choices} 是空数组和字段缺失一样要拦住：只判 {@code has("choices")} 的话 {@code get(0)} 照样炸，
     * 抛出的 {@link IndexOutOfBoundsException} 不带 {@code ErrorType}，上层的重试降级认不出，会一路冒泡到界面。
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
     * 响应体不是合法 JSON 时归类为可重试的 {@code SERVER_ERROR}：拿到 HTML 说明流量没打到模型服务、被中间网关应答了，
     * 漏出 Jackson 的 {@code JsonParseException} 会让一次瞬时抖动变成用户可见失败，还把排查方向带到序列化配置上。
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

    /** 空响应体要在解析入口就抛出说明原因的异常：空串既不是 null 也不触发格式错误，放过去只会在几行后变成一个指向解析代码的空指针，掩盖「服务端什么都没返回」。 */
    @Test
    public void shouldRejectEmptyResponseBody() {
        // Arrange + Act + Assert：空响应体也要有明确错误，而不是空指针。
        assertThrows(
                ModelException.class,
                () -> codec.parseResponse("", null)
        );
    }

    /**
     * {@code usage} 缺失要容忍并记 0：缺字段该不该报错取决于它对本次业务是否必需，为了记账让主流程 100% 失败更糟；
     * 代价是记 0 不代表没计费，成本看板会少掉这部分用量。
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
     * {@code requestId} 取不到响应体里的 {@code id} 就退回响应头：有的供应商只在 {@code x-request-id} 里给，
     * 只读响应体在一切正常时毫无症状，等真要向服务商提工单时才发现日志里全是空的，那时已无法回溯。
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
     * 401 映射成不可重试的 {@code AUTHENTICATION} 并带上服务端原文：鉴权失败靠等不会恢复，当成可重试只是白等 N 倍、
     * 用 N 倍日志噪音盖住真问题；丢掉原文则分不清密钥拼错、被吊销还是账户欠费。
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
     * 429 映射成可重试的 {@code RATE_LIMIT}：请求本身合法，只是太快了；当成不可重试会在流量最高峰丢掉一大片本可自动恢复的调用，
     * 但重试必须配退避，立刻原样重发只会把偶发限流变成持续限流。
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

    /** 5xx 按 {@code >= 500} 整段映射成可重试的 {@code SERVER_ERROR}：当成致命错误，你的可用性就直接等于上游可用性，上游抖一下就跟着掉一片本可重发成功的请求。 */
    @Test
    public void shouldMapServerErrorAsRetryable() {
        // Arrange + Act：5xx 是服务端问题。
        ModelException exception = codec.toException(503, "{\"error\":{\"message\":\"unavailable\"}}", null);

        // Assert：可重试。
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.isRetryable());
    }

    /**
     * 同样是 400 要靠 {@code error.code} 把上下文超长和参数写错分开：两者补救动作没有交集，混成一类的话超长会被当代码 bug
     * 让值班的人白翻代码，而把所有 400 都当超长去自动压缩又会白删用户的对话历史、问题依旧。
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
     * 408 映射成可重试的 {@code TIMEOUT}，且 {@code body} 为空时也要能分类：超时只说明没收到响应，不说明服务端没执行，
     * 上一次可能已生成完并计了费，带副作用的调用要靠幂等键，不能只看 {@code isRetryable()} 就无脑重发。
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
     * 错误响应体不是 JSON 时 {@code toException} 不能自己再抛异常，要把原文片段带进消息：HTML 里的
     * {@code 504 Gateway Timeout} 往往是判断哪一跳出问题的唯一线索，吃掉它只剩一个像是自己代码 bug 的 Jackson 解析栈。
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

    /** 只给状态码、没有响应体时异常消息里至少要有状态码：消息全靠 {@code providerMessage} 拼的话，空响应体会产出一条连该不该重试都判断不了的空告警。 */
    @Test
    public void shouldHandleEmptyErrorBody() {
        // Arrange + Act：服务端只给状态码，没有响应体。
        ModelException exception = codec.toException(500, "", "req-9");

        // Assert：仍要给出可用的错误信息和分类。
        assertEquals(ModelException.ErrorType.SERVER_ERROR, exception.getErrorType());
        assertTrue(exception.getMessage().contains("500"));
    }
}
