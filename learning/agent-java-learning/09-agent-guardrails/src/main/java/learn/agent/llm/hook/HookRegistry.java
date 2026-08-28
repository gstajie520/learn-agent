package learn.agent.llm.hook;

import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.structured.ValidationResult;
import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.permission.PermissionBehavior;

/**
 * 按事件保存回调队列，串行执行并把多个结果合并成一个。
 *
 * <p>这个类是本课的主体，三件事：<b>注册顺序即执行顺序</b>、
 * <b>后一个回调看到的是前一个回调改过的上下文</b>、
 * <b>多个结果按字段各自的规则合并</b>。</p>
 *
 * <h3>为什么是串行而不是并行</h3>
 * <p>并行看起来更快，但 Hook 之间是有依赖的：第一个 Hook 把参数里的路径改了，
 * 第二个 Hook 要审查的就该是<b>改过之后</b>的参数。并行执行时两个 Hook 看到的
 * 都是原始参数，第二个 Hook 的审查等于白做 —— 它批准的是一份不会被执行的输入。
 * 这正是 {@link #run} 里每次循环都可能重建 {@code current} 上下文的原因。</p>
 *
 * <h3>合并规则（每个字段不一样，不能用一套逻辑套完）</h3>
 * <table border="1">
 *   <caption>字段合并策略</caption>
 *   <tr><th>字段</th><th>策略</th><th>为什么</th></tr>
 *   <tr><td>{@code permissionBehavior}</td><td>取最严格</td><td>安全建议只能收紧，不能被后来的 allow 冲掉</td></tr>
 *   <tr><td>{@code updatedInput/Output}</td><td>后者覆盖前者</td><td>串行链条上，最后一次改写才是要执行的那份</td></tr>
 *   <tr><td>{@code additionalContext}</td><td>按顺序拼接</td><td>每个 Hook 的说明都要留下，不是互相替代</td></tr>
 *   <tr><td>{@code preventContinuation}</td><td>逻辑或</td><td>任何一个 Hook 要求停，就得停</td></tr>
 *   <tr><td>{@code blockingError}</td><td>保留最先出现的并短路</td><td>第一个拦下就已经决定了结局，后面的 Hook 不该再改写理由</td></tr>
 *   <tr><td>{@code forceContinue}</td><td>保留最先出现的并短路</td><td>同上</td></tr>
 * </table>
 *
 * <h3>这里的优先级阶梯和第 6 课不是同一套</h3>
 * <p>第 6 课 {@code PermissionPolicy.strongest} 是<b>三轮扫描</b>，passthrough
 * 被完全忽略（弃权不参与计票）。本类的 {@link #stronger} 是<b>四级比较</b>：
 * {@code passthrough=0 < allow=1 < ask=2 < deny=3}。</p>
 *
 * <p>差别的来源是两者在回答不同的问题。第 6 课要从一堆候选里<b>挑出一条</b>带着
 * reason 和 source 进审计，所以弃权票必须排除，同级还必须稳定取最早的那条。
 * 本类只是把 N 个 Hook 的建议<b>压成一个值</b>再交给第 6 课当候选，passthrough
 * 是这里的合法初始值（{@link HookResult#noop()} 就是它），参与比较不会有歧义。
 * 两套阶梯<b>不要合并成一个 Comparator</b> —— 它们的输入语义不同。</p>
 */
public final class HookRegistry {

    /** 每个事件一条独立队列。EnumMap 保证四个事件都有槽位，不会出现 null 队列。 */
    private final Map<HookEvent, List<HookCallback>> callbacks =
            new EnumMap<HookEvent, List<HookCallback>>(HookEvent.class);

    public HookRegistry() {
        for (HookEvent event : HookEvent.values()) {
            callbacks.put(event, new ArrayList<HookCallback>());
        }
    }

    /**
     * 注册一个回调到队列尾部。
     *
     * <p>追加而不是插入：<b>注册顺序就是执行顺序</b>，而且这个顺序对结果有影响
     * （见 {@link #run} 的串行传递）。如果注册顺序不确定，同一套 Hook 在两次
     * 启动里可能给出不同的裁决，这种 bug 极难查。</p>
     */
    public void register(HookEvent event, HookCallback callback) {
        if (event == null) {
            throw new HookContractException("event 不能为空");
        }
        if (callback == null) {
            throw new HookContractException("callback 不能为空");
        }
        callbacks.get(event).add(callback);
    }

    /** @return 某个事件已注册的回调数，给测试和诊断用 */
    public int count(HookEvent event) {
        if (event == null) {
            throw new HookContractException("event 不能为空");
        }
        return callbacks.get(event).size();
    }

