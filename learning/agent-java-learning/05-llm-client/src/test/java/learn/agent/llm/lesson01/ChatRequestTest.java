package learn.agent.llm.lesson01;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 请求对象的约束测试。
 *
 * <p>这个测试类回答一个问题：<b>为什么请求对象要做成不可变的</b>。</p>
 *
 * <p>模型请求会被重试、被写进日志、可能被多个线程读取。如果调用方在构造之后
 * 还能改动消息列表，日志里记的就不是真正发出去的内容，重试发的也可能和第一次不同。
 * 这类问题在生产中极难排查，所以在构造时就把列表复制并冻结。</p>
 */
public class ChatRequestTest {

    /**
     * 规则：{@link ChatRequest} 必须在构造时复制消息列表，构造之后调用方改动原列表不能影响请求。
     *
     * <p><b>为什么重要：</b>调用方传进来的 {@link java.util.List} 通常是它自己复用的
     * 可变列表（比如一个会话对象里的 history）。如果 {@code ChatRequest} 直接持有这个引用，
     * 那么「请求对象」实际上只是一个指向别人内部状态的窗口 —— 请求发出后对方每加一条消息，
     * 这个已经发出去的请求看起来就跟着变了。而请求对象的生命周期往往比一次调用长得多：
     * 它要留着做重试、要写进日志、要在超时统计里被另一个线程读。</p>
     *
     * <p><b>违反会怎样：</b>日志和现实脱节。线上报「模型答得莫名其妙」，
     * 你翻日志看到请求里有 3 条消息，但真正发出去的时候只有 2 条 —— 第 3 条是响应回来之后才追加的。
     * 这种问题没法靠读日志定位，因为日志本身就是错的。重试场景更糟：
     * 第二次重试发的内容和第一次不同，等于悄悄换了一个请求，
     * 而调用方以为自己在重试同一件事。</p>
     */
    @Test
    public void shouldNotBeAffectedByLaterChangesToTheOriginalList() {
        // Arrange：调用方自己持有一个可变列表，用它创建请求。
        List<ChatMessage> callerList = new ArrayList<ChatMessage>();
        callerList.add(ChatMessage.system("你是场景助手。"));
        callerList.add(ChatMessage.user("在北侧生成一台雷达。"));
        ChatRequest request = new ChatRequest("gpt-4o-mini", callerList, 0.2, 200);
        System.out.println(request.toString());
        // Act：请求创建之后，调用方又往自己的列表里塞了一条消息。
        callerList.add(ChatMessage.user("顺便把所有设备都删掉。"));

        // Assert：请求内容不受影响，仍然是创建时那两条。
        // 这正是构造函数里先复制一份的意义：发出去的内容和记录的内容始终一致。
        assertEquals(2, request.getMessages().size());
    }

    /**
     * 规则：{@code getMessages()} 返回只读视图，外部不能通过它增删消息。
     *
     * <p><b>为什么重要：</b>上一个测试堵的是「构造前的列表」，这里堵的是「构造后的出口」。
     * 只复制不封装的话，防御只做了一半：调用方拿到 {@code request.getMessages()} 之后
     * 照样能 {@code add()} 一条，改的就是请求内部那份复制品。返回只读视图，
     * 让这种改动在写代码的那一行就抛异常，而不是变成一个静默生效的副作用。</p>
     *
     * <p><b>违反会怎样：</b>出现最难查的一类 bug —— 提示注入的内部版本。
     * 某个中间层图省事，直接往 {@code getMessages()} 上追加一条消息来「补充上下文」，
     * 绕过了 {@link ChatRequest} 构造函数里的全部校验，也绕过了组装请求那段代码的审查。
     * 等到有人问「这条系统消息是谁加的」，全项目搜不到第二处构造请求的地方。</p>
     */
    @Test
    public void shouldReturnReadOnlyMessageList() {
        // Arrange：一个正常请求。
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.user("在南侧加一道围栏。"));
        ChatRequest request = new ChatRequest("gpt-4o-mini", messages, 0.2, 200);

