package learn.agent.llm.artifact;

import learn.agent.llm.workspace.WorkspaceGuard;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 产物管理器：将大型工具结果写入文件，历史中只保留引用。
 *
 * <p>规则：</p>
 * <ul>
 *   <li>tool 消息内容超过阈值时写入 artifact 文件</li>
 *   <li>文件名：artifact-{timestamp}-{seq}.txt</li>
 *   <li>历史中替换为引用：[Artifact: path]</li>
 *   <li>所有文件操作必须经过 {@link WorkspaceGuard} 边界检查</li>
 * </ul>
 *
 * <p>为什么重要：避免单个工具结果占用过多 token。</p>
 */
public final class ArtifactManager {

    private static final DateTimeFormatter TIMESTAMP_FORMAT =
        DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss").withZone(ZoneId.systemDefault());

    private final Path workspaceRoot;
    private final String artifactDirRelative;
    private final WorkspaceGuard guard;
    private final int sizeThreshold;
    private final AtomicInteger sequenceCounter = new AtomicInteger(0);

    /**
     * @param workspaceRoot 工作区根目录（绝对路径）
     * @param artifactDirRelative 产物目录相对于工作区根的路径（如 "artifacts"）
     * @param sizeThreshold 触发落盘的字节阈值
     */
    public ArtifactManager(Path workspaceRoot, String artifactDirRelative, int sizeThreshold) {
        if (workspaceRoot == null) {
            throw new IllegalArgumentException("workspaceRoot must not be null");
        }
        if (artifactDirRelative == null || artifactDirRelative.trim().isEmpty()) {
            throw new IllegalArgumentException("artifactDirRelative must not be empty");
        }
        if (sizeThreshold <= 0) {
            throw new IllegalArgumentException("sizeThreshold must be positive");
        }

        this.workspaceRoot = workspaceRoot;
        this.artifactDirRelative = artifactDirRelative;
        this.guard = WorkspaceGuard.open(workspaceRoot.toString());
        this.sizeThreshold = sizeThreshold;
    }

    /**
     * 将大型工具结果落盘，历史中替换为引用。
     *
     * @param history 消息历史
     * @return 处理后的历史
     * @throws IOException 文件操作失败
     * @throws SecurityException 路径超出边界
     */
    public List<ChatMessage> compactToArtifacts(List<ChatMessage> history) throws IOException {
        ensureArtifactDir();

        List<ChatMessage> result = new ArrayList<>();
        for (ChatMessage message : history) {
            if (message instanceof ChatMessage.ToolMessage) {
                ChatMessage.ToolMessage toolMsg = (ChatMessage.ToolMessage) message;
                String content = toolMsg.getContent();

                if (content.getBytes().length > sizeThreshold) {
                    // 落盘并替换为引用
                    Path artifactPath = writeArtifact(content);
                    String reference = "[Artifact: " + artifactPath.getFileName() + "]";
                    result.add(ChatMessage.tool(reference, toolMsg.getToolCallId()));
                } else {
                    result.add(message);
                }
            } else {
                result.add(message);
            }
        }

        return Collections.unmodifiableList(result);
    }

    /**
     * 确保产物目录存在。
     */
    private void ensureArtifactDir() throws IOException {
        // 先通过词法关获取路径
        Path artifactDir = guard.resolveRelative(artifactDirRelative);

        if (!Files.exists(artifactDir)) {
            Files.createDirectories(artifactDir);
        }

        // 创建后通过物理关验证（防止符号链接攻击）
        WorkspaceGuard.realDirectoryInside(artifactDir, guard.getRoot());
    }

    /**
     * 将内容写入 artifact 文件。
     *
     * @return 文件路径（相对于工作区）
     */
    private Path writeArtifact(String content) throws IOException {
        String timestamp = TIMESTAMP_FORMAT.format(Instant.now());
        int seq = sequenceCounter.incrementAndGet();
        String filename = String.format("artifact-%s-%03d.txt", timestamp, seq);

        // 通过词法关构建路径
        String relativePath = artifactDirRelative + "/" + filename;
        Path filePath = guard.resolveRelative(relativePath);

        Files.write(filePath, content.getBytes(StandardCharsets.UTF_8));

        // 写入后通过物理关验证
        WorkspaceGuard.realFileInside(filePath, guard.getRoot());

        return filePath;
    }

    /**
     * 重置序列计数器（测试用）。
     */
    void resetSequence() {
        sequenceCounter.set(0);
    }
}
