package learn.agent.llm.lesson04;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * 一次「已经准备好、但还没有执行」的工具调用。
 *
 * <p>这是本课最重要的一个类型，因为它把「检查」和「执行」在<b>类型层面</b>切开了。
 * 模型返回的 {@link ToolCall} 是一段不可信的文本；把它变成能真正跑的东西，
 * 中间要过工具查找、JSON 解析、参数校验三道关。
 * {@code PreparedToolCall} 就是这三道关的<b>结论</b>。
 *
 * <p>它只有两种状态，二者必有其一：
 * <ul>
 *   <li>{@link #isFailed()} 为 {@code false}：{@link #getDefinition()} 和
 *       {@link #getArguments()} 都可用，参数已经是解析好、校验过的 {@link JsonNode}，
 *       执行阶段可以直接用，不需要再检查一遍。</li>
 *   <li>{@link #isFailed()} 为 {@code true}：{@link #getError()} 里已经装好了
 *       要回传给模型的失败结果，{@link #getDefinition()} 可能为 {@code null}
 *       （工具根本不存在时就是这样）。</li>
 * </ul>
 *
 * <p><b>为什么失败要提前装成 {@link ToolExecutionResult} 而不是抛异常？</b>
 * 因为工具调用失败是<b>对话的一部分</b>，不是程序的故障。
 * 模型把参数写错了，正确的做法是把「你写错了，错在哪」告诉它，让它下一轮改，
 * 而不是让整个请求崩掉。失败结果预先装好之后，执行阶段的代码就不需要
 * try/catch 或者 if-else 分支去区分「这次能不能跑」——
 * 它只要看一眼 {@code isFailed()}，就知道该跑还是该直接回传。
 *
 * @see ToolRegistry#prepare(ToolCall)
 * @see ToolRegistry#invoke(PreparedToolCall, ToolContext)
 */
public class PreparedToolCall {

    /** 模型原始的调用请求，无论成败都保留，回传结果时要用它的 id 配对。 */
    private final ToolCall call;

    /** 命中的工具定义；工具不存在时为 null。 */
    private final ToolDefinition definition;

    /** 解析并校验通过的参数；失败时为 null。 */
    private final JsonNode arguments;

    /** 预先装好的失败结果；成功时为 null。 */
    private final ToolExecutionResult error;

    private PreparedToolCall(ToolCall call,
                             ToolDefinition definition,
                             JsonNode arguments,
                             ToolExecutionResult error) {
        this.call = call;
        this.definition = definition;
        this.arguments = arguments;
        this.error = error;
    }

    /**
     * 三道关全过，可以执行。
     *
     * @param call       模型的原始请求
     * @param definition 命中的工具
     * @param arguments  已解析、已校验的参数
     */
    public static PreparedToolCall ready(ToolCall call, ToolDefinition definition, JsonNode arguments) {
        if (call == null) {
            throw new IllegalArgumentException("call 不能为 null");
        }
        if (definition == null) {
            throw new IllegalArgumentException("definition 不能为 null");
        }
        if (arguments == null) {
            throw new IllegalArgumentException("arguments 不能为 null");
        }
        return new PreparedToolCall(call, definition, arguments, null);
    }

    /**
     * 某道关没过。失败结果此时就已经确定，执行阶段不需要再判断。
     *
     * <p>{@code definition} 允许为 {@code null}：工具名根本不存在时，
     * 我们没有定义可以填，但依然要能构造出一个失败的 {@code PreparedToolCall}。
     *
     * @param call       模型的原始请求
     * @param definition 命中的工具，可能为 null
     * @param error      要回传给模型的失败结果，必须是 error 态
     */
    public static PreparedToolCall failed(ToolCall call, ToolDefinition definition, ToolExecutionResult error) {
        if (call == null) {
            throw new IllegalArgumentException("call 不能为 null");
        }
        if (error == null) {
            throw new IllegalArgumentException("error 不能为 null");
        }
        if (!error.isError()) {
            // 防止把成功结果塞进失败通道，那会让 isFailed() 说谎。
            throw new IllegalArgumentException("failed() 只接受 error 态的结果");
        }
        // arguments 必须为 null：失败的调用没有「可用的参数」这个概念。
        return new PreparedToolCall(call, definition, null, error);
    }

    public ToolCall getCall() {
        return call;
    }

    /** @return 命中的工具定义；工具不存在时为 null */
    public ToolDefinition getDefinition() {
        return definition;
    }

    /** @return 已校验的参数；{@link #isFailed()} 为 true 时为 null */
    public JsonNode getArguments() {
        return arguments;
    }

    /** @return 预置的失败结果；{@link #isFailed()} 为 false 时为 null */
    public ToolExecutionResult getError() {
        return error;
    }

    /** @return true 表示这次调用在准备阶段就已经失败，不该执行 */
    public boolean isFailed() {
        return error != null;
    }

    @Override
    public String toString() {
        if (isFailed()) {
            return "PreparedToolCall{failed, call=" + call + ", errorCode=" + error.getErrorCode() + "}";
        }
        return "PreparedToolCall{ready, call=" + call + ", effect=" + definition.getEffect().getWireValue() + "}";
    }
}
