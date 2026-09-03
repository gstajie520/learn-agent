package learn.agent.llm.artifact;

/**
 * 工件引用：落盘后的文件位置和元信息。
 * 模型使用 relativePath 重新读取，本地清理用 path。
 */
public final class ArtifactReference {
    private final String path;
    private final String relativePath;
    private final int originalBytes;

    public ArtifactReference(String path, String relativePath, int originalBytes) {
        if (path == null || path.isEmpty()) {
            throw new IllegalArgumentException("path must not be empty");
        }
        if (relativePath == null || relativePath.isEmpty()) {
            throw new IllegalArgumentException("relativePath must not be empty");
        }
        if (originalBytes < 0) {
            throw new IllegalArgumentException("originalBytes must not be negative");
        }
        this.path = path;
        this.relativePath = relativePath;
        this.originalBytes = originalBytes;
    }

    /**
     * 工件的绝对路径，仅供本地清理。
     */
    public String getPath() {
        return path;
    }

    /**
     * 相对工作区路径，可安全写入工具结果和摘要。
     */
    public String getRelativePath() {
        return relativePath;
    }

    /**
     * 落盘前正文的 UTF-8 字节数。
     * 帮助模型判断是否需要重新读取。
     */
    public int getOriginalBytes() {
        return originalBytes;
    }
}
