package learn.agent.redis.lesson01;

/** 命令幂等抢占的结果。 */
public enum ClaimResult {
    /** 当前消费者第一次抢到命令，可以继续执行。 */
    CLAIMED,
    /** 已经有其他消费者处理过或正在处理，当前消费者不能重复执行。 */
    ALREADY_CLAIMED
}
