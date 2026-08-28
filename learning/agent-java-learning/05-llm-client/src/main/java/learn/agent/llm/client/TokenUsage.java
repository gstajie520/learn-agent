package learn.agent.llm.client;

/**
 * 一次模型请求消耗的 Token。
 *
 * <p>为什么后端一定要记它：Token 同时决定三件事 —— 费用、延迟和上下文是否溢出。
 * 输入 Token 随对话历史线性增长，所以长会话的成本不是恒定的。</p>
 *
 * <p>输入和输出通常单价不同，输出一般更贵，因此必须分开统计而不是只记总数。</p>
 */
public class TokenUsage {

    /** 输入 Token：本次发送的全部消息。 */
    private final int promptTokens;

    /** 输出 Token：模型本次生成的内容。 */
    private final int completionTokens;

    public TokenUsage(int promptTokens, int completionTokens) {
        if (promptTokens < 0 || completionTokens < 0) {
            throw new IllegalArgumentException("Token 数量不能为负");
        }
        this.promptTokens = promptTokens;
        this.completionTokens = completionTokens;
    }

    public int getPromptTokens() {
        return promptTokens;
    }

    public int getCompletionTokens() {
        return completionTokens;
    }

    /** 总 Token，用于粗略判断是否接近上下文窗口上限。 */
    public int getTotalTokens() {
        return promptTokens + completionTokens;
    }

    @Override
    public String toString() {
        return "prompt=" + promptTokens
                + ", completion=" + completionTokens
                + ", total=" + getTotalTokens();
    }
}
