package learn.agent.llm.lesson05;

/**
 * 一轮循环的结构化记录：这一轮模型说了什么、程序做了什么、花了多少。
 *
 * <p>路线要求从本阶段起就打 trace id、轮次、工具名、耗时、token。这个类是
 * 「一行日志」的对象形态：字段固定、可断言、可聚合。等到接入真正的日志框架时，
 * 只需要把它序列化输出，埋点位置不用重新找。</p>
 *
 * <p>为什么做成对象而不是直接 {@code System.out.println}：字符串一旦拼出来就
 * 只能靠人读，测试没法断言「这一轮确实调了 create_device」。对象可以。</p>
 */
public class RoundTrace {

    /** 第几轮，从 1 开始，和人读日志的习惯一致。 */
    private final int round;

    /** 这一轮模型的 finish_reason 协议值，例如 {@code tool_calls}、{@code stop}。 */
    private final String finishReason;

    /** 这一轮请求的工具名；没有工具调用时为 null。 */
    private final String toolName;

    /** 工具调用 id；没有工具调用时为 null。 */
    private final String toolCallId;

    /** 工具执行结果的处置方式，例如 executed、blocked_destructive、deduplicated。 */
    private final String toolOutcome;

    /** 工具失败时的错误码；成功或未调工具时为 null。 */
    private final String errorCode;

    /** 这一轮模型调用的耗时毫秒数。 */
    private final long modelLatencyMillis;

    /** 这一轮工具执行的耗时毫秒数；未调工具时为 0。 */
    private final long toolLatencyMillis;

    /** 这一轮的输入 token。 */
    private final int promptTokens;

    /** 这一轮的输出 token。 */
    private final int completionTokens;

    public RoundTrace(int round,
                      String finishReason,
                      String toolName,
                      String toolCallId,
                      String toolOutcome,
                      String errorCode,
                      long modelLatencyMillis,
                      long toolLatencyMillis,
                      int promptTokens,
                      int completionTokens) {
        this.round = round;
        this.finishReason = finishReason;
        this.toolName = toolName;
        this.toolCallId = toolCallId;
        this.toolOutcome = toolOutcome;
        this.errorCode = errorCode;
        this.modelLatencyMillis = modelLatencyMillis;
        this.toolLatencyMillis = toolLatencyMillis;
        this.promptTokens = promptTokens;
        this.completionTokens = completionTokens;
    }

    public int getRound() {
        return round;
    }

    public String getFinishReason() {
        return finishReason;
    }

    public String getToolName() {
        return toolName;
    }

    public String getToolCallId() {
        return toolCallId;
    }

    public String getToolOutcome() {
        return toolOutcome;
    }

    public String getErrorCode() {
        return errorCode;
    }

    public long getModelLatencyMillis() {
        return modelLatencyMillis;
    }

    public long getToolLatencyMillis() {
        return toolLatencyMillis;
    }

    public int getPromptTokens() {
        return promptTokens;
    }

    public int getCompletionTokens() {
        return completionTokens;
    }

    /** @return 这一轮是否调用了工具 */
    public boolean hasToolCall() {
        return toolName != null;
    }

    /** @return 这一轮的 token 合计 */
    public int getTotalTokens() {
        return promptTokens + completionTokens;
    }

    /**
     * 渲染成一行日志。
     *
     * <p>用 {@code key=value} 而不是自然语言：这种格式能被日志系统直接切成字段，
     * 也方便 grep 出「所有调了 delete_device 的轮次」。</p>
     */
    public String toLogLine() {
        StringBuilder sb = new StringBuilder();
        sb.append("round=").append(round);
        sb.append(" finish=").append(finishReason);
        if (toolName != null) {
            sb.append(" tool=").append(toolName);
            sb.append(" tool_call_id=").append(toolCallId);
            sb.append(" outcome=").append(toolOutcome);
            if (errorCode != null) {
                sb.append(" error=").append(errorCode);
            }
            sb.append(" tool_ms=").append(toolLatencyMillis);
        }
        sb.append(" model_ms=").append(modelLatencyMillis);
        sb.append(" prompt_tokens=").append(promptTokens);
        sb.append(" completion_tokens=").append(completionTokens);
        return sb.toString();
    }

    @Override
    public String toString() {
        return toLogLine();
    }
}
