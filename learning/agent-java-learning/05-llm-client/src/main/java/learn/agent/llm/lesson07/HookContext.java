package learn.agent.llm.lesson07;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRole;
import learn.agent.llm.lesson04.PreparedToolCall;
import learn.agent.llm.lesson04.ToolExecutionResult;

/**
 * 一次 Hook 回调看得到的数据。
 *
 * <p>核心设计：<b>每个事件只带它自己那一份数据</b>。四个事件共用这一个类，
 * 但字段归属由构造器强制：</p>
 *
 * <table border="1">
 *   <tr><th>事件</th><th>可用字段</th></tr>
 *   <tr><td>UserPromptSubmit</td><td>{@code message}（必须 user 角色）</td></tr>
 *   <tr><td>PreToolUse</td><td>{@code prepared}（必须 ready 态）</td></tr>
 *   <tr><td>PostToolUse</td><td>{@code prepared} + {@code result}</td></tr>
 *   <tr><td>Stop</td><td>{@code history} + {@code stopHookActive}</td></tr>
 * </table>
 *
 * <p><b>为什么不让四个事件各写一个类？</b>那样 {@code HookCallback} 的签名就没法
 * 统一，注册表要么写四个 register 方法，要么用泛型把类型参数一路传下去。
 * 用一个类 + 构造器校验，代价是多写一段 {@link #validateEventFields}，
 * 换来的是「注册表只认识一种回调」。</p>
 *
 * <p><b>为什么要拦「带了别人的字段」而不是默默忽略？</b>因为一个 Stop Hook 如果
 * 能读到 {@code prepared}，它就会去读；等到某天有人把它注册到 PreToolUse 上，
 * 行为会静默变化。更直接的风险是<b>伪造</b>：Stop Hook 自己造一个
 * {@code result} 塞进上下文，看起来就像某个工具真的执行过。字段归属由类型边界
 * 守住，比靠文档约定可靠。</p>
 *
 * <p>本类不可变：{@code history} 存副本，getter 返回不可修改视图。Hook 是别人
 * 写的代码，它不该有能力改动 Agent 的内部状态 —— 它只能<b>返回</b>
 * {@link HookResult} 声明自己想要什么。</p>
 */
public final class HookContext {

    /** 哪个生命周期事件。 */
    private final HookEvent event;

    /** UserPromptSubmit 专属：用户刚提交的消息。 */
    private final ChatMessage message;

    /** PreToolUse / PostToolUse 专属：已准备好的调用。 */
    private final PreparedToolCall prepared;

    /** PostToolUse 专属：工具执行结果。 */
    private final ToolExecutionResult result;

    /** Stop 专属：当前会话历史快照。 */
    private final List<ChatMessage> history;

    /**
     * Stop 专属：是否已经请求过一次续跑。
     *
     * <p>这个字段的存在只有一个目的：<b>阻止 Stop Hook 无限续跑自己</b>。
     * Stop Hook 可以说「别停，再来一轮」，但如果它每次都这么说，循环就永远
     * 不结束。所以第二次进 Stop 时这个标志为 true，注册表会把它的续跑请求丢掉。</p>
     */
    private final boolean stopHookActive;

    private HookContext(HookEvent event,
                        ChatMessage message,
                        PreparedToolCall prepared,
                        ToolExecutionResult result,
                        List<ChatMessage> history,
                        boolean stopHookActive) {
        if (event == null) {
            throw new HookContractException("event 不能为空");
        }
        this.event = event;
        this.message = message;
        this.prepared = prepared;
        this.result = result;
        List<ChatMessage> copy = new ArrayList<ChatMessage>();
        if (history != null) {
            for (ChatMessage each : history) {
                if (each == null) {
                    throw new HookContractException("history 不能包含 null");
                }
                copy.add(each);
            }
        }
        this.history = copy;
        this.stopHookActive = stopHookActive;
        validateEventFields();
    }

    /** 用户提交了一条消息。 */
    public static HookContext userPromptSubmit(ChatMessage message) {
        return new HookContext(HookEvent.USER_PROMPT_SUBMIT, message, null, null, null, false);
    }

