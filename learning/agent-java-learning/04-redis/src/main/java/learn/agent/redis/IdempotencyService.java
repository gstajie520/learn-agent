package learn.agent.redis;

/**
 * 命令幂等服务。
 *
 * <p>真实项目中，这里的 RedisLikeStore 会替换为 StringRedisTemplate，
 * 但业务调用方只关心“是否抢占成功”。</p>
 */
public class IdempotencyService {
    /** 幂等抢占记录保留 10 分钟，防止消费者异常后永久锁死。 */
    private static final long CLAIM_TTL_MILLIS = 10 * 60 * 1000L;

    /** 提供 SETNX 和 TTL 能力的共享状态边界。 */
    private final RedisLikeStore store;

    /**
     * @param store Redis 语义存储；两个消费者必须共享同一个存储才能互相看见状态
     */
    public IdempotencyService(RedisLikeStore store) {
        if (store == null) {
            throw new IllegalArgumentException("store 不能为空");
        }
        this.store = store;
    }

    /**
     * 尝试抢占命令执行权。
     *
     * <p>同一个 commandId 生成固定 key；SETNX 成功的消费者才允许继续执行业务。</p>
     */
    public ClaimResult claim(String commandId) {
        validateCommandId(commandId);
        String key = "agent:command:claim:" + commandId;
        boolean firstConsumer = store.setIfAbsent(key, "PROCESSING", CLAIM_TTL_MILLIS);
        return firstConsumer ? ClaimResult.CLAIMED : ClaimResult.ALREADY_CLAIMED;
    }

    /** 查询当前命令是否已经被记录为处理中。 */
    public String getClaimStatus(String commandId) {
        validateCommandId(commandId);
        return store.get("agent:command:claim:" + commandId);
    }

    /** commandId 是幂等 key 的组成部分，不能为空，否则不同请求会错误地共用一个 key。 */
    private void validateCommandId(String commandId) {
        if (commandId == null || commandId.trim().isEmpty()) {
            throw new IllegalArgumentException("commandId 不能为空");
        }
    }
}
