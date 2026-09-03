package learn.agent.llm.prompting;

/**
 * 动态 Prompt 上下文异常。
 * 当 context 包含不可序列化的值时抛出：函数、Date、NaN、Infinity、循环引用等。
 */
public class PromptContextException extends RuntimeException {

    public PromptContextException(String message) {
        super(message);
    }

    public PromptContextException(String message, Throwable cause) {
        super(message, cause);
    }
}
