package learn.agent.llm.hook;

/**
 * Hook 违反契约时抛出。
 *
 * <p>「违反契约」指的不是 Hook 内部业务出错，而是它<b>越权</b>了：在
 * {@code Stop} 事件里改工具参数、用 {@code PostToolUse} 提权限建议、
 * 改参数时把工具名换了。这些不是运行时故障，是扩展点被误用。</p>
 *
 * <p>为什么要和普通异常分开：两者的处理方式不同。Hook 里业务抛异常
 * （比如它调的下游服务挂了）应当变成一条工具错误回传给模型，让运行继续；
 * 契约违反说明<b>代码写错了</b>，回传给模型没有意义 —— 模型改不了 Hook
 * 的代码。所以循环里靠这个类型区分错误码：{@code hook_contract_error}
 * 对应「你的 Hook 写错了」，{@code hook_execution_error} 对应
 * 「你的 Hook 跑挂了」。运维看到前者应该去改代码，看到后者应该去查下游。</p>
 *
 * <p>继承 {@link RuntimeException} 而不是受检异常：{@code HookCallback}
 * 的签名如果声明 {@code throws}，每个只想加一行日志的 Hook 都得写 try-catch。
 * 这和第 4 课「工具失败是返回值不是异常」不矛盾 —— 那条讲的是<b>预期内</b>的
 * 失败，契约违反不在预期内。</p>
 */
public class HookContractException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public HookContractException(String message) {
        super(message);
    }
}
