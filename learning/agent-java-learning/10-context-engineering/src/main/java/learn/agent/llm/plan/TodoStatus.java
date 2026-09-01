package learn.agent.llm.plan;

/**
 * 会话计划里一个任务项的状态。
 *
 * <p>只有三个状态，<b>刻意不给第四个</b>。见过的失败设计是加上 {@code blocked}、
 * {@code cancelled}、{@code deferred}：状态一多，模型就开始把「我不想做」写成
 * {@code deferred}，把「我做不动了」写成 {@code blocked}，计划从进度记录退化成
 * 借口清单。三态的好处是每一项只能回答一个问题 —— <b>做完了没有</b>。</p>
 *
 * <p>和 {@link learn.agent.llm.loop.StopReason} 一样带显式 {@code wireValue}：
 * 枚举名以后改了，落到日志和工具结果里的字符串不能跟着变，否则历史记录对不上。
 * 第 5 课 {@code AgentLoop.wireOf} 那处 {@code name().toLowerCase()} 就是反例。</p>
 */
public enum TodoStatus {

    /** 还没开始。新写入的项默认都是这个。 */
    PENDING("pending"),

    /** 正在做。同一时刻通常只该有一项，见 {@link TodoTracker} 的说明。 */
    IN_PROGRESS("in_progress"),

    /** 已完成。终态，但下一次完整快照仍然要带上它，否则模型会以为自己没做过。 */
    COMPLETED("completed");

    /** 出现在工具参数、工具结果和日志里的字面值。 */
    private final String wireValue;

    TodoStatus(String wireValue) {
        this.wireValue = wireValue;
    }

    public String getWireValue() {
        return wireValue;
    }

    /**
     * 从模型给的字符串解析状态。
     *
     * <p>返回 null 而不是抛异常：这里的输入来自模型，写错是<b>预期内</b>的事件。
     * 调用方（{@link TodoWriteValidator}）要把它变成一条能回传给模型的错误，
     * 而不是让整个请求崩掉 —— 这条规则从第 4 课的 {@code prepare} 一直沿用到现在。</p>
     *
     * @param wireValue 模型给的状态字符串
     * @return 匹配的状态；无法匹配时返回 null
     */
    public static TodoStatus fromWireValue(String wireValue) {
        if (wireValue == null) {
            return null;
        }
        String trimmed = wireValue.trim();
        for (TodoStatus status : values()) {
            if (status.wireValue.equals(trimmed)) {
                return status;
            }
        }
        return null;
    }

    /** @return 全部合法字面值，用于给模型的错误提示 */
    public static String describeAll() {
        StringBuilder builder = new StringBuilder();
        for (TodoStatus status : values()) {
            if (builder.length() > 0) {
                builder.append(", ");
            }
            builder.append(status.wireValue);
        }
        return builder.toString();
    }
}
