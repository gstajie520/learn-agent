package learn.agent.llm.lesson07;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRole;
import learn.agent.llm.lesson04.PreparedToolCall;
import learn.agent.llm.lesson04.ToolExecutionResult;
import learn.agent.llm.lesson06.PermissionBehavior;

/**
 * 一次 Hook 回调的<b>影响</b>，声明式。
 *
 * <p>这是整课的关键设计：<b>Hook 不能直接改 Loop，只能返回一个描述「我想要什么」
 * 的对象。</b>对比一下如果给回调传一个可写的 Loop 引用会发生什么 —— 任意一个
 * 第三方 Hook 都能改历史、改工具表、改轮次上限，而且改动没有任何记录。
 * 换成返回值之后，每一项影响都必须落在下面七个字段之一，也就必须被
 * {@link #validateFor} 检查过。</p>
 *
 * <h3>七个字段，各自绑死一个事件</h3>
 * <table border="1">
 *   <tr><th>字段</th><th>允许的事件</th><th>作用</th></tr>
 *   <tr><td>{@code permissionBehavior}</td><td>PreToolUse</td><td>给权限策略提一条建议</td></tr>
 *   <tr><td>{@code updatedInput}</td><td>PreToolUse</td><td>改写调用参数</td></tr>
 *   <tr><td>{@code blockingError}</td><td>PreToolUse</td><td>直接阻断并回填错误</td></tr>
 *   <tr><td>{@code updatedOutput}</td><td>PostToolUse</td><td>改写执行结果</td></tr>
 *   <tr><td>{@code preventContinuation}</td><td>PostToolUse</td><td>停掉本轮剩余调用</td></tr>
 *   <tr><td>{@code forceContinue}</td><td>Stop</td><td>要求再跑一轮</td></tr>
 *   <tr><td>{@code additionalContext}</td><td>任意</td><td>追加系统消息</td></tr>
 * </table>
 *
 * <p>只有 {@code additionalContext} 是四个事件通用的，因为「补一句上下文」在任何
 * 时点都无害：它是 system 角色的追加消息，不改变已经发生的事，也不影响本次调用的
 * 执行与否。其余六个都会改变控制流，所以必须绑定事件。</p>
 *
 * <p><b>为什么 {@code permissionBehavior} 只是「建议」？</b>因为放行权不在 Hook
 * 手上。Hook 的 allow 只是第 6 课 {@link learn.agent.llm.lesson06.PermissionPolicy}
 * 收集的一个候选，系统的 deny 在归约里依然压过它。如果 Hook 能直接放行，
 * 「注册一个 Hook」就成了绕过全部权限的后门。</p>
 *
 * <p>默认值刻意选成「什么都不做」：{@code permissionBehavior} 是
 * {@link PermissionBehavior#PASSTHROUGH}（弃权），其余为 null / false / 空列表。
 * 所以 {@code HookResult.noop()} 是一个完全无副作用的结果，写一个只读的
 * 观察型 Hook 不需要了解任何字段。</p>
 */
public final class HookResult {

    /** 对权限的建议。默认 PASSTHROUGH = 弃权。 */
    private final PermissionBehavior permissionBehavior;

    /** 改写后的调用参数；null 表示不改。 */
    private final PreparedToolCall updatedInput;

    /** 改写后的执行结果；null 表示不改。 */
    private final ToolExecutionResult updatedOutput;

    /** 要追加的系统消息，只允许 system 角色。 */
    private final List<ChatMessage> additionalContext;

    /** 阻断执行并直接回填的错误结果；必须是 error 态。 */
    private final ToolExecutionResult blockingError;

    /** 是否停掉本轮剩余的工具调用。 */
    private final boolean preventContinuation;

    /** 要求续跑时补进历史的用户消息；只允许 user 角色。 */
    private final ChatMessage forceContinue;

