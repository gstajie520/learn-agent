package learn.agent.llm.lesson06;

/**
 * 一条权限规则：谓词 + 结论。
 *
 * <p>为什么规则是<b>代码谓词</b>而不是一张配置表：真实的权限条件是
 * 「谁、对哪台设备、在什么场景下」的组合，用声明式 DSL 表达要么表达不了，
 * 要么得先造一门小语言。谓词直接看 {@link PermissionRequest}，
 * 想看工具名看工具名，想看参数看参数。</p>
 *
 * <p>代价也说清楚：规则散落在代码里，没法在运行时改。生产上通常两层
 * 都要 —— 配置表管粗粒度开关，谓词管复杂条件。本课只做谓词。</p>
 */
public final class PermissionRule {

    /** 稳定的规则名，同时作为决定的 source 进审计。 */
    private final String name;

    /** 命中时给出的结论。 */
    private final PermissionBehavior behavior;

    /** 命中时的原因，会回传给模型。 */
    private final String reason;

    /** 判断本条规则是否管这次请求。 */
    private final Matcher matcher;

    /** 规则谓词。Java 8 没有现成的语义化函数接口，这里显式声明一个。 */
    public interface Matcher {
        boolean matches(PermissionRequest request);
    }

    public PermissionRule(String name, PermissionBehavior behavior, String reason, Matcher matcher) {
        if (name == null || name.trim().isEmpty()) {
            throw new PermissionContractException("规则名不能为空，它要作为 source 进审计");
        }
        if (behavior == null) {
            throw new PermissionContractException("behavior 不能为空");
        }
        if (reason == null || reason.trim().isEmpty()) {
            throw new PermissionContractException("reason 不能为空");
        }
        if (matcher == null) {
            throw new PermissionContractException("matcher 不能为空");
        }
        this.name = name;
        this.behavior = behavior;
        this.reason = reason;
        this.matcher = matcher;
    }

    public String getName() {
        return name;
    }

    public PermissionBehavior getBehavior() {
        return behavior;
    }

    /**
     * 不命中返回 null，命中返回一条带本规则名的决定。
     *
     * <p>谓词抛异常的处理放在 {@link PermissionPolicy}：那里会转成本规则名下的
     * <b>deny</b>，而不是忽略这条规则。理由是规则写错时应该收紧而不是放宽 ——
     * 一条本该拦住删除的规则因为 NPE 被跳过，是最坏的失败方式。</p>
     */
    public PermissionDecision evaluate(PermissionRequest request) {
        if (!matcher.matches(request)) {
            return null;
        }
        return new PermissionDecision(behavior, reason, name);
    }

    @Override
    public String toString() {
        return "PermissionRule{" + name + " -> " + behavior.getWireValue() + "}";
    }
}
