package learn.agent.llm.lesson05;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 一次 Agent 运行的完整轨迹：trace id + 每轮记录 + 结束原因。
 *
 * <p>这是贯穿项「Trace 与结构化日志」的载体。仓库里没有引入 slf4j，
 * 而且构建是离线的（{@code mvn -o}），所以本课不打日志行，而是把每轮
 * 发生的事记成内存里的结构。两个好处：</p>
 * <ul>
 *   <li>测试可以直接断言「第 2 轮调了哪个工具、为什么结束」，
 *       而不是去 grep 控制台输出；</li>
 *   <li>要落盘时，把这个对象序列化成 JSON 就是一行结构化日志，
 *       埋点位置不用再动。</li>
 * </ul>
 *
 * <p>trace id 的作用是把「同一次运行的多轮模型调用」串起来。生产里一次
 * 用户请求会产生多轮调用、多次工具执行，日志混在一起没有 id 就无法归因。</p>
 */
public class AgentTrace {

    /** 本次运行的唯一标识，用来把多轮记录归到一起。 */
    private final String traceId;

    /** 每轮一条记录，按发生顺序追加。 */
    private final List<RoundTrace> rounds = new ArrayList<RoundTrace>();

    /** 结束原因；运行结束时才确定。 */
    private StopReason stopReason;

    /** 最终返回给调用方的文本。 */
    private String finalAnswer;

    public AgentTrace(String traceId) {
        if (traceId == null || traceId.trim().isEmpty()) {
            throw new IllegalArgumentException("traceId 不能为空，否则多轮记录无法归因");
        }
        this.traceId = traceId.trim();
    }

    void addRound(RoundTrace round) {
        rounds.add(round);
    }

    void finish(StopReason reason, String answer) {
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

    /** @return 本次运行在模型调用上花的总毫秒数 */
    public long getTotalModelMillis() {
        long total = 0L;
        for (RoundTrace round : rounds) {
            total += round.getModelLatencyMillis();
        }
        return total;
    }

    /**
     * 渲染成多行文本，每轮一行。
     *
     * <p>这就是「结构化日志」的人类可读版本：真正落盘时换成 JSON，
     * 字段完全一样。</p>
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
        return sb.toString();
    }

    @Override
    public String toString() {
        return render();
    }
}
