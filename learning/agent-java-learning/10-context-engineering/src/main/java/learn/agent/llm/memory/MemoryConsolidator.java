package learn.agent.llm.memory;

import java.util.List;

/**
 * 记忆整理器：整理给定记忆，合并重复或冲突内容。
 */
public interface MemoryConsolidator {
    /**
     * 整理记忆集合。
     *
     * @param records 待整理的记忆记录
     * @return JSON 对象，包含 source_names 和 records
     */
    String consolidate(List<MemoryRecord> records) throws Exception;
}
