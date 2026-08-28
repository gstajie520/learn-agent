package learn.agent.llm.client;

/**
 * 等待动作的抽象。
 *
 * <p>为什么要为「睡一会儿」单独定义接口：退避重试的正确性体现在
 * <b>等了多久</b>，而不只是最终结果对不对。如果直接调
 * {@code Thread.sleep()}，测试验证「第一次等 500ms、第二次等 1000ms」
 * 就必须真的等 1.5 秒。几个这样的测试就能让整个测试套件慢到没人愿意跑。</p>
 *
 * <p>把等待抽象出来后，测试注入一个只<b>记录</b>时长、不真正睡眠的实现，
 * 于是既能断言退避序列，又是毫秒级完成。这和第 1 课用
 * {@code FakeModelClient} 替换真实模型是同一个思路。</p>
 */
public interface Sleeper {

    /**
     * 等待指定毫秒数。
     *
     * @param millis 等待时长
     * @throws InterruptedException 等待被中断
     */
    void sleep(long millis) throws InterruptedException;

    /** 生产实现：真正调用 {@code Thread.sleep()}。 */
    Sleeper REAL = new Sleeper() {
        @Override
        public void sleep(long millis) throws InterruptedException {
            Thread.sleep(millis);
        }
    };
}
