package learn.agent.redis.lesson03;

/**
 * 从 Redis Hash 读取出来的一条命令状态。
 */
public class RedisCommandState {
    private final String commandId;
    private final String instruction;
    private final String status;
    private final String result;

    public RedisCommandState(String commandId, String instruction, String status, String result) {
        this.commandId = commandId;
        this.instruction = instruction;
        this.status = status;
        this.result = result;
    }

    public String getCommandId() {
        return commandId;
    }

    public String getInstruction() {
        return instruction;
    }

    public String getStatus() {
        return status;
    }

    public String getResult() {
        return result;
    }
}
