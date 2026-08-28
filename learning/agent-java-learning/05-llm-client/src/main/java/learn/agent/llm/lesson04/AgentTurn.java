package learn.agent.llm.lesson04;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 工具调用循环里的一轮「模型回合」。
 *
 * <p>第 1 课的 {@link learn.agent.llm.lesson01.ChatResponse} 只有 content 和
 * finishReason，装不下「模型决定调工具」这个结果。本课定义自己的回合结果，
 * 把三种可能的结局显式区分开：</p>
 * <ul>
 *   <li>{@link #isToolCall()} —— 模型要调工具，{@link #getToolCall()} 可用；</li>
 *   <li>{@link #isFinalAnswer()} —— 模型给出了最终答复，{@link #getContent()} 可用；</li>
 *   <li>{@link #isTruncated()} —— 输出被截断，两者都不可用，需要处理。</li>
 * </ul>
 *
 * <p>为什么不用一个 {@code content} 加一堆可空字段：因为「模型要调工具」和
 * 「模型答完了」是<b>互斥</b>的两种状态，用可空字段表达，调用方就得自己记住
 * 「什么时候该读哪个字段」。用三个布尔判断，读错字段的代价从「静默拿到 null」
 * 变成「一眼就能看出的语义错误」。</p>
 */
public class AgentTurn {

    /** 模型最终答复；工具调用或截断时为 null。 */
    private final String content;

    /** 模型发起的工具调用；最终答复或截断时为 null。 */
    private final ToolCall toolCall;

    /** 是否被 maxOutputTokens 截断。 */
    private final boolean truncated;

    private AgentTurn(String content, ToolCall toolCall, boolean truncated) {
        this.content = content;
        this.toolCall = toolCall;
        this.truncated = truncated;
    }

    /** 模型给出了最终答复。 */
    public static AgentTurn finalAnswer(String content) {
        if (content == null) {
            throw new IllegalArgumentException("最终答复的 content 不能为 null");
        }
        return new AgentTurn(content, null, false);
    }

    /** 模型决定调用工具。 */
    public static AgentTurn toolCall(ToolCall call) {
        if (call == null) {
            throw new IllegalArgumentException("toolCall 不能为 null");
        }
        return new AgentTurn(null, call, false);
    }

    /** 输出被截断，既没有完整答复也没有工具调用。 */
    public static AgentTurn truncated() {
        return new AgentTurn(null, null, true);
    }

    public boolean isToolCall() {
        return toolCall != null;
    }

    public boolean isFinalAnswer() {
        return content != null;
    }

    public boolean isTruncated() {
        return truncated;
    }

    /** @return 最终答复；非最终答复时为 null */
    public String getContent() {
        return content;
    }

    /** @return 工具调用；非工具调用时为 null */
    public ToolCall getToolCall() {
        return toolCall;
    }

    @Override
    public String toString() {
        if (isToolCall()) {
            return "AgentTurn{toolCall=" + toolCall + "}";
        }
        if (isTruncated()) {
            return "AgentTurn{truncated}";
        }
        return "AgentTurn{finalAnswer, length=" + content.length() + "}";
    }
}