    private HookResult(Builder builder) {
        this.permissionBehavior = builder.permissionBehavior == null
                ? PermissionBehavior.PASSTHROUGH : builder.permissionBehavior;
        this.updatedInput = builder.updatedInput;
        this.updatedOutput = builder.updatedOutput;
        this.additionalContext = Collections.unmodifiableList(
                new ArrayList<ChatMessage>(builder.additionalContext));
        this.blockingError = builder.blockingError;
        this.preventContinuation = builder.preventContinuation;
        this.forceContinue = builder.forceContinue;
    }

    /** 什么都不做。观察型 Hook 用这个。 */
    public static HookResult noop() {
        return new Builder().build();
    }

    public static Builder builder() {
        return new Builder();
    }

    /**
     * 检查本结果是否只用了该事件允许的字段。
     *
     * <p>违规<b>抛异常</b>而不是静默丢弃：一个 Stop Hook 返回了
     * {@code updatedInput}，说明写它的人搞错了事件语义。静默忽略的话，
     * 他会以为参数改成功了，而实际上工具用的还是原参数 —— 这种「以为生效了
     * 其实没生效」的错误极难查。</p>
     *
     * <p>一次收集完所有违规字段再抛，不是遇到第一个就抛：写 Hook 的人一次就能
     * 看到全部问题。</p>
     */
    public void validateFor(HookEvent event) {
        if (event == null) {
            throw new HookContractException("event 不能为空");
        }
        List<String> invalid = new ArrayList<String>();
        if (event != HookEvent.PRE_TOOL_USE) {
            if (permissionBehavior != PermissionBehavior.PASSTHROUGH) {
                invalid.add("permissionBehavior");
            }
            if (updatedInput != null) {
                invalid.add("updatedInput");
            }
            if (blockingError != null) {
                invalid.add("blockingError");
            }
        }
        if (event != HookEvent.POST_TOOL_USE) {
            if (updatedOutput != null) {
                invalid.add("updatedOutput");
            }
            if (preventContinuation) {
                invalid.add("preventContinuation");
            }
        }
        if (event != HookEvent.STOP && forceContinue != null) {
            invalid.add("forceContinue");
        }
        if (!invalid.isEmpty()) {
            throw new HookContractException(
                    event.getWireValue() + " 不允许这些字段：" + invalid);
        }
    }

    public PermissionBehavior getPermissionBehavior() {
        return permissionBehavior;
    }

    /** @return 改写后的调用；不改时为 null */
    public PreparedToolCall getUpdatedInput() {
        return updatedInput;
    }

    /** @return 改写后的结果；不改时为 null */
    public ToolExecutionResult getUpdatedOutput() {
        return updatedOutput;
    }

    /** @return 要追加的系统消息，不可修改 */
    public List<ChatMessage> getAdditionalContext() {
        return additionalContext;
    }

    /** @return 阻断用的错误结果；不阻断时为 null */
    public ToolExecutionResult getBlockingError() {
        return blockingError;
    }

    public boolean isPreventContinuation() {
        return preventContinuation;
    }

    /** @return 续跑用的用户消息；不续跑时为 null */
    public ChatMessage getForceContinue() {
        return forceContinue;
    }

    @Override
    public String toString() {
        StringBuilder sb = new StringBuilder("HookResult{permission=");
        sb.append(permissionBehavior.getWireValue());
        if (updatedInput != null) {
            sb.append(", updatedInput");
        }
        if (updatedOutput != null) {
            sb.append(", updatedOutput");
        }
        if (blockingError != null) {
            sb.append(", blockingError=").append(blockingError.getErrorCode());
        }
        if (preventContinuation) {
            sb.append(", preventContinuation");
        }
        if (forceContinue != null) {
            sb.append(", forceContinue");
        }
        if (!additionalContext.isEmpty()) {
            sb.append(", context=").append(additionalContext.size());
        }
        return sb.append('}').toString();
    }

    /**
     * 建造器。
     *
     * <p>七个可选字段用建造器而不是重载构造器：七个参数的构造器调用方读不出
     * 哪个是哪个，而 2^7 种组合也不可能都写成重载。</p>
     *
     * <p>字段合法性在 setter 里当场校验，不留到 build()：越早报错，栈里越能看出
     * 是哪个 Hook 写错了。</p>
     */
    public static final class Builder {

