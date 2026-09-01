package learn.agent.llm.plan;

import learn.agent.llm.tool.ToolRegistry;

/**
 * 子 Agent 的工具注册表工厂。
 *
 * <p>和 {@link ModelClientFactory} 同一个理由：每次委派要一份自己的注册表。
 * 共享一份的话，一个子任务往里注册的临时工具会出现在下一个子任务的白名单里，
 * 而后者的提示词里压根没提过这个工具 —— 模型会看到一个它不该知道的能力。</p>
 *
 * <p><b>工厂返回的注册表里绝不能有 {@code task}。</b>这条由
 * {@link SubagentTool} 在每次委派时检查，不靠工厂的实现者自觉。理由见
 * {@code SubagentTool} 关于递归委派的说明。</p>
 */
public interface ToolRegistryFactory {

    /** @return 一份专供本次委派使用的工具注册表，不得包含 {@code task} */
    ToolRegistry create();
}