    /** 工具即将执行。 */
    public static HookContext preToolUse(PreparedToolCall prepared) {
        return new HookContext(HookEvent.PRE_TOOL_USE, null, prepared, null, null, false);
    }

    /** 工具已经执行完。 */
    public static HookContext postToolUse(PreparedToolCall prepared, ToolExecutionResult result) {
        return new HookContext(HookEvent.POST_TOOL_USE, null, prepared, result, null, false);
    }

    /** 循环准备结束。 */
    public static HookContext stop(List<ChatMessage> history, boolean stopHookActive) {
        return new HookContext(HookEvent.STOP, null, null, null, history, stopHookActive);
    }

    /**
     * 按事件校验字段归属。
     *
     * <p>两个方向都要查：该有的必须有（PreToolUse 没有 prepared 就没法工作），
     * 不该有的必须没有（Stop 带着 result 说明有人在伪造工具执行状态）。</p>
     */
    private void validateEventFields() {
        if (event == HookEvent.USER_PROMPT_SUBMIT) {
            if (message == null || message.getRole() != ChatRole.USER) {
                throw new HookContractException("UserPromptSubmit 需要一条 user 消息");
            }
            requireAbsent(prepared == null && result == null && history.isEmpty() && !stopHookActive);
            return;
        }
        if (event == HookEvent.PRE_TOOL_USE) {
            requireReady(prepared, "PreToolUse");
            requireAbsent(message == null && result == null && history.isEmpty() && !stopHookActive);
            return;
        }
        if (event == HookEvent.POST_TOOL_USE) {
            requireReady(prepared, "PostToolUse");
            if (result == null) {
                throw new HookContractException("PostToolUse 需要工具执行结果");
            }
            requireAbsent(message == null && history.isEmpty() && !stopHookActive);
            return;
        }
        // Stop：history 允许为空（模型第一轮就给了最终答复），但不能带工具字段。
        requireAbsent(message == null && prepared == null && result == null);
    }

    /**
     * Hook 只应看到已经过白名单和参数校验的调用。
     *
     * <p>把 failed 态的 {@link PreparedToolCall} 交给 Hook 会造成一种错觉：
     * Hook 以为这次调用即将执行，于是去改参数、提权限建议，而实际上循环早就
     * 决定回传错误了。所以循环里 prepare 失败是<b>直接返回</b>，压根不触发 Pre Hook。</p>
     */
    private static void requireReady(PreparedToolCall prepared, String eventName) {
        if (prepared == null) {
            throw new HookContractException(eventName + " 需要一次已准备好的工具调用");
        }
        if (prepared.isFailed()) {
            throw new HookContractException(eventName + " 不接受准备失败的调用");
        }
        if (prepared.getDefinition() == null || prepared.getArguments() == null) {
            throw new HookContractException(eventName + " 的调用缺少 definition 或 arguments");
        }
    }

    private void requireAbsent(boolean onlyOwnFields) {
        if (!onlyOwnFields) {
            throw new HookContractException(
                    event.getWireValue() + " 收到了属于其他事件的字段");
        }
    }

    public HookEvent getEvent() {
        return event;
    }

    /** @return UserPromptSubmit 的用户消息；其他事件为 null */
    public ChatMessage getMessage() {
        return message;
    }

    /** @return Pre/PostToolUse 的调用；其他事件为 null */
    public PreparedToolCall getPrepared() {
        return prepared;
    }

    /** @return PostToolUse 的执行结果；其他事件为 null */
    public ToolExecutionResult getResult() {
        return result;
    }

    /** @return Stop 的历史快照，不可修改；其他事件为空列表 */
    public List<ChatMessage> getHistory() {
        return Collections.unmodifiableList(history);
    }

    /** @return Stop 是否已经请求过一次续跑 */
    public boolean isStopHookActive() {
        return stopHookActive;
    }

    @Override
    public String toString() {
        return "HookContext{event=" + event.getWireValue()
                + (prepared == null ? "" : ", tool=" + prepared.getCall().getName())
                + (history.isEmpty() ? "" : ", history=" + history.size())
                + '}';
    }
}
