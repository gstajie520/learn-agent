package learn.agent.llm.compaction;

import learn.agent.llm.artifact.ArtifactManager;
import learn.agent.llm.artifact.ChatMessage;
import learn.agent.llm.artifact.MessageGroup;
import learn.agent.llm.artifact.CompactionUtils;

import java.io.IOException;
import java.util.List;

/**
 * 上下文压缩器：三层压缩的统一入口。
 * <p>三层策略（教材 ch08）：</p>
 * <ul>
 *   <li>artifact：大工具结果落盘，历史中只留引用（永远先执行）</li>
 *   <li>snip：删除中间消息组，保留头尾（超过 maxGroups 时触发）</li>
 *   <li>micro：替换旧工具结果为占位符（不超过 maxGroups 但需要压缩时）</li>
 * </ul>
 * <p>为什么重要：预算不足时自动压缩，而不是拒绝请求。</p>
 *
 * @author cj
 * @since 2026-09-03
 */
public class ContextCompactor {
    private final ArtifactManager artifactManager;
    private final int maxGroups;
    private final int keepHeadGroups;
    private final int keepRecentToolGroups;

    /**
     * @param artifactManager artifact 管理器（已配置阈值）
     * @param maxGroups 允许的最大消息组数（超过则触发 snip 压缩）
     * @param keepHeadGroups snip 压缩保留的头部组数
     * @param keepRecentToolGroups micro 压缩保留的最近工具组数
     */
    public ContextCompactor(ArtifactManager artifactManager,
                            int maxGroups,
                            int keepHeadGroups,
                            int keepRecentToolGroups) {
        this.artifactManager = artifactManager;
        this.maxGroups = maxGroups;
        this.keepHeadGroups = keepHeadGroups;
        this.keepRecentToolGroups = keepRecentToolGroups;
    }

    /**
     * 执行压缩：artifact 永远先执行，然后根据消息组数选择 snip 或 micro。
     *
     * @param history 原始消息历史
     * @return 压缩后的历史
     */
    public List<ChatMessage> compact(List<ChatMessage> history) {
        // 第一层：artifact 落盘（永远先执行）
        List<ChatMessage> afterArtifact;
        try {
            afterArtifact = artifactManager.compactToArtifacts(history);
        } catch (IOException e) {
            // 落盘失败时继续使用原始历史
            afterArtifact = history;
        }

        // 计算消息组数
        List<MessageGroup> groups = MessageGroup.fromHistory(afterArtifact);

        // 超过 maxGroups：使用 snip 压缩
        if (groups.size() > maxGroups) {
            return CompactionUtils.snipCompact(afterArtifact, maxGroups, keepHeadGroups);
        }

        // 否则：使用 micro 压缩（如果有工具交换的话）
        return CompactionUtils.microCompact(afterArtifact, keepRecentToolGroups);
    }
}
