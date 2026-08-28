package learn.agent.llm.lesson06;

/**
 * 审计落点：记录「谁请求了什么、最终判成什么」。
 *
 * <p>参数是完整的请求快照加最终决定，不是几个扁平字段。因为「事后要查什么」
 * 现在猜不准 —— 可能要查身份，可能要查参数，可能要查是哪条规则拦的。
 * 传整个对象，实现方自己挑。</p>
 *
 * <p><b>审计是闸门，不是日志。</b>{@link #record} 抛异常时
 * {@link PermissionPolicy#decide} 会一起抛，最终 handler 不执行。
 * 习惯上写日志都要包一层 try-catch 吞掉，这里绝不能吞：
 * 吞了就等于「决定没留痕，但副作用发生了」，正好是审计要防的那种情况。</p>
 */
public interface AuditSink {

    /**
     * 记录一条审计。
     *
     * <p>只会在<b>最终决定</b>产生后调用，所以 decision 必然是 allow 或 deny，
     * 永远不会是 ask 或 passthrough。</p>
     */
    void record(PermissionRequest request, PermissionDecision decision);
}
