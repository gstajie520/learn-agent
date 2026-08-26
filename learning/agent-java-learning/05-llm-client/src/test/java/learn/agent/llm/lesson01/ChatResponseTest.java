package learn.agent.llm.lesson01;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 响应契约与错误分类的测试。
 *
 * <p>测试目标：证明「响应能不能用」和「失败要不要重试」这两个判断
 * 都由对象自己回答，业务代码不需要解析文本去猜。</p>
 *
 * <p>覆盖的规则：</p>
 * <ul>
 *   <li>只有正常结束且有内容的响应才可用；</li>
 *   <li>被截断的响应即使有正文也不可用；</li>
 *   <li>缺少 Token 统计的响应不允许进入业务层；</li>
 *   <li>网关不返回 requestId 时统一记为 unknown，日志里不会出现 null；</li>
 *   <li>可重试与不可重试的错误分类正确。</li>
 * </ul>
 */
public class ChatResponseTest {

    /**
     * 规则：{@code isUsable()} 为 true 的充要条件是 {@code finishReason == STOP} 且正文非空白。
     *
     * <p><b>为什么重要：</b>这是整个响应契约的正向基准 —— 先钉死「什么才算可用」，
     * 后面三个测试才好逐个证明「哪些情况不可用」。关键在于把这个判断收进
     * {@link ChatResponse} 自己身上：调用方只需要问一句 {@code isUsable()}，
     * 不必记住「要检查 finishReason，还要顺手 trim 一下 content」这套口诀。
     * 一处实现、一处测试，新人也不会漏掉其中半条。</p>
     *
     * <p><b>违反会怎样：</b>如果把这个判断散落在每个调用点，
     * 总会有人只写 {@code if (content != null)} 就直接往下走。
     * 项目里于是出现十几种「差不多」的检查，其中几种漏了 finishReason ——
     * 而漏掉的那几处就是将来的线上故障点。</p>
     */
    @Test
    public void shouldBeUsableOnlyWhenStoppedNormally() {
        // Arrange：模型自然说完，正文非空。
        ChatResponse response = new ChatResponse(
                "北侧新增一台雷达。",
                FinishReason.STOP,
                new TokenUsage(100, 12),
                "req-001");

        // Act + Assert：这是唯一可以放心读 content 的情况。
        assertTrue(response.isUsable());
        assertEquals("北侧新增一台雷达。", response.getContent());
    }

    /**
     * 规则：{@code finishReason == LENGTH}（撞到输出上限被截断）时 {@code isUsable()} 必须为 false，
     * 哪怕正文看起来完全正常。
     *
     * <p><b>为什么重要：</b>这是本课最危险的一条，因为被截断的内容<b>没有任何外观特征</b>。
     * 本测试里的 {@code "北侧新增一台雷达，东南角部署"} 是通顺的中文，长度也不短，
     * 任何基于「内容非空」「长度够不够」的检查都会放它过去。唯一能识别它的信号是
     * {@code finishReason}，而这个字段只有你主动去看才存在。
     * 换个角度说：截断不是错误响应，服务端返回的是 HTTP 200，
     * 没有异常、没有错误码，只有这一个枚举值在告诉你话没说完。</p>
     *
     * <p><b>违反会怎样：</b>脏数据静默入库，而且事后无法追溯。
     * 如果下游要解析 JSON，你会遇到最费解的一类报错 ——「模型明明返回了内容，
     * 为什么 JSON 解析失败」，因为残缺的 JSON 少了收尾的括号。
     * 如果是直接写库或展示给用户，那就是一句话说到一半就断了，
     * 而日志里这次调用记录成功。等用户反馈过来，你已经分不清是模型答错、
     * 还是被截断、还是存储环节丢了数据。</p>
     */
    @Test
    public void shouldNotBeUsableWhenTruncated() {
        // Arrange：正文看起来像正常文本，但结束原因是达到输出上限。
        ChatResponse response = new ChatResponse(
                "北侧新增一台雷达，东南角部署",
                FinishReason.LENGTH,
                new TokenUsage(100, 200),
                "req-002");

        // Act + Assert：残句不可用。只看 content 长度是发现不了的，必须看 finishReason。
        assertFalse(response.isUsable());
    }

