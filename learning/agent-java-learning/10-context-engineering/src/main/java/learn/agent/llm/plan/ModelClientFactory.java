package learn.agent.llm.plan;

import learn.agent.llm.client.ModelClient;

/**
 * 子 Agent 的模型客户端工厂。
 *
 * <p><b>为什么是工厂而不是实例。</b>每次 {@code task} 调用都要一个全新的子 Agent。
 * 如果构造时传一个客户端实例进来，两次委派就共享同一个对象 —— 测试里用
 * {@code FakeModelClient} 排响应队列时，第二次委派会接着读第一次剩下的队列，
 * 两个本该无关的子任务互相污染。生产里如果客户端带连接状态、重试计数或
 * 熔断器状态，问题一模一样。</p>
 *
 * <p>这条和「隔离历史」是同一个目标的两面：历史隔离靠新建循环，依赖隔离靠工厂。
 * 少任何一半，子 Agent 都不是真的从零开始。</p>
 */
public interface ModelClientFactory {

    /** @return 一个专供本次委派使用的模型客户端 */
    ModelClient create();
}
