package learn.agent.llm.lesson01;

/**
 * 模型调用边界。
 *
 * <p>这是本课最重要的一个设计：业务代码只依赖这个接口，不直接依赖 OpenAI SDK
 * 或任何 HTTP 客户端。原因有三个：</p>
 * <ul>
 *   <li><b>可测试</b>：测试用 {@code FakeModelClient} 注入固定回复，
 *       不需要真实密钥、不花钱、不受网络影响，也能稳定复现截断和限流分支；</li>
 *   <li><b>可替换</b>：切换模型厂商时只改实现类，业务代码不动；</li>
 *   <li><b>可加横切逻辑</b>：重试、限流、日志、Token 统计都可以做成包装实现，
 *       不用污染业务代码。</li>
 * </ul>
 *
 * <p>注意接口只有一个方法。模型调用本质上就是「发一组消息，拿一段回复」，
 * 不要在这一层就设计出十几个方法。</p>
 */
public interface ModelClient {

    /**
     * 发起一次模型调用。
     *
     * <p>这是同步调用，会阻塞当前线程直到模型返回或超时。因此绝不能在
     * Web 请求线程里直接调它 —— 模型响应通常是秒级，慢的时候几十秒。
     * 阶段 14 会把它移到 MQ 消费者里执行。</p>
     *
     * @param request 本次请求的完整内容
     * @return 模型回复；调用方必须先检查 {@link ChatResponse#getFinishReason()}
     * @throws ModelException 调用失败；通过 {@link ModelException#getErrorType()} 判断能否重试
     */
    ChatResponse chat(ChatRequest request) throws ModelException;
}
