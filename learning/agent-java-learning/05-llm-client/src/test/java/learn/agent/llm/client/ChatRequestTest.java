package learn.agent.llm.client;

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

    /** {@link ChatRequest} 构造时复制消息列表：直接持有调用方的引用，日志里记的就不是真正发出去的内容，重试也会悄悄换掉请求。 */
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

    /** {@code getMessages()} 返回只读视图：只复制不封装的话，中间层能直接往请求内部那份列表里追加消息，绕过构造函数的全部校验。 */
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

    /** 空消息列表直接拒绝构造：空列表基本都是上游出了问题，放它走到 HTTP 层才 400，真实故障就被伪装成了外部依赖不稳定。 */
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

    /** {@code temperature} 两端越界都拒绝：温度多半来自配置而非字面量，不在构造时校验，配置写错要等白天流量进来才按请求逐个失败。 */
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

    /** {@code maxOutputTokens} 必须为正：这个值常是「窗口减去输入」算出来的，算出非正数说明该压缩历史了，而有些网关把 {@code 0} 当成不限制，成本闸门就此消失。 */
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

    /** {@code toString()} 只打结构信息不打正文：正文里是用户的手机号住址，日志一旦落盘、同步到第三方平台、进了备份，就不是删一条日志能了事的。 */
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

    /** {@link ChatMessage} 拒绝 {@code null} 但允许空字符串：空串是「模型没说话」这个真实状态，{@code null} 是代码漏了一步，混在一起下游就分不清，还要等序列化时才在离现场很远处爆出来。 */
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
