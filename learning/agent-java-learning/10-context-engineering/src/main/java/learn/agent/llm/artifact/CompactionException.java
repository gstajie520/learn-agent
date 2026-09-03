package learn.agent.llm.artifact;

/**
 * 压缩领域错误的公共基类。
 * 调用方按子类决定是拒绝、清理还是重试。
 */
public class CompactionException extends RuntimeException {
    public CompactionException(String message) {
        super(message);
    }

    public CompactionException(String message, Throwable cause) {
        super(message, cause);
    }
}
