package learn.agent.llm.plan;

import java.util.Collections;
import java.util.List;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.hook.HookCallback;
import learn.agent.llm.hook.HookContext;
import learn.agent.llm.hook.HookEvent;
import learn.agent.llm.hook.HookRegistry;
import learn.agent.llm.hook.HookResult;
import learn.agent.llm.tool.ToolDefinition;

/**
 * 把 {@link TodoTracker} 接到第 7 课 {@code HookedAgentLoop} 上的桥。
 *
 * <p><b>本课没有新写循环。</b>第 6 课记下过一笔设计债：第 5 课的
 * {@code AgentLoop} 把执行骨架封在私有方法里，导致第 6 课只能重写一遍循环，
 * 第 7 课又重写一遍。到本课如果再写第四遍，那就是第三次犯同样的错误。</p>
 *
 * <p>所以本课的问法变成：<b>「计划提醒能不能只靠已有的扩展点实现？」</b>
 * 答案是能 —— 用 {@link HookEvent#POST_TOOL_USE}。每轮工具执行完，Hook 都会
 * 被调到，正好是「记一笔这轮调了什么工具」和「该不该提醒」的时机。</p>
 *
 * <h3>但这条路有一个真实的语义损失，必须说清楚</h3>
 * <p>Hook 返回的 {@code additionalContext} 会被循环 <b>append 进 messages</b>，
 * 也就是<b>进了消息历史</b>。而 {@link TodoTracker#beforeModel()} 的契约是
 * 「请求级临时消息，不进历史」。两者的差别是实打实的：</p>
 *
 * <table border="1">
 *   <caption>两种注入方式的差别</caption>
 *   <tr><th></th><th>{@code beforeModel()}（教材语义）</th><th>本 Hook（现有扩展点）</th></tr>
 *   <tr><td>提醒出现次数</td><td>只在下一次请求</td><td>之后每一次请求都带着</td></tr>
 *   <tr><td>token 代价</td><td>一次</td><td>剩余轮次 × 每轮一次</td></tr>
 *   <tr><td>对话回放</td><td>干净</td><td>混进了用户没说过的话</td></tr>
 * </table>
 *
 * <p>为什么还是保留这个类：因为它是<b>「Hook 是执行期扩展点，表达不了请求期
 * 临时上下文」这个结论的代码证据</b>。这个缺口正是本阶段第 5 课（动态 Prompt
 * 组装）要解决的问题 —— 那一课引入的 Provider 机制，就是专门为「每次请求
 * 重新生成、不累积」这件事设计的。</p>
 *
 * <p>换句话说：<b>先撞到墙，再解释为什么需要那扇门。</b>如果直接跳到第 5 课
 * 给出 Provider，你只会觉得「哦，又多一个抽象」。</p>
 *
 * <p>用法：</p>
 * <pre>{@code
 * TodoTracker tracker = new TodoTracker();
 * ToolRegistry registry = new ToolRegistry();
 * registry.register(tracker.getToolDefinition());
 *
 * HookRegistry hooks = new HookRegistry();
 * PlanReminderHook.install(hooks, tracker);
 * }</pre>
 */
public final class PlanReminderHook implements HookCallback {

    /** 被观察的计划状态。 */
    private final TodoTracker tracker;

    public PlanReminderHook(TodoTracker tracker) {
        if (tracker == null) {
            throw new IllegalArgumentException("tracker 不能为 null");
        }
        this.tracker = tracker;
    }

    /**
     * 注册到 PostToolUse。
     *
     * <p>提供这个静态方法而不是让调用方自己 {@code register}，是为了把
     * 「这个 Hook 只能挂在 PostToolUse 上」这件事固定下来。挂错事件的后果
     * 很隐蔽：挂到 PreToolUse 上，计数会在工具<b>执行前</b>就加一，
     * 于是被权限拒绝的调用也会被算成「推进了一轮」。</p>
     */
    public static PlanReminderHook registerOn(HookRegistry hooks, TodoTracker tracker) {
        if (hooks == null) {
            throw new IllegalArgumentException("hooks 不能为 null");
        }
        PlanReminderHook hook = new PlanReminderHook(tracker);
        hooks.register(HookEvent.POST_TOOL_USE, hook);
        return hook;
    }

    @Override
    public HookResult handle(HookContext context) {
        ToolDefinition definition = context.getPrepared() == null
                ? null
                : context.getPrepared().getDefinition();
        if (definition == null) {
            // 走到 PostToolUse 却没有工具定义，说明上游给的上下文不完整。
            // 不抛异常：PostToolUse 的异常会被降级成工具错误回传给模型，
            // 而「记账失败」不该让模型以为它的工具调用出了问题。
            return HookResult.noop();
        }

        tracker.recordToolRound(Collections.singletonList(definition.getName()));

        List<ChatMessage> reminder = tracker.beforeModel();
        if (reminder.isEmpty()) {
            return HookResult.noop();
        }
        // additionalContext 只接受 SYSTEM 角色（第 7 课的三条角色约束之一）。
        // 提醒本来就该是 system：它是运行时的规则重申，不是用户的新要求。
        return HookResult.builder().addAllContext(reminder).build();
    }
}
