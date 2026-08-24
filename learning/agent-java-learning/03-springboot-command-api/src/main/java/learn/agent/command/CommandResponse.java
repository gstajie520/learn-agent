package learn.agent.command;

/** 返回给前端的命令信息，不直接暴露内部对象。 */
public class CommandResponse {
    private final String commandId;
    private final String instruction;
    private final CommandStatus status;
    private final String result;

    public CommandResponse(String commandId, String instruction, CommandStatus status, String result) {
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

    public CommandStatus getStatus() {
        return status;
    }

    public String getResult() {
        return result;
    }

    public static CommandResponse from(CommandRecord record) {
        return new CommandResponse(
                record.getCommandId(),
                record.getInstruction(),
                record.getStatus(),
                record.getResult()
        );
    }
}