    /**
     * 规则：结束原因正常但正文只有空白字符时，{@code isUsable()} 同样为 false。
     *
     * <p><b>为什么重要：</b>这补上了另一半 —— 上一个测试是「原因异常但有内容」，
     * 这里是「原因正常但没内容」。模型返回空输出在真实服务里确实会发生：
     * 提示词写得太克制、输入本身没什么可总结的、或者模型判断该沉默。
     * 服务端认为这是一次成功调用（{@code STOP}，HTTP 200，照常计费），
     * 但对业务来说它没有任何价值。注意判断用的是 {@code trim().isEmpty()} 而不是
     * {@code isEmpty()}：模型很容易吐出几个空格或换行，那和什么都没输出是一回事。</p>
     *
     * <p><b>违反会怎样：</b>空串被当成有效结果写进下游。场景总结字段存了个 {@code ""}，
     * 页面上显示一片空白，用户以为功能坏了。更麻烦的是这个空值会被当成
     * 「已经处理过」而不再重算 —— 缓存、幂等标记、状态机全都认为这条数据是好的，
     * 你需要专门写一个数据修复任务才能把它们捞出来重跑。</p>
     */
    @Test
    public void shouldNotBeUsableWhenContentIsBlank() {
        // Arrange：结束原因正常，但模型什么都没输出，这在真实服务里确实会发生。
        ChatResponse response = new ChatResponse(
                "   ",
                FinishReason.STOP,
                new TokenUsage(100, 0),
                "req-003");

        // Act + Assert：空白内容同样不可用，避免把空串当有效结果写进下游。
        assertFalse(response.isUsable());
    }

    /**
     * 规则：{@code usage} 为 {@code null} 时拒绝构造 {@link ChatResponse}，
     * 且异常信息里要点明是哪个字段。
     *
     * <p><b>为什么重要：</b>Token 统计不是可选的锦上添花，它是这次调用花了多少钱的唯一凭据。
     * 允许一个没有 usage 的响应进入业务层，等于允许一次<b>不计入成本的调用</b>存在 ——
     * 成本报表从此对不上账，而且差额无从查起。这里选择用「构造即失败」而不是「默认给零」
     * 来处理：默认零值会让缺失伪装成「这次没花钱」，那比直接报错危险得多。
     * 断言异常信息包含 {@code usage}，是为了让排查的人一眼看出缺的是哪一项，
     * 不用去翻构造函数源码数参数位置。</p>
     *
     * <p><b>违反会怎样：</b>成本黑洞。月底账单比统计数字高出一截，
     * 你知道有调用没被记上，但不知道是哪个接口、哪个模型、哪段时间 ——
     * 因为那些调用在系统里的记录是完整的，只是 Token 数是 0。
     * 想定位就只能拿服务方的原始账单逐条比对。</p>
     */
    @Test
    public void shouldRejectResponseWithoutUsage() {
        // Arrange + Act + Assert：没有 Token 统计就无法核算成本，直接拒绝构造。
        IllegalArgumentException exception = assertThrows(
                IllegalArgumentException.class,
                () -> new ChatResponse("内容", FinishReason.STOP, null, "req-004")
        );
        assertTrue(exception.getMessage().contains("usage"));
    }

    /**
     * 规则：{@code requestId} 缺失（{@code null} 或空白）时统一兜底成字符串 {@code "unknown"}。
     *
     * <p><b>为什么重要：</b>{@code requestId} 是出问题时唯一能和模型服务方对上的凭证 ——
     * 你说「昨天下午有次调用返回了奇怪结果」没人能查，报出这个 id 对方才能捞到日志。
     * 但它并非总是存在：不少兼容 OpenAI 协议的第三方网关不返回这个响应头。
     * 既然这种缺失是常态而不是故障，就不该让它抛异常（那会因为一个日志字段
     * 把一次成功的调用判死），而是给一个明确的占位值。
     * 选 {@code "unknown"} 而不是留 {@code null}，是因为它同时传达了两层意思：
     * 这里没有 id，而且我们知道没有、这是预期内的。</p>
     *
     * <p><b>违反会怎样：</b>{@code null} 渗进日志。轻则日志里出现
     * {@code requestId=null} 这种噪声，看的人分不清是网关没给还是我们的解析代码写错了；
     * 重则某处对它做字符串拼接或 {@code equals} 之外的操作，
     * 一个纯粹用于排查的字段反过来把主流程打挂 —— 排障手段变成故障源，
     * 这是最不划算的一种崩溃。</p>
     */
    @Test
    public void shouldFallBackToUnknownRequestId() {
        // Arrange：部分兼容网关不返回请求 id。
        ChatResponse response = new ChatResponse(
                "内容",
                FinishReason.STOP,
                new TokenUsage(10, 5),
                null);

        // Act + Assert：统一成 unknown，日志里不会出现 null，排查时也能看出是网关没给。
        assertEquals("unknown", response.getRequestId());
    }

