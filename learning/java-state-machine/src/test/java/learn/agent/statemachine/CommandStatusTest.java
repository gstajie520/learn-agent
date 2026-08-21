package learn.agent.statemachine;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * {@link SceneCommand} 的行为测试。
 *
 * <p>这些测试不是为了验证私有字段怎么存，而是验证命令对外表现出的业务规则：
 * 哪些状态迁移允许、哪些迁移必须拒绝，以及失败后状态是否保持不变。</p>
 */
class CommandStatusTest {

    /** 验证智能场景命令从创建到用户确认应用的正常路径。 */
    @Test
    void allowsTheHappyPath() {
        // Arrange：新命令总是从 PENDING 开始。
        SceneCommand command = new SceneCommand("cmd-001");

        // Act：模拟 Java 创建命令、Agent 生成预览、用户确认应用。
        command.transitionTo(CommandStatus.RUNNING);
        command.transitionTo(CommandStatus.PREVIEW);
        command.transitionTo(CommandStatus.APPLIED);

        // Assert：最终状态必须是 APPLIED。
        assertEquals(CommandStatus.APPLIED, command.status());
    }

    /** 验证运行中的命令可以进入失败、超时和用户取消等终态。 */
    @Test
    void allowsFailureAndCancellationBranches() {
        // Arrange + Act：模拟 Agent 处理失败。
        SceneCommand failed = new SceneCommand("cmd-failed");
        failed.transitionTo(CommandStatus.RUNNING);
        failed.transitionTo(CommandStatus.FAILED);

        // Arrange + Act：模拟 Agent 处理超过业务时间限制。
        SceneCommand timedOut = new SceneCommand("cmd-timeout");
        timedOut.transitionTo(CommandStatus.RUNNING);
        timedOut.transitionTo(CommandStatus.TIMEOUT);

        // Arrange + Act：模拟任务尚未开始执行时，用户主动取消。
        SceneCommand cancelled = new SceneCommand("cmd-cancelled");
        cancelled.transitionTo(CommandStatus.CANCELLED);

        // Assert：三个分支都应停在各自的终态。
        assertEquals(CommandStatus.FAILED, failed.status());
        assertEquals(CommandStatus.TIMEOUT, timedOut.status());
        assertEquals(CommandStatus.CANCELLED, cancelled.status());
    }

    /** 验证命令 ID 是跨 MQ、Redis 和服务调用关联同一命令的必要标识。 */
    @Test
    void rejectsBlankCommandIds() {
        // Act：尝试创建没有有效幂等标识的命令。
        IllegalArgumentException exception = assertThrows(
                IllegalArgumentException.class,
                () -> new SceneCommand("  ")
        );

        // Assert：对象创建失败，并返回可定位问题的错误信息。
        assertEquals("commandId must not be blank", exception.getMessage());
    }

    /** 验证不能跳过 Agent 执行和用户预览，直接把命令标记为已应用。 */
    @Test
    void rejectsIllegalTransitions() {
        // Arrange：命令仍处于等待执行状态。
        SceneCommand command = new SceneCommand("cmd-002");

        // Act + Assert：PENDING -> APPLIED 是非法迁移，必须抛领域异常。
        IllegalStateTransitionException exception = assertThrows(
                IllegalStateTransitionException.class,
                () -> command.transitionTo(CommandStatus.APPLIED)
        );

        // Assert：失败后仍保持 PENDING，不能留下半修改状态。
        assertEquals("Illegal command transition: PENDING -> APPLIED", exception.getMessage());
        assertEquals(CommandStatus.PENDING, command.status());
    }

    /** 验证终态不会被重新打开，避免同一命令被重复执行。 */
    @Test
    void protectsTerminalStates() {
        // Arrange：命令已被用户取消，进入终态。
        SceneCommand command = new SceneCommand("cmd-003");
        command.transitionTo(CommandStatus.CANCELLED);

        // Act + Assert：终态不能重新回到 RUNNING。
        assertThrows(
                IllegalStateTransitionException.class,
                () -> command.transitionTo(CommandStatus.RUNNING)
        );
        assertEquals(CommandStatus.CANCELLED, command.status());
    }

    /** 验证重复迁移不会被误当成新的成功处理。 */
    @Test
    void repeatedTransitionDoesNotSilentlySucceed() {
        // Arrange：第一次迁移成功。
        SceneCommand command = new SceneCommand("cmd-004");
        command.transitionTo(CommandStatus.RUNNING);

        // Act + Assert：第二次重复迁移被拒绝，类似重复 MQ 消息的本地防线。
        assertThrows(
                IllegalStateTransitionException.class,
                () -> command.transitionTo(CommandStatus.RUNNING)
        );
        assertEquals(CommandStatus.RUNNING, command.status());
    }

    /** 验证空目标状态不会被当成合法迁移。 */
    @Test
    void rejectsNullAsTheNextStatus() {
        // Arrange：命令仍等待执行。
        SceneCommand command = new SceneCommand("cmd-null");

        // Act + Assert：null 不是业务状态，必须被拒绝。
        assertThrows(
                IllegalStateTransitionException.class,
                () -> command.transitionTo(null)
        );
        assertEquals(CommandStatus.PENDING, command.status());
    }

    /** 验证一个命令的状态变化不会污染另一个命令实例。 */
    @Test
    void commandInstancesKeepIndependentState() {
        // Arrange：创建两个相互独立的用户命令。
        SceneCommand first = new SceneCommand("cmd-first");
        SceneCommand second = new SceneCommand("cmd-second");

        // Act：只推进第一个命令。
        first.transitionTo(CommandStatus.RUNNING);

        // Assert：第二个命令仍保持初始状态。
        assertEquals(CommandStatus.RUNNING, first.status());
        assertEquals(CommandStatus.PENDING, second.status());
    }
}
