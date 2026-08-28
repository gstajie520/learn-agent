package learn.agent.llm.permission;

import learn.agent.llm.tool.ToolExecutionResult;

/**
 * 一次权限裁决的结果：三元组 {@code (behavior, reason, source)}。
 *
 * <p>为什么不只是一个枚举：出了事要能回答「谁拒的、为什么拒」。只有 behavior
 * 的话，审计日志里就只剩一个 deny，没法追责，也没法告诉用户该找谁开权限。</p>
 *
 * <p>{@code reason} 会被回传给模型（进而可能被用户看到），所以写的是业务语言，
 * 不带类名和堆栈；{@code source} 是稳定的规则名，给审计和排查用。</p>
 */
public final class PermissionDecision {

    /** 裁决结论。 */
    private final PermissionBehavior behavior;

    /** 给人看的原因，会回传给模型。 */
    private final String reason;

    /** 谁做的这个决定：规则名 / workspace-boundary / approval / default。 */
    private final String source;

    public PermissionDecision(PermissionBehavior behavior, String reason, String source) {
        if (behavior == null) {
            throw new PermissionContractException("behavior 不能为空");
        }
        // reason 和 source 都强制非空白：审计里出现一条空原因的 deny，等于没记。
        if (reason == null || reason.trim().isEmpty()) {
            throw new PermissionContractException("reason 不能为空，否则审计记录无法追责");
        }
        if (source == null || source.trim().isEmpty()) {
            throw new PermissionContractException("source 不能为空，否则不知道是谁做的决定");
        }
        this.behavior = behavior;
        this.reason = reason;
        this.source = source;
    }

    public PermissionBehavior getBehavior() {
        return behavior;
    }

    public String getReason() {
        return reason;
    }

    public String getSource() {
        return source;
    }

    /** 是否放行。这是唯一允许真正执行 handler 的条件。 */
    public boolean isAllowed() {
        return behavior == PermissionBehavior.ALLOW;
    }

    /**
     * 把一条 deny 转成回传给模型的工具错误。
     *
     * <p>刻意只允许 deny 调用：{@code ask} 和 {@code passthrough} 是<b>中间态</b>，
     * 它们必须先在 {@link PermissionPolicy} 内部被收敛成 allow 或 deny。
     * 如果一个 ask 能走到这里，说明收敛逻辑漏了分支 —— 那时候宁可炸掉，
     * 也不要把「还没问过人」当成「已经拒绝了」糊过去。</p>
     */
    public ToolExecutionResult toToolResult() {
        if (behavior != PermissionBehavior.DENY) {
            throw new PermissionContractException(
                    "只有最终的 deny 才能转成工具结果，当前是 " + behavior.getWireValue());
        }
        return ToolExecutionResult.error("permission_denied", reason);
    }

    /**
     * 按三元组比较。
     *
     * <p>为什么值类型要有 {@code equals}：{@code reason} 和 {@code source} 是
     * 本课的<b>可观测输出</b>——「同级冲突取最早那条」这类断言，断的就是它们。
     * 没有 {@code equals} 的话，测试里 {@code assertEquals(expected, actual)}
     * 退化成比较对象地址，写起来像在断言内容，实际上永远只在断言身份。</p>
     */
    @Override
    public boolean equals(Object o) {
        if (this == o) {
            return true;
        }
        if (!(o instanceof PermissionDecision)) {
            return false;
        }
        PermissionDecision other = (PermissionDecision) o;
        return behavior == other.behavior
                && reason.equals(other.reason)
                && source.equals(other.source);
    }

    @Override
    public int hashCode() {
        int result = behavior.hashCode();
        result = 31 * result + reason.hashCode();
        result = 31 * result + source.hashCode();
        return result;
    }

    @Override
    public String toString() {
        return "PermissionDecision{" + behavior.getWireValue()
                + ", source=" + source + ", reason=" + reason + "}";
    }
}
