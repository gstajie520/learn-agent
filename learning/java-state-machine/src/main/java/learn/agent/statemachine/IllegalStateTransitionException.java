package learn.agent.statemachine;

/**
 * 当命令尝试进行未被业务规则允许的状态迁移时抛出。
 */
public final class IllegalStateTransitionException extends IllegalStateException {

    /**
     * 创建包含当前状态和目标状态的领域异常。
     *
     * @param current 当前状态
     * @param next    尝试迁移到的目标状态
     */
    public IllegalStateTransitionException(CommandStatus current, CommandStatus next) {
        super("Illegal command transition: " + current + " -> " + next);
    }
}