        private PermissionBehavior permissionBehavior = PermissionBehavior.PASSTHROUGH;
        private PreparedToolCall updatedInput;
        private ToolExecutionResult updatedOutput;
        private final List<ChatMessage> additionalContext = new ArrayList<ChatMessage>();
        private ToolExecutionResult blockingError;
        private boolean preventContinuation;
        private ChatMessage forceContinue;

        /** 提一条权限建议。null 视为弃权。 */
        public Builder permissionBehavior(PermissionBehavior behavior) {
            this.permissionBehavior = behavior == null ? PermissionBehavior.PASSTHROUGH : behavior;
            return this;
        }

        /**
         * 改写调用参数。
         *
         * <p>这里只查「是不是一个 ready 态的调用」，三道锁（保留 id、保留工具名、
         * 保留定义）在 {@link HookRegistry} 里查 —— 因为那三条都需要和<b>原始</b>
         * 调用比对，而建造器看不到原始调用。</p>
         */
        public Builder updatedInput(PreparedToolCall prepared) {
            if (prepared != null && prepared.isFailed()) {
                throw new HookContractException("updatedInput 不能是准备失败的调用");
            }
            if (prepared != null && (prepared.getDefinition() == null || prepared.getArguments() == null)) {
                throw new HookContractException("updatedInput 缺少 definition 或 arguments");
            }
            this.updatedInput = prepared;
            return this;
        }

        /** 改写执行结果。 */
        public Builder updatedOutput(ToolExecutionResult result) {
            this.updatedOutput = result;
            return this;
        }

        /**
         * 追加一条系统消息。
         *
         * <p>只收 system 角色：Hook 追加的是<b>给模型的补充说明</b>，不是用户说的话。
         * 允许 Hook 追加 user 消息等于允许它冒充用户，模型无从分辨。</p>
         */
        public Builder addContext(ChatMessage message) {
            if (message == null) {
                throw new HookContractException("additionalContext 不能包含 null");
            }
            if (message.getRole() != ChatRole.SYSTEM) {
                throw new HookContractException("additionalContext 只允许 system 消息，当前是："
                        + message.getRole().getWireValue());
            }
            // 重建一条：避免 Hook 持着同一个引用，在合并之后再去改它。
            this.additionalContext.add(ChatMessage.system(message.getContent()));
            return this;
        }

        /**
         * 批量追加系统消息，逐条走 {@link #addContext} 的校验。
         *
         * <p>合并多个 Hook 的结果时用它。{@code null} 视为空列表，让合并代码
         * 不必到处判空。</p>
         */
        public Builder addAllContext(List<ChatMessage> messages) {
            if (messages == null) {
                return this;
            }
            for (ChatMessage message : messages) {
                addContext(message);
            }
            return this;
        }

        /**
         * 阻断执行，直接回填这个错误。
         *
         * <p>必须是 error 态。允许用 success 结果阻断，等于让 Hook 能伪造一次
         * 「工具执行成功了」而工具压根没跑 —— 模型会把它当成真实结果继续推理。</p>
         */
        public Builder blockingError(ToolExecutionResult error) {
            if (error != null && !error.isError()) {
                throw new HookContractException("blockingError 必须是 error 态的结果");
            }
            this.blockingError = error;
            return this;
        }

        /** 停掉本轮剩余的工具调用。 */
        public Builder preventContinuation(boolean prevent) {
            this.preventContinuation = prevent;
            return this;
        }

        /**
         * 要求再跑一轮，并把这条 user 消息补进历史。
         *
         * <p>只收 user 角色：续跑的语义是「有人又提了一个要求」，而模型只会响应
         * user 消息。塞一条 system 进去模型可能压根不接话，循环白跑一轮。</p>
         */
        public Builder forceContinue(ChatMessage message) {
            if (message != null && message.getRole() != ChatRole.USER) {
                throw new HookContractException("forceContinue 只允许 user 消息，当前是："
                        + message.getRole().getWireValue());
            }
            this.forceContinue = message;
            return this;
        }

        public HookResult build() {
            return new HookResult(this);
        }
    }
}
