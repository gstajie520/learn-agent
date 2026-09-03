package learn.agent.llm.artifact;

/**
 * 目标 artifact 已存在。
 * 独占发布失败时不覆盖旧文件。
 */
public class ArtifactConflictException extends CompactionException {
    public ArtifactConflictException(String message) {
        super(message);
    }

    public ArtifactConflictException(String message, Throwable cause) {
        super(message, cause);
    }
}
