package learn.agent.llm.artifact;

/**
 * artifact 路径或目录不满足安全边界。
 * 例如 ID 非法、符号链接逃逸。
 */
public class ArtifactPathException extends CompactionException {
    public ArtifactPathException(String message) {
        super(message);
    }

    public ArtifactPathException(String message, Throwable cause) {
        super(message, cause);
    }
}
