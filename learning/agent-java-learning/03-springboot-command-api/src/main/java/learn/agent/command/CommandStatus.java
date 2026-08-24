package learn.agent.command;

/** 智能场景命令在本课中使用的生命周期状态。 */
public enum CommandStatus {
    PENDING,
    RUNNING,
    SUCCEEDED,
    FAILED
}
