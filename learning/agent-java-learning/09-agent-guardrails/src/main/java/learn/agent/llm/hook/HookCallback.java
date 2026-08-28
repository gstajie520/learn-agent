package learn.agent.llm.hook;

/**
 * 一个 Hook 回调。
 *
 * <p>签名刻意窄：进去一个 {@link HookContext}，出来一个 {@link HookResult}，没有别的通路。
 * 回调拿不到 Loop、拿不到消息列表的可变引用、拿不到注册表，所以它<b>没有能力</b>
 * 直接改 Agent 的状态 —— 它只能「声明」自己想要什么，由 {@link HookRegistry} 和
 * Loop 决定这个声明能不能生效。</p>
 *
 * <p>这是本课的核心手法：<b>把扩展点的副作用建模成返回值</b>。如果 Hook 签名是
 * {@code void onPreTool(AgentLoop loop, ...)}，那它爱干什么就干什么，你既没法校验、
 * 也没法审计、更没法在两个 Hook 打起来的时候讲清楚谁赢。</p>
 *
 * <p>不允许返回 null。返回 null 的含义是「我什么都不想做」，而这件事已经有了
 * 明确的表达方式：{@link HookResult#noop()}。多一种表达同一件事的写法，
 * 只会让调用方多一处 null 判断。</p>
 */
public interface HookCallback {

    /**
     * 处理一次生命周期事件。
     *
     * <p>实现可以抛异常。抛出去之后各事件的处理方式<b>刻意不同</b>，
     * 见 {@link HookRegistry} 和 {@code HookedAgentLoop} 的说明。</p>
     *
     * @param context 本次事件的只读上下文
     * @return 结构化的影响声明，不能为 null
     */
    HookResult handle(HookContext context);
}
