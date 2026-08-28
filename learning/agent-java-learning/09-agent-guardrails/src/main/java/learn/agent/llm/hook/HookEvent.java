package learn.agent.llm.hook;

/**
 * Hook 的生命周期事件。<b>只有四个，而且是封闭集合。</b>
 *
 * <p>为什么是枚举而不是字符串：Hook 是给外部代码用的扩展点，事件名会被写进
 * 注册调用里。用字符串的话，{@code register("PreToolCall", cb)} 这种拼写错误
 * 会静默地永不触发 —— 注册成功、回调从不执行、没有任何报错。这是最难查的一类
 * 缺陷，因为「什么都没发生」不产生日志。枚举把这个错误提前到编译期。</p>
 *
 * <p>四个事件覆盖一次运行里全部可以被外部观察或干预的位置：</p>
 * <pre>
 * 用户输入 → 【UserPromptSubmit】
 *   ↓ 调模型
 *   ↓ prepare
 *   ↓ 【PreToolUse】     ← 唯一可以改参数、可以阻断、可以给权限建议的位置
 *   ↓ 权限裁决
 *   ↓ handler 执行
 *   ↓ 【PostToolUse】    ← 唯一可以改结果、可以叫停后续调用的位置
 *   ↓ 模型给出最终答复
 * 【Stop】               ← 唯一可以要求再来一轮的位置
 * </pre>
 *
 * <p><b>为什么不能再加事件</b>：每个事件都是一个「外部代码可以介入 Agent 内部
 * 状态」的缺口。缺口越多，「这次运行到底做了什么」越难推理。四个事件的选择标准
 * 是「这个位置有没有别的办法介入」—— 有别的办法就不该开 Hook。</p>
 *
 * @see HookRegistry
 */
public enum HookEvent {

    /** 用户输入进入历史之前。只能追加系统上下文，不能改写用户说的话。 */
    USER_PROMPT_SUBMIT("UserPromptSubmit"),

    /** 工具已经 prepare 完、还没裁决权限。参数改写、阻断、权限建议都在这里。 */
    PRE_TOOL_USE("PreToolUse"),

    /** 工具已经执行完。可以改写结果，也可以叫停这一轮剩下的调用。 */
    POST_TOOL_USE("PostToolUse"),

    /** 模型给出了最终答复。唯一可以要求「再来一轮」的位置。 */
    STOP("Stop");

    /** 对外的事件名，和 TypeScript 教材、日志里的写法一致。 */
    private final String wireValue;

    HookEvent(String wireValue) {
        this.wireValue = wireValue;
    }

    public String getWireValue() {
        return wireValue;
    }

    @Override
    public String toString() {
        return wireValue;
    }
}
