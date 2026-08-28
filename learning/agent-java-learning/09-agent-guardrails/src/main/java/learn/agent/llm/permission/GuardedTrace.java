package learn.agent.llm.permission;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import learn.agent.llm.loop.RoundTrace;
import learn.agent.llm.loop.StopReason;

/**
 * 本课的运行轨迹：和第 5 课的 {@code AgentTrace} 字段一致，多了「权限裁决」这一维。
 *
 * <p><b>为什么不直接用 {@code lesson05.AgentTrace}</b>：它的 {@code addRound}
 * 和 {@code finish} 是包私有的，只有 {@code lesson05} 包里的类能调。包私有是
 * <em>包</em>边界，不是类边界——第 5 课把写入方（{@code AgentLoop}）和轨迹放在
 * 同一个包里，所以它自己用得很顺；换个包就够不着了。</p>
 *
 * <p>两条出路：把那两个方法改成 public，或者在本包重写一个。本课选后者，因为
 * 改第 5 课就违背了阶段 8 的完成标准（不修改 Loop 主体）。值类型
 * （{@link RoundTrace}、{@link StopReason}）本来就是 public 的，照原样复用，
 * 没有复制粘贴。</p>
 *
 * <p>这是第 5 课留下的一处设计债，如实记在这里：<b>一个类如果希望被下游扩展，
 * 它的写入口就不能停在包私有</b>。第 5 课当时没有下游，看不出问题。</p>
 *
 * <p><b>后续（第 7 课）：这条结论当场应验了。</b>第 7 课要在 {@code lesson07} 包里
 * 组装带 Hook 的循环，复用本类时撞上了一模一样的编译错误 ——「{@code addRound}
 * 在 {@code GuardedTrace} 中不是公共的」。当时的选择有两个：让第 7 课再抄一份轨迹类
 * （同一个错误连犯两次），或者把本类的三个写入口改成 public。改了后者，理由就是
 * 上面那句自己写下的话。所以 {@link #addRound}、{@link #addDecision}、
 * {@link #finish} 现在是 public，代价写在各自的注释里。</p>
 */
public class GuardedTrace {

    /** 本次运行的唯一标识，用来把多轮记录归到一起。 */
    private final String traceId;

    /** 每轮一条记录，按发生顺序追加。 */
    private final List<RoundTrace> rounds = new ArrayList<RoundTrace>();

    /**
     * 每次权限裁决一条，按发生顺序追加。
     *
     * <p>和 {@code rounds} 分开存：一轮里可能压根没走到权限（参数校验就失败了），
     * 也可能只裁决一次。硬塞进 {@link RoundTrace} 会让「没有裁决」和
     * 「裁决为放行」两种情况长得一样。</p>
     */
    private final List<PermissionDecision> decisions = new ArrayList<PermissionDecision>();

    /** 结束原因；运行结束时才确定。 */
    private StopReason stopReason;

    /** 最终返回给调用方的文本。 */
    private String finalAnswer;

    public GuardedTrace(String traceId) {
        if (traceId == null || traceId.trim().isEmpty()) {
            throw new IllegalArgumentException("traceId 不能为空，否则多轮记录无法归因");
        }
        this.traceId = traceId.trim();
    }

    /**
     * 追加一轮记录。
     *
     * <p><b>这三个写入口是 public，而不是像第 5 课那样停在包私有</b>，而且这不是
     * 一开始就想清楚的 —— 本类的类注释里写下的教训是「一个类如果希望被下游扩展，
     * 它的写入口就不能停在包私有」。第 7 课就是那个下游：它在 {@code lesson07} 包里
     * 组装自己的循环，如果这三个方法还是包私有，第 7 课就得再抄一份轨迹类，
     * 一模一样的错误连犯两次。</p>
     *
     * <p>所以这里是<b>照着上一课自己写下的结论改的</b>。代价要如实说清楚：写入口
     * 公开之后，任何拿到 trace 的人都能往里塞记录，轨迹不再只由循环写。审计要防
     * 篡改的话，这三个方法就得收回去、改由构造器一次性接收全部记录 —— 那是生产
     * 代码的做法，但教学代码里循环需要边跑边追加，所以选了公开加约定。</p>
     */
    public void addRound(RoundTrace round) {
        rounds.add(round);
    }

    /** 追加一条权限裁决记录。公开理由同 {@link #addRound}。 */
    public void addDecision(PermissionDecision decision) {
        decisions.add(decision);
    }

    /** 记下结束原因和最终答复。公开理由同 {@link #addRound}。 */
    public void finish(StopReason reason, String answer) {
        this.stopReason = reason;
        this.finalAnswer = answer;
    }

    public String getTraceId() {
        return traceId;
    }

    /** @return 每轮记录的不可修改视图 */
    public List<RoundTrace> getRounds() {
        return Collections.unmodifiableList(rounds);
    }

    /** @return 本次运行的全部权限裁决，按发生顺序 */
    public List<PermissionDecision> getDecisions() {
        return Collections.unmodifiableList(decisions);
    }

    /** @return 实际发生的轮数 */
    public int getRoundCount() {
        return rounds.size();
    }

    /** @return 结束原因；运行未结束时为 null */
    public StopReason getStopReason() {
        return stopReason;
    }

    public String getFinalAnswer() {
        return finalAnswer;
    }

    /** @return 本次运行累计消耗的 token（各轮相加） */
    public int getTotalTokens() {
        int total = 0;
        for (RoundTrace round : rounds) {
            total += round.getTotalTokens();
        }
        return total;
    }

    /**
     * 渲染成多行文本：一行汇总 + 每轮一行 + 每条裁决一行。
     *
     * <p>裁决单独打出来，是因为审计要回答的问题是「谁批的、依据哪条规则」，
     * 而不是「这一轮花了多少 token」。</p>
     */
    public String render() {
        StringBuilder sb = new StringBuilder();
        sb.append("trace=").append(traceId)
                .append(" rounds=").append(rounds.size())
                .append(" stop=").append(stopReason == null ? "running" : stopReason.getWireValue())
                .append(" tokens=").append(getTotalTokens())
                .append('\n');
        for (RoundTrace round : rounds) {
            sb.append("  ").append(round.toLogLine()).append('\n');
        }
        for (PermissionDecision decision : decisions) {
            sb.append("  permission=").append(decision.getBehavior().getWireValue())
                    .append(" source=").append(decision.getSource())
                    .append(" reason=").append(decision.getReason())
                    .append('\n');
        }
        return sb.toString();
    }

    @Override
    public String toString() {
        return render();
    }
}
