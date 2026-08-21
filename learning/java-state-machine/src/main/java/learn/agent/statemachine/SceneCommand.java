package learn.agent.statemachine;

import java.util.EnumMap;
import java.util.EnumSet;
import java.util.Map;
import java.util.Set;

/**
 * 智能场景命令的领域对象。
 *
 * <p>Java 服务收到前端请求后，会先创建这个对象；随后 Python Agent
 * 可能返回预览、失败或超时结果。所有状态变化都必须经过
 * {@link #transitionTo(CommandStatus)}，避免不同调用方随意写入状态。</p>
 *
 * <p>这个类只负责单个 JVM 内的状态规则，不负责 Redis 持久化、MQ 消费
 * 或跨实例幂等。那些能力属于更外层的应用服务。</p>
 */
public final class SceneCommand {

    /**
     * 状态迁移表：key 是当前状态，value 是允许到达的目标状态。
     *
     * <p>使用集中表而不是在多个 if/else 中分散规则，便于审查和测试。
     * {@code Map.copyOf} 会冻结外层 Map，防止运行时被外部修改。</p>
     */
    private static final Map<CommandStatus, Set<CommandStatus>> ALLOWED_TRANSITIONS = createTransitions();

    /** 命令的幂等标识；真实系统会用它关联 Redis/MQ 中的同一条命令。 */
    private final String commandId;

    /** 当前命令状态，只能通过 {@link #transitionTo(CommandStatus)} 修改。 */
    private CommandStatus status;

    /**
     * 创建一个新命令。新命令必须从 {@link CommandStatus#PENDING} 开始。
     *
     * @param commandId 命令唯一标识，不能为空或空白
     */
    public SceneCommand(String commandId) {
        if (commandId == null || commandId.isBlank()) {
            throw new IllegalArgumentException("commandId must not be blank");
        }
        this.commandId = commandId;
        this.status = CommandStatus.PENDING;
    }

    /**
     * 获取命令标识。
     *
     * @return 命令标识
     */
    public String commandId() {
        return commandId;
    }

    /**
     * 获取当前状态的只读快照。
     *
     * @return 当前状态
     */
    public CommandStatus status() {
        return status;
    }

    /**
     * 按业务迁移规则推进命令状态。
     *
     * <p>关键顺序是“先校验，后写入”：如果目标状态不允许，
     * 当前状态不会被破坏。</p>
     *
     * @param next 目标状态
     * @throws IllegalStateTransitionException 目标状态不允许时抛出
     */
    public void transitionTo(CommandStatus next) {
        if (next == null || !ALLOWED_TRANSITIONS.get(status).contains(next)) {
            throw new IllegalStateTransitionException(status, next);
        }
        status = next;
    }

    /**
     * 构造完整迁移表。
     *
     * <p>没有配置后继状态的状态就是终态，表示命令已经结束，
     * 不能再回到执行中。</p>
     */
    private static Map<CommandStatus, Set<CommandStatus>> createTransitions() {
        EnumMap<CommandStatus, Set<CommandStatus>> transitions = new EnumMap<>(CommandStatus.class);
        transitions.put(CommandStatus.PENDING, EnumSet.of(CommandStatus.RUNNING, CommandStatus.CANCELLED));
        transitions.put(CommandStatus.RUNNING, EnumSet.of(
                CommandStatus.PREVIEW,
                CommandStatus.FAILED,
                CommandStatus.TIMEOUT
        ));
        transitions.put(CommandStatus.PREVIEW, EnumSet.of(CommandStatus.APPLIED));
        transitions.put(CommandStatus.APPLIED, EnumSet.noneOf(CommandStatus.class));
        transitions.put(CommandStatus.FAILED, EnumSet.noneOf(CommandStatus.class));
        transitions.put(CommandStatus.TIMEOUT, EnumSet.noneOf(CommandStatus.class));
        transitions.put(CommandStatus.CANCELLED, EnumSet.noneOf(CommandStatus.class));
        return Map.copyOf(transitions);
    }
}
