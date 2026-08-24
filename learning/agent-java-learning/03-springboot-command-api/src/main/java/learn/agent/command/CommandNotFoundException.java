package learn.agent.command;

/** 查询不存在的 commandId 时使用的业务异常。 */
public class CommandNotFoundException extends RuntimeException {
    public CommandNotFoundException(String commandId) {
        super("command not found: " + commandId);
    }
}