    /**
     * 规则：{@code RATE_LIMIT}、{@code SERVER_ERROR}、{@code TIMEOUT} 三类错误标记为可重试。
     *
     * <p><b>为什么重要：</b>这三类的共同点是<b>失败原因和请求内容无关</b> ——
     * 限流是因为这一刻并发太高，5xx 是服务端自己出了状况，超时可能只是网络抖动。
     * 请求本身完全合法，换个时间点原样发过去就能成功，所以重试是有意义的。
     * 把这个属性写进 {@link ModelException.ErrorType} 枚举，
     * 意味着「可重试」是错误类型的固有性质，而不是每个调用点各自的判断。</p>
     *
     * <p><b>违反会怎样：</b>本该自愈的故障变成用户可见的失败。
     * 模型服务方做一次滚动发布，期间零星 503，如果不重试，
     * 这些请求全部原样报错给用户 —— 而实际上隔两秒再发就成功了。
     * 限流场景尤其明显：高峰期偶发 429 是正常运行状态，不是故障，
     * 不重试就等于把服务的有效容量白白砍掉一块。</p>
     *
     * <p>{@code TIMEOUT} 有个值得留意的细节：重试是对的，
     * 但上一次可能已经在服务端执行完并且计费了，所以超时重试的成本要按多次算。</p>
     */
    @Test
    public void shouldClassifyRetryableErrors() {
        // Arrange + Act + Assert：等一会儿就可能成功的错误，标记为可重试。
        assertTrue(ModelException.ErrorType.RATE_LIMIT.isRetryable());
        assertTrue(ModelException.ErrorType.SERVER_ERROR.isRetryable());
        assertTrue(ModelException.ErrorType.TIMEOUT.isRetryable());
    }

    /**
     * 规则：{@code INVALID_REQUEST}、{@code AUTHENTICATION}、{@code CONTEXT_LENGTH_EXCEEDED}、
     * {@code CONTENT_FILTERED} 四类必须标记为不可重试。
     *
     * <p><b>为什么重要：</b>这四类的共同点正好和上一个测试相反 ——
     * 问题出在请求本身或配置上，是<b>确定性</b>的。参数越界就是越界，
     * 密钥无效就是无效，输入超了窗口就是超了，被安全策略拦下就是会被拦下。
     * 同样的请求重发一万次，得到的是同样的失败。想成功必须先改东西：
     * 修参数、换密钥、压缩上下文、调整内容。</p>
     *
     * <p><b>违反会怎样：</b>把确定性失败当成偶发故障去重试，代价是三重的。
     * 花钱：每次重试都要付输入 Token 的费用，而且 {@code CONTEXT_LENGTH_EXCEEDED}
     * 场景下的输入恰恰是最长最贵的那种。费时：用户要等完整个重试退避周期
     * 才收到那个从第一次起就注定的错误。掩盖真相：日志里堆满同一个错误，
     * 监控图上是一片失败率尖峰，真正需要做的事（改配置）却因为看起来像
     * 「外部服务不稳定」而被推迟排查。{@code AUTHENTICATION} 还有额外风险，
     * 拿着无效密钥反复叩门可能触发服务方的风控封禁。</p>
     */
    @Test
    public void shouldClassifyNonRetryableErrors() {
        // Arrange + Act + Assert：输入或配置本身就是错的，重试多少次结果都一样。
        assertFalse(ModelException.ErrorType.INVALID_REQUEST.isRetryable());
        assertFalse(ModelException.ErrorType.AUTHENTICATION.isRetryable());
        assertFalse(ModelException.ErrorType.CONTEXT_LENGTH_EXCEEDED.isRetryable());
        assertFalse(ModelException.ErrorType.CONTENT_FILTERED.isRetryable());
    }

