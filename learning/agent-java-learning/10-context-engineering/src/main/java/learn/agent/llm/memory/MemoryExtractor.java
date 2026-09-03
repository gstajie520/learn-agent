package learn.agent.llm.memory;

import learn.agent.llm.artifact.ChatMessage;

import java.util.List;

/**
 * 记忆提取器：从会话历史中提取新记忆。
 */
public interface MemoryExtractor {
    /**
     * 从会话历史中提取新记忆。
     *
     * @param history 完整会话历史
     * @param catalog 当前记忆目录
     * @return JSON 数组，包含新的记忆记录
     */
    String extract(List<ChatMessage> history, String catalog) throws Exception;
}
