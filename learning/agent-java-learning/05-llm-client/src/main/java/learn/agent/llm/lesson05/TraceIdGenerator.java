package learn.agent.llm.lesson05;

import java.util.UUID;

/**
 * trace id 的来源。做成接口只有一个原因：<b>测试需要可预测的 id</b>。
 *
 * <p>如果 {@link AgentLoop} 里直接写 {@code UUID.randomUUID()}，那么每次跑
 * 测试拿到的 trace id 都不一样，断言就只能写成「非空」，等于没断言。
 * 把它抽成接口，测试注入固定值，生产注入随机值。</p>
 *
 * <p>这也是第 1 课「用接口隔离不确定性」那条规则的第二次应用：第 1 课隔离的是
 * 网络调用（{@code ModelClient}），这里隔离的是随机数。凡是「每次结果都不同」
 * 的东西，都该挡在接口后面，否则测试没法断言。</p>
 */
public interface TraceIdGenerator {

    /** @return 一个新的 trace id，非空 */
    String next();

    /** 生产用：随机 UUID。 */
    TraceIdGenerator RANDOM = new TraceIdGenerator() {
        @Override
        public String next() {
            return UUID.randomUUID().toString();
        }
    };

    /** 测试用：返回固定值，让断言能写死具体 id。 */
    static TraceIdGenerator fixed(final String id) {
        return new TraceIdGenerator() {
            @Override
            public String next() {
                return id;
            }
        };
    }
}
