package learn.agent.llm.memory;

/**
 * 记忆选择器：从目录中选择与查询相关的记忆。
 */
public interface MemorySelector {
    /**
     * 选择相关记忆。
     *
     * @param query   用户查询
     * @param catalog 记忆目录（name + description 列表）
     * @return JSON 字符串数组，包含选中的记忆名称
     */
    String select(String query, String catalog) throws Exception;
}