    /**
     * 串行跑完一个事件的全部回调，返回合并后的<b>单个</b>结果。
     *
     * <p>调用方（Loop）只需要读这一个结果，不需要知道有几个 Hook 注册过、
     * 谁改了什么。这是「横切逻辑不塞回 Loop 内部」的落地方式：Loop 看到的是
     * 一个声明式的结果对象，而不是一串回调。</p>
     *
     * @throws HookContractException 回调返回 null、返回越权字段，或 updatedInput 违反三道锁
     */
    public HookResult run(HookContext context) {
        if (context == null) {
            throw new HookContractException("context 不能为空");
        }

        HookResult combined = HookResult.noop();
        HookContext current = context;

        for (HookCallback callback : callbacks.get(context.getEvent())) {
            HookResult outcome = callback.handle(current);
            if (outcome == null) {
                throw new HookContractException(
                        context.getEvent().getWireValue() + " 的回调返回了 null，应当返回 HookResult.noop()");
            }
            // 先查越权：一个 Stop Hook 返回 updatedInput 是写错了，不该被静默忽略。
            outcome.validateFor(context.getEvent());

            HookResult effective = normalize(current, outcome);
            combined = merge(combined, effective);

            // 串行的关键：把改过的输入/输出写回上下文，下一个回调看到的是新的那份。
            if (effective.getUpdatedInput() != null) {
                current = HookContext.preToolUse(effective.getUpdatedInput());
            }
            if (effective.getUpdatedOutput() != null && current.getPrepared() != null) {
                current = HookContext.postToolUse(current.getPrepared(), effective.getUpdatedOutput());
            }
            // 拦下或强制续写之后，后面的回调不再执行：结局已经定了。
            if (effective.getBlockingError() != null || effective.getForceContinue() != null) {
                break;
            }
        }
        return combined;
    }

    /** UserPromptSubmit：用户消息进历史之前。 */
    public HookResult runUserPrompt(learn.agent.llm.client.ChatMessage message) {
        return run(HookContext.userPromptSubmit(message));
    }

    /** PreToolUse：prepare 之后、权限裁决之前。 */
    public HookResult runPreTool(PreparedToolCall prepared) {
        return run(HookContext.preToolUse(prepared));
    }

    /** PostToolUse：handler 返回之后、结果回传模型之前。 */
    public HookResult runPostTool(PreparedToolCall prepared,
                                  learn.agent.llm.tool.ToolExecutionResult result) {
        return run(HookContext.postToolUse(prepared, result));
    }

    /** Stop：模型给出最终答复、准备返回之前。 */
    public HookResult runStop(List<learn.agent.llm.client.ChatMessage> history, boolean stopHookActive) {
        return run(HookContext.stop(history, stopHookActive));
    }

    /**
     * 对回调结果做两处规范化：{@code updatedInput} 过三道锁，Stop 的重复续写被吞掉。
     */
    private static HookResult normalize(HookContext context, HookResult outcome) {
        PreparedToolCall normalizedInput = normalizeUpdatedInput(context, outcome);

        HookResult result = outcome;
        if (normalizedInput != null) {
            // 换成脱离 Hook 引用的那一份。注意 forceContinue/updatedOutput 不用带：
            // updatedInput 只可能出现在 PreToolUse，而那个事件不允许这两个字段。
            result = HookResult.builder()
                    .permissionBehavior(outcome.getPermissionBehavior())
                    .updatedInput(normalizedInput)
                    .addAllContext(outcome.getAdditionalContext())
                    .blockingError(outcome.getBlockingError())
                    .build();
        }

        // Stop 已经续写过一次，就不允许再续：否则一个「总是要求继续」的 Hook
        // 能让循环永远不结束。additionalContext 保留 —— 它只是说明文字，无害。
        if (context.getEvent() == HookEvent.STOP
                && context.isStopHookActive()
                && result.getForceContinue() != null) {
            return HookResult.builder()
                    .addAllContext(result.getAdditionalContext())
                    .build();
        }
        return result;
    }