    /**
     * 规则：{@link ModelException} 实例自己要能回答「要不要重试」，
     * 把枚举上的判断转发出来。
     *
     * <p><b>为什么重要：</b>前两个测试验的是枚举，这个测试验的是<b>业务代码实际拿到的东西</b>。
     * {@code catch} 块里接住的是异常对象，不是枚举 —— 如果异常上没有 {@code isRetryable()}，
     * 调用方就得写 {@code e.getErrorType().isRetryable()}，先知道有 {@code ErrorType}
     * 这个概念、再知道该问它。一行 {@code if (e.isRetryable())} 才是重试逻辑该有的样子。</p>
     *
     * <p><b>违反会怎样：</b>调用方退回到解析错误文本来猜。你会在项目里看到
     * {@code if (e.getMessage().contains("429"))} 或者
     * {@code msg.contains("rate limit")} 这种代码 —— 它今天能跑，
     * 因为今天的错误信息恰好长这样。等换个模型服务商、或者服务方把提示语从
     * 「Rate limit exceeded」改成「Too many requests」，判断就静默失效了：
     * 不报错，只是从此不再重试，而没有任何测试会发现。
     * 把判断收进异常类型里，这类腐坏就不可能发生。</p>
     */
    @Test
    public void shouldExposeRetryableFlagOnException() {
        // Arrange：业务代码拿到的是异常对象，不是枚举。
        ModelException rateLimit = new ModelException(
                ModelException.ErrorType.RATE_LIMIT, "429 Too Many Requests");
        ModelException authFailure = new ModelException(
                ModelException.ErrorType.AUTHENTICATION, "API key 无效");

        // Act + Assert：异常自己就能回答「要不要重试」，调用方不必解析错误文本。
        assertTrue(rateLimit.isRetryable());
        assertFalse(authFailure.isRetryable());
    }

    /**
     * 规则：{@link TokenUsage} 必须分别保留输入和输出 Token，总数是算出来的而不是存进来的。
     *
     * <p><b>为什么重要：</b>输入和输出<b>单价不同，输出通常明显更贵</b>，
     * 所以只记总数根本算不出钱 —— 同样 138 个 Token，
     * 全是输入和全是输出的花费差好几倍。两者的增长规律也完全不同：
     * 输出 Token 受 {@code maxOutputTokens} 约束，有明确天花板；
     * 输入 Token 随对话历史线性增长，第 20 轮的输入可能是第 1 轮的十几倍。
     * 这意味着长会话的成本曲线是上翘的，而这个趋势只有看分项才能发现。</p>
     *
     * <p><b>违反会怎样：</b>成本失控但归因失败。你只知道「Token 用量涨了」，
     * 不知道该去优化提示词长度、裁剪历史，还是收紧输出上限 ——
     * 三种手段针对的是不同分项，选错了做了半天没效果。
     * 更实际的痛点是无法预估：产品问「支持 50 轮对话要多少成本」，
     * 只有总数的话答不上来。</p>
     *
     * <p>{@code getTotalTokens()} 仍然有用，但用途不同：它是判断有没有逼近
     * 上下文窗口上限的粗略指标，对账要看分项。</p>
     */
    @Test
    public void shouldAccumulateTokensSeparately() {
        // Arrange：输入和输出单价不同，必须分开统计。
        TokenUsage usage = new TokenUsage(120, 18);

        // Act + Assert：总数只用于粗略判断是否接近上下文窗口，对账要看分项。
        assertEquals(120, usage.getPromptTokens());
        assertEquals(18, usage.getCompletionTokens());
        assertEquals(138, usage.getTotalTokens());
    }

    /**
     * 规则：Token 数为负时拒绝构造 {@link TokenUsage}。
     *
     * <p><b>为什么重要：</b>负数 Token 在现实中不存在，所以它出现时表达的不是
     * 「用量」而是「我们的代码错了」：可能是 JSON 里字段名拼错拿到了默认值，
     * 可能是网关返回结构和预期不一致，可能是某处做减法算剩余预算时算漏了。
     * 这类解析错误必须当场炸出来 —— 它是唯一还能定位到出错位置的时刻。</p>
     *
     * <p><b>违反会怎样：</b>负数悄悄流进成本累加器，把统计<b>越算越少</b>。
     * 这比统计缺失更难发现：数字看起来是有的、是在增长的，只是偏低。
     * 没有任何报警会响，因为没有异常、没有空值，直到某天有人拿账单核对
     * 才发现系统里的数字一直只有真实值的一半。届时你面对的是几个月的历史数据，
     * 而且已经无从知道每条记录少算了多少。</p>
     */
    @Test
    public void shouldRejectNegativeTokens() {
        // Arrange + Act + Assert：负数说明解析响应时出了错，不能静默接受。
        assertThrows(
                IllegalArgumentException.class,
                () -> new TokenUsage(-1, 10)
        );
    }
}
