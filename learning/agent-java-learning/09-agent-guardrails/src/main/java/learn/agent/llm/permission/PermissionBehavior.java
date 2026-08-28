package learn.agent.llm.permission;

/**
 * 权限决定的四种状态。
 *
 * <p>为什么是四态而不是三态：{@link #ASK} 和 {@link #PASSTHROUGH} 是<b>中间态</b>，
 * 只在 {@link PermissionPolicy} 内部存在；{@link #ALLOW} 和 {@link #DENY} 是<b>最终态</b>，
 * 是唯一允许离开 policy 的两个值。</p>
 *
 * <p>把这四个值放进一个枚举，但只让两个能出门，是本课最容易被写坏的地方。
 * 很自然会想「三态就够了：允许、拒绝、问一下」。但少了 PASSTHROUGH，
 * 规则就没法表达「这条规则对本次请求没有意见」——它只能被迫表态，
 * 于是任何一条无关规则都会参与裁决。</p>
 *
 * <p>两个中间态的归宿不同：</p>
 * <ul>
 *   <li>{@code ASK} 必须交给 {@link ApprovalProvider} 收敛成 allow 或 deny；</li>
 *   <li>{@code PASSTHROUGH} 表示无人反对，归一为 {@code ALLOW}。</li>
 * </ul>
 */
public enum PermissionBehavior {

    /** 放行。唯一会真正执行 handler 的状态。 */
    ALLOW("allow"),

    /** 拒绝。转成 {@code permission_denied} 工具错误回传给模型，handler 不执行。 */
    DENY("deny"),

    /** 需要人工裁决。<b>中间态</b>，必须被审批器收敛，绝不允许离开 policy。 */
    ASK("ask"),

    /** 无意见 / 弃权。<b>中间态</b>，无人反对时归一为 {@code ALLOW}。 */
    PASSTHROUGH("passthrough");

    /** 日志与审计里使用的字面值。 */
    private final String wireValue;

    PermissionBehavior(String wireValue) {
        this.wireValue = wireValue;
    }

    public String getWireValue() {
        return wireValue;
    }

    /** 是否是允许放行的最终态。 */
    public boolean isAllowed() {
        return this == ALLOW;
    }

    /** 是否是可以离开 policy 的最终态（只有 allow 和 deny）。 */
    public boolean isFinal() {
        return this == ALLOW || this == DENY;
    }
}