    /**
     * {@code updatedInput} 的三道锁，本课的安全核心。
     *
     * <p>威胁模型是<b>「批准 A、执行 B」</b>：Hook 在 PreToolUse 里返回一份看起来
     * 无害的参数、等权限批准之后再改成危险参数。三道锁分别封死一条路：</p>
     * <ol>
     *   <li><b>tool_call_id 必须一致</b> —— 否则回传结果会和模型的另一次调用配错，
     *       模型以为 A 的结果是 B 的。</li>
     *   <li><b>工具名必须一致</b> —— Hook 不能把 {@code read_device} 换成
     *       {@code delete_device}。改工具名等于换了一个完全不同的操作，
     *       而模型和用户看到的还是原来那个。</li>
     *   <li><b>definition 必须是<em>同一个对象</em></b> —— 用 {@code !=} 判断引用，
     *       不是 {@code equals}。构造一个字段完全相同、但 handler 指向别处的
     *       {@code ToolDefinition}，{@code equals} 会说它们相等（何况
     *       {@link ToolDefinition} 根本没重写 equals，那就更没得比），
     *       但执行的是攻击者的 handler。<b>这里要的是「就是注册表里那一个」，
     *       只有引用相等能表达这件事。</b></li>
     * </ol>
     *
     * <p>三道锁过完还要<b>重跑一遍参数校验</b>，然后返回一份<b>新构造</b>的
     * {@link PreparedToolCall}。为什么不能直接用 Hook 给的那个对象：Hook 手里
     * 还捏着它的引用，理论上可以在裁决通过之后改内部状态。返回新对象之后，
     * 后续的权限裁决和执行读的都是这一份，Hook 改不到。</p>
     *
     * @return 规范化后的调用；Hook 没提供 updatedInput 时返回 null
     */
    private static PreparedToolCall normalizeUpdatedInput(HookContext context, HookResult outcome) {
        PreparedToolCall updated = outcome.getUpdatedInput();
        if (updated == null) {
            return null;
        }
        PreparedToolCall original = context.getPrepared();
        if (original == null || original.getDefinition() == null) {
            throw new HookContractException("updatedInput 需要一个已存在的 prepared 调用");
        }

        ToolCall updatedCall = updated.getCall();
        ToolCall originalCall = original.getCall();
        if (!originalCall.getId().equals(updatedCall.getId())) {
            throw new HookContractException("updatedInput 必须保留原来的 tool_call_id");
        }
        if (!originalCall.getName().equals(updatedCall.getName())) {
            throw new HookContractException("updatedInput 必须保留原来的工具名");
        }
        if (updated.getDefinition() != original.getDefinition()) {
            // 引用比较，不是 equals。见方法 javadoc 第三条。
            throw new HookContractException("updatedInput 必须保留注册表里那一份工具定义");
        }

        JsonNode arguments = updated.getArguments();
        if (arguments == null || !arguments.isObject()) {
            throw new HookContractException("updatedInput 的参数必须是 JSON 对象");
        }
        // 重新校验：Hook 改过的参数不比模型给的更可信。
        ToolDefinition definition = original.getDefinition();
        if (definition.hasValidator()) {
            ValidationResult<JsonNode> validated = definition.getValidator().validate(arguments);
            if (!validated.isValid()) {
                throw new HookContractException(
                        "updatedInput 的参数没通过工具自己的校验：" + validated.getErrorMessage());
            }
        }
        // deepCopy 之后 Hook 手里的引用改不到这一份。
        return PreparedToolCall.ready(originalCall, definition, arguments.deepCopy());
    }

    /** 按 javadoc 表格里那六条规则合并两个结果。 */
    private static HookResult merge(HookResult current, HookResult incoming) {
        HookResult.Builder builder = HookResult.builder()
                .permissionBehavior(stronger(
                        current.getPermissionBehavior(), incoming.getPermissionBehavior()))
                .updatedInput(incoming.getUpdatedInput() == null
                        ? current.getUpdatedInput() : incoming.getUpdatedInput())
                .updatedOutput(incoming.getUpdatedOutput() == null
                        ? current.getUpdatedOutput() : incoming.getUpdatedOutput())
                .addAllContext(current.getAdditionalContext())
                .addAllContext(incoming.getAdditionalContext())
                .preventContinuation(current.isPreventContinuation() || incoming.isPreventContinuation());

        // blockingError 和 forceContinue 保留最先出现的：第一个拦下的 Hook
        // 已经决定了结局，后面的不该改写用户看到的理由。
        builder.blockingError(current.getBlockingError() == null
                ? incoming.getBlockingError() : current.getBlockingError());
        builder.forceContinue(current.getForceContinue() == null
                ? incoming.getForceContinue() : current.getForceContinue());
        return builder.build();
    }

    /**
     * 四级比较取更严格的那个：{@code passthrough < allow < ask < deny}。
     *
     * <p>用显式的 {@code rank} 而不是 {@code ordinal()}：{@code ordinal}
     * 把优先级绑在枚举的声明顺序上，有人重排一下 {@link PermissionBehavior}
     * 的常量，这里就会静默地变成另一套优先级，而且编译和现有测试都不会报错。</p>
     */
    private static PermissionBehavior stronger(PermissionBehavior current, PermissionBehavior incoming) {
        return rank(incoming) > rank(current) ? incoming : current;
    }

    private static int rank(PermissionBehavior behavior) {
        switch (behavior) {
            case DENY:
                return 3;
            case ASK:
                return 2;
            case ALLOW:
                return 1;
            case PASSTHROUGH:
                return 0;
            default:
                throw new HookContractException("未知的权限行为：" + behavior);
        }
    }

    /** @return 某事件回调的只读视图，给诊断用 */
    public List<HookCallback> callbacksOf(HookEvent event) {
        if (event == null) {
            throw new HookContractException("event 不能为空");
        }
        return Collections.unmodifiableList(callbacks.get(event));
    }
}
