package learn.agent.command;

/**
 * 内存中的命令记录。
 *
 * <p>本课暂时不用数据库，目的是先看懂 Controller 如何调用 Service。
 * 生产环境不能只依赖这个内存对象，后续会替换为 Redis/数据库。</p>
 */
public class CommandRecord {
    private final String commandId;
    private final String instruction;
    private volatile CommandStatus status;
    private volatile String result;

    public CommandRecord(String commandId, String instruction) {
        this.commandId = commandId;
        this.instruction = instruction;
        this.status = CommandStatus.PENDING;
    }

    public String getCommandId() {
        return commandId;
    }

    public String getInstruction() {
        return instruction;
    }

    public CommandStatus getStatus() {
        return status;
    }

    public String getResult() {
        return result;
    }

    public void markRunning() {
        this.status = CommandStatus.RUNNING;
    }

    public void markSucceeded(String result) {
        this.result = result;
        this.status = CommandStatus.SUCCEEDED;
    }

    public void markFailed(String result) {
        this.result = result;
        this.status = CommandStatus.FAILED;
    }
}