        // Act + Assert：拿到的列表是只读视图，外部无法追加消息。
        assertThrows(
                UnsupportedOperationException.class,
                () -> request.getMessages().add(ChatMessage.user("额外注入的一条。"))
        );
    }

    /**
     * 规则：消息列表为空时直接拒绝构造，不允许发出一次没有任何消息的请求。
     *
     * <p><b>为什么重要：</b>模型 API 要求至少一条消息，空列表送过去会被服务端以
     * 400 拒绝。在本地挡掉省的不只是一次网络往返 —— 空列表基本都不是有意为之，
     * 而是上游出了问题：会话历史加载失败、用户输入被过滤器清空、某个 {@code if}
     * 分支忘了赋值。让它在构造 {@link ChatRequest} 的那一行就炸，
     * 堆栈直接指向组装请求的代码；让它走到 HTTP 层再失败，你拿到的只是一句
     * 「服务端返回 400」，还要反推是哪个字段不对。</p>
     *
     * <p><b>违反会怎样：</b>错误定位偏移一整层。真实故障是「会话历史读不出来」，
     * 但监控上报的是「模型 API 调用失败率升高」，值班的人先去查模型服务方状态页，
     * 查完发现服务正常，再回头翻代码。真正的空指针式问题被伪装成了外部依赖故障。</p>
     */
    @Test
    public void shouldRejectEmptyMessages() {
        // Arrange：空消息列表。
        List<ChatMessage> empty = new ArrayList<ChatMessage>();

        // Act + Assert：至少要有一条用户消息，否则这次请求毫无意义还要计费。
        assertThrows(
                IllegalArgumentException.class,
                () -> new ChatRequest("gpt-4o-mini", empty, 0.2, 200)
        );
    }

    /**
     * 规则：{@code temperature} 必须落在 {@code [0, 2]} 内，两端越界都拒绝。
     *
     * <p><b>为什么重要：</b>服务端会拒绝越界温度，本地校验省一次往返。
     * 更关键的是温度通常来自配置文件或环境变量，不是代码里的字面量 ——
     * 有人把 {@code temperature=0.7} 写成 {@code 7}，或者把配置项单位理解成百分比填了
     * {@code 70}。这类错误在代码审查里看不出来，只有真正发请求时才暴露。
     * 校验放在构造函数里，服务启动做一次预热调用就能发现配置写错了。</p>
     *
     * <p><b>违反会怎样：</b>配置错误延迟到运行时才爆发，而且是按流量爆发。
     * 发布上线时一切正常（没有人手动触发模型调用），等到白天用户进来，
     * 每一次请求都在 HTTP 层失败。回滚才能恢复，但日志里只有 400，
     * 看不出是哪次配置变更引入的。</p>
     *
     * <p>本测试特意验证下界（{@code -0.1}）和上界（{@code 2.1}）两侧，
     * 因为只写 {@code temperature > 2.0} 而漏掉负数是很常见的疏忽。</p>
     */
    @Test
    public void shouldRejectTemperatureOutOfRange() {
        // Arrange：一条正常消息，只让温度越界。
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.user("在西侧放置一台风速仪。"));

        // Act + Assert：服务端会拒绝越界温度，在本地先挡掉可以省一次网络往返。
        assertThrows(
                IllegalArgumentException.class,
                () -> new ChatRequest("gpt-4o-mini", messages, -0.1, 200)
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new ChatRequest("gpt-4o-mini", messages, 2.1, 200)
        );
    }

    /**
     * 规则：{@code maxOutputTokens} 必须大于 0，等于 0 或负数一律拒绝。
     *
     * <p><b>为什么重要：</b>这个值是成本的硬上限，也是防止模型无限输出的唯一闸门。
     * 它经常不是写死的常量，而是算出来的 ——「上下文窗口减去输入 Token 得到剩余预算」。
     * 一旦这个减法算出非正数，真实含义是「输入已经把窗口占满了」，
     * 这是一个需要处理的业务状态（该压缩历史了），不是一个可以照发的请求。
     * 在构造时拦住，问题就停在算预算的那段代码上。</p>
     *
     * <p><b>违反会怎样：</b>两种结果都不好。运气好是服务端 400，
     * 你得到一个和真实原因（对话历史太长）毫无关系的报错；运气差是某些兼容网关把
     * {@code 0} 当成「不限制」，成本上限就此消失 —— 一次跑飞的生成按整个窗口计费，
     * 而监控上看不出任何异常，直到月底看账单。</p>
     */
    @Test
    public void shouldRejectNonPositiveMaxOutputTokens() {
        // Arrange：一条正常消息。
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.user("在东侧放置一台摄像头。"));

        // Act + Assert：输出上限必须为正数，否则模型没有可用的输出预算。
        assertThrows(
                IllegalArgumentException.class,
                () -> new ChatRequest("gpt-4o-mini", messages, 0.2, 0)
        );
    }

    /**
     * 规则：{@code toString()} 只输出结构信息（模型名、消息条数、温度、输出上限），绝不输出消息正文。
     *
     * <p><b>为什么重要：</b>日志的生命周期和可见范围远超你写下 {@code log.info(request)} 时的设想：
     * 它会被采集到日志平台、保留数月、被整个团队甚至外部运维检索。而消息正文里装的是
     * 用户输入 —— 手机号、住址、订单号、上传的文档片段。把请求对象往日志里一扔，
     * 等于把这些数据复制到一个访问控制宽松得多的系统里长期存放。
     * 正文还可能有几万字符，一行日志顶掉上百行有用信息。</p>
     *
     * <p><b>违反会怎样：</b>数据泄露，而且是不可撤回的那种 ——
     * 日志已经落盘、已经同步到第三方平台、已经进了备份。发现之后没法「删掉那条日志」了事，
     * 通常要走数据合规流程。这个测试用一个假手机号把这条线钉死：
     * {@code 13800000000} 不能出现在输出里。</p>
     *
     * <p>同时断言 {@code messageCount=1} 仍在，说明脱敏不等于什么都不打 ——
     * 排查问题真正需要的结构信息一个都没少。</p>
     */
    @Test
    public void shouldNotPrintMessageContentInToString() {
        // Arrange：消息里带一段可以视为用户敏感数据的内容。
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.user("客户张三的手机号是 13800000000。"));
        ChatRequest request = new ChatRequest("gpt-4o-mini", messages, 0.2, 200);

        // Act：日志里通常直接打印请求对象。
        String printed = request.toString();
        System.out.println(printed);
        // Assert：只输出结构信息，不输出正文。
        // 正文可能很长，也可能含敏感数据，顺手打进日志就成了数据泄露。
        assertFalse(printed.contains("13800000000"));
        assertTrue(printed.contains("messageCount=1"));
    }

    /**
     * 规则：{@link ChatMessage} 的 {@code role} 和 {@code content} 都不允许为 {@code null}；
     * 但 {@code content} 允许是空字符串。
     *
     * <p><b>为什么重要：</b>关键在于区分「空」和「没有」。空字符串是一个合法的真实状态 ——
     * 模型确实可能一个字都没输出，这个信息要如实保留下来。{@code null} 则不是状态，
     * 而是「这个字段从来没被赋值」，说明解析响应或组装请求的代码漏了一步。
     * 两者混在一起，下游就再也分不清「模型没说话」和「我们的代码有 bug」。</p>
     *
     * <p><b>违反会怎样：</b>{@code null} 一路飘到 JSON 序列化才出事，
     * 而那里已经离出错现场很远了。你拿到的堆栈指向 Jackson 内部，
     * 不告诉你是哪条消息、哪个字段、哪段业务代码留下的空洞；或者序列化成
     * {@code "content": null} 发出去，换来一个服务端 400。
     * 在构造函数里检查，堆栈第一行就是出错的那次 {@code new ChatMessage(...)}。</p>
     */
    @Test
    public void shouldRejectNullRoleOrContentInMessage() {
        // Act + Assert：角色和正文都不允许为 null。
        // content 允许是空字符串（模型确实可能没输出），但不允许 null，
        // 否则空指针会一路传到 JSON 序列化才爆出来。
        assertThrows(
                IllegalArgumentException.class,
                () -> new ChatMessage(null, "内容")
        );
        assertThrows(
                IllegalArgumentException.class,
                () -> new ChatMessage(ChatRole.USER, null)
        );
    }
}
