package learn.agent.llm.loop;

import java.util.List;

import learn.agent.llm.client.ChatMessage;

/**
 * 循环的「每轮观察点」：请求前给一次临时上下文，工具轮后记一笔账。
 *
 * <h3>为什么循环需要这个扩展点，而 Hook 顶替不了</h3>
 * <p>Hook 的每一种返回值（改参数、改结果、拦下、续写）都在<b>改变对话</b> ——
 * 它注入的 {@code additionalContext} 会被 append 进 messages，从此永久留在历史里。
 * 而有一类需求要的恰恰是<b>不改变对话</b>：只影响下一次请求，发完就丢。
 * 会话计划的陈旧提醒就是典型 —— 写进历史的话，跑三十轮会攒下十条一模一样的
 * 「保持计划更新」，每轮都为它付 token，还污染了可回放的历史（那些话没有任何人说过）。</p>
 *
 * <p>这不是 Hook 的缺陷，是它的设计目标决定的：Hook 的词汇表里没有
 * 「临时的、不进历史的上下文」这个概念。所以需要一个单独的扩展点，
 * 也就是本接口。</p>
 *
 * <h3>两个时机各自的约束</h3>
 * <table border="1">
 *   <caption>两个方法的语义差异</caption>
 *   <tr><th></th><th>{@link #beforeModel()}</th><th>{@link #recordToolRound(List)}</th></tr>
 *   <tr><td>触发时机</td><td>每次模型请求<b>之前</b></td><td>一轮工具结果<b>全部落盘之后</b></td></tr>
 *   <tr><td>产出去哪</td><td>只拼进这一次请求，<b>不进历史</b></td><td>无产出，只记账</td></tr>
 *   <tr><td>是否纯函数</td><td><b>不是</b> —— 允许有副作用（如读取即清零）</td><td>不是</td></tr>
 * </table>
 *
 * <p><b>{@code beforeModel()} 每轮只能调一次。</b>它允许在被调用时更新内部状态
 * （典型实现是「发出提醒后立刻清零，避免每轮重复注入」），所以多调一次就会
 * 少发一条提醒。循环里必须把结果存进局部变量，不能为了「再看一眼」重复调用。</p>
 *
 * <p><b>{@code recordToolRound} 按「轮」而不是按「工具」触发。</b>它拿到的是这一轮
 * 里调用过的全部工具名。等整轮结果都写进历史后再触发，观察器就永远看不到
 * 「assistant 已入历史、tool 结果还没入」这种半成品协议状态。</p>
 *
 * @see learn.agent.llm.loop.AgentLoop
 */
public interface ToolRoundObserver {

    /**
     * 请求前的临时上下文。
     *
     * <p>返回的消息只拼进<b>这一次</b>模型请求，不写进消息历史。
     * 没有内容时返回空列表，不要返回 null。</p>
     *
     * <p><b>有副作用，每轮只调一次。</b>见类注释。</p>
     *
     * @return 临时消息，永远非 null
     */
    List<ChatMessage> beforeModel();

    /**
     * 记一轮工具调用。
     *
     * <p>在这一轮<b>全部</b>工具结果都追加进历史之后触发，参数是这一轮调用过的
     * 所有工具名。没有工具调用的轮次（模型直接给答复）<b>不</b>触发。</p>
     *
     * @param toolNames 本轮调用过的工具名，非 null；实现方不应修改它
     */
    void recordToolRound(List<String> toolNames);
}
