package learn.agent.llm.tool;

/**
 * 一次工具执行的结果。
 *
 * <h2>本课最重要的一条设计：工具失败也返回结果，不抛异常</h2>
 *
 * <p>直觉上，工具执行失败应该抛异常让调用方处理。但在 Agent 里这样做是错的，
 * 原因是<b>模型是这个结果的消费者</b>。</p>
 *
 * <p>如果抛异常，整条链路会中断，用户看到的是一个 500。而模型其实完全有能力
 * 自己纠正：它调 {@code delete_device} 时传了不存在的 id，只要把
 * 「设备 device-99 不存在，当前设备是 [device-1, device-2]」回传给它，
 * 它下一轮就会改对。抛异常等于剥夺了模型自我纠正的机会。</p>
 *
 * <p>所以规则是：<b>工具的失败是一种正常的返回值，不是意外</b>。
 * 这和第 3 课 {@code ValidationResult} 不用异常表达校验失败是同一个道理 ——
 * 预期内的失败用返回值，编程错误才用异常。</p>
 *
 * <h2>但也不能把什么都回传给模型</h2>
 *
 * <p>{@code content} 是要发给模型、进而可能被用户看到的文本，所以它绝不能包含
 * Java 堆栈、SQL 语句、文件绝对路径或内部主机名。这些既帮不了模型（它看不懂
 * 你的堆栈），又是实打实的信息泄露。{@link ToolRegistry#invoke} 里统一做了这层转换。</p>
 */
public class ToolExecutionResult {

    /** 给模型看的结果文本。 */
    private final String content;

    /** 是否失败。注意：失败仍然是一个合法结果，会正常回传给模型。 */
    private final boolean error;

    /**
     * 机器可读的错误码，例如 {@code unknown_tool}、{@code invalid_json}。
     *
     * <p>它不是给模型看的，而是给<b>我们</b>看的：告警和统计要按错误码聚合。
     * 「本周 invalid_json 占工具调用的 12%」说明工具的参数 schema 描述得不清楚，
     * 是可以优化的产品问题；只有一段自然语言错误文本就统计不出这个。</p>
     */
    private final String errorCode;

    private ToolExecutionResult(String content, boolean error, String errorCode) {
        this.content = (content == null) ? "" : content;
        this.error = error;
        this.errorCode = errorCode;
    }

    /** 创建成功结果。 */
    public static ToolExecutionResult success(String content) {
        if (content == null || content.trim().isEmpty()) {
            // 空结果会让模型以为工具没执行。宁可显式说「没有数据」也不要返回空串。
            throw new IllegalArgumentException("成功结果必须有内容，没有数据时也要显式说明");
        }
        return new ToolExecutionResult(content, false, null);
    }

    /**
     * 创建失败结果。
     *
     * @param errorCode 机器可读错误码，用于统计和告警
     * @param message   给模型看的原因说明，应当包含「怎么改」的线索
     */
    public static ToolExecutionResult error(String errorCode, String message) {
        if (errorCode == null || errorCode.trim().isEmpty()) {
            throw new IllegalArgumentException("错误结果必须带错误码，否则无法聚合统计");
        }
        // 加上前缀，让模型在一堆工具结果里能立刻识别出这次失败了。
        return new ToolExecutionResult(
                "工具执行失败 [" + errorCode.trim() + "]：" + message,
                true,
                errorCode.trim());
    }

    public String getContent() {
        return content;
    }

    public boolean isError() {
        return error;
    }

    public String getErrorCode() {
        return errorCode;
    }

    @Override
    public String toString() {
        return error
                ? "ToolExecutionResult{error=" + errorCode + "}"
                : "ToolExecutionResult{ok, length=" + content.length() + "}";
    }
}
