package learn.agent.llm.memory;

/**
 * 记忆存储异常。
 */
public class MemoryStoreException extends RuntimeException {
    public MemoryStoreException(String message) {
        super(message);
    }

    public MemoryStoreException(String message, Throwable cause) {
        super(message, cause);
    }
}
