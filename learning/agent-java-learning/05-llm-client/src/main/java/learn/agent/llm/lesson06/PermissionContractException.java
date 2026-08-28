package learn.agent.llm.lesson06;

/**
 * 权限契约被违反时抛出。
 *
 * <p>为什么这里用异常，而第 4 课说「工具失败是返回值不是异常」：两者的
 * 消费者不同。工具执行失败要回传给<b>模型</b>看，所以是返回值；契约违反是
 * <b>写代码的人</b>搞错了（把 ASK 当最终态用、reason 传空字符串），
 * 模型对此无能为力，必须让程序崩掉暴露出来。</p>
 *
 * <p>换句话说：能让模型自我纠正的走返回值，只有程序员能修的走异常。</p>
 */
public class PermissionContractException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    public PermissionContractException(String message) {
        super(message);
    }
}
