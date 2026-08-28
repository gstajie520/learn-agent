package learn.agent.llm.loop;

/**
 * 循环为什么停下来。
 *
 * <p>第 4 课的 {@code run} 只返回一个字符串，「正常答完」和「轮数耗尽」都混在
 * 文本里，调用方只能靠字符串匹配去猜。把停止原因提成枚举，上层才能对
 * 「异常停止」做监控和告警。</p>
 */
public enum StopReason {

    /** 模型给出了最终答复，正常结束。 */
    FINAL_ANSWER("final_answer"),

    /** 达到最大轮数仍未拿到最终答复。是保险丝熔断，不是正常结束。 */
    MAX_ROUNDS("max_rounds"),

    /** 模型输出被截断，既没有完整答复也没有工具调用。 */
    TRUNCATED("truncated"),

    /** 模型声明要调工具却没给出调用内容，属于协议违约。 */
    PROTOCOL_VIOLATION("protocol_violation"),

    /** 模型调用本身失败：重试耗尽、密钥错误、网络不通。 */
    MODEL_ERROR("model_error");

    private final String wireValue;

    StopReason(String wireValue) {
        this.wireValue = wireValue;
    }

    /** @return 写进日志和 trace 的稳定字符串，不受 Java 枚举改名影响 */
    public String getWireValue() {
        return wireValue;
    }

    /** @return 是否属于非正常结束，上层可以据此决定要不要告警 */
    public boolean isAbnormal() {
        return this != FINAL_ANSWER;
    }
}
