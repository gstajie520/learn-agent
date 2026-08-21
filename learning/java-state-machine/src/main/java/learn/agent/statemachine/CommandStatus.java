package learn.agent.statemachine;

/**
 * 智能场景命令的生命周期状态。
 *
 * <p>这些状态描述“命令现在走到哪一步”，不是 MQ 消息本身的状态：
 * MQ 负责传递消息，命令状态由业务代码持久化和查询。</p>
 */
public enum CommandStatus {
    /** 命令已创建，等待投递或执行。 */
    PENDING,
    /** Agent 或后台任务正在处理命令。 */
    RUNNING,
    /** Agent 已生成结构化操作，等待用户预览或确认。 */
    PREVIEW,
    /** 用户确认后，操作已经应用到场景。 */
    APPLIED,
    /** 处理失败，不能继续沿当前流程执行。 */
    FAILED,
    /** 超过业务允许的处理时间。 */
    TIMEOUT,
    /** 用户主动取消，或命令尚未执行前被撤销。 */
    CANCELLED
}
