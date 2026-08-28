package learn.agent.llm.hook;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRequest;
import learn.agent.llm.client.ChatResponse;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.ModelClient;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.tool.AgentMessage;
import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolCallCodec;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolRegistry;
import learn.agent.llm.loop.RoundTrace;
import learn.agent.llm.loop.StopReason;
import learn.agent.llm.loop.ToolCallMemo;
import learn.agent.llm.loop.ToolTimeoutGuard;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.GuardedTrace;
import learn.agent.llm.permission.PermissionDecision;
import learn.agent.llm.permission.PermissionPolicy;
import learn.agent.llm.permission.PermissionRequest;

/**
 * 把 Hook 生命周期接进循环：完整链路是
 * {@code prepare → PreToolUse → 权限 → handler → PostToolUse}。
 *
 * <p>本课要回答的问题和第 6 课不同。第 6 课问「这次调用<b>该不该</b>被允许」，
 * 答案是一个裁决；本课问「<b>在哪些时刻</b>可以插进来看一眼、改一手」，答案是
 * 四个事件。两者的关系是：Hook <b>只能提建议</b>，最终拒绝权仍在
 * {@link PermissionPolicy} 手里。</p>
 *
 * <h3>为什么 Hook 的 permissionBehavior 不能直接生效</h3>
 * <p>它作为 {@code recommendations} 交给策略，和硬边界、破坏性默认、注册规则
 * 一起参与归约。所以一个 Hook 建议 allow、而硬边界说 deny 时，结果是 deny ——
 * 归约里 deny 压过一切。如果让 Hook 的 allow 直接放行，任何一个 Hook 就都成了
 * 绕过全部权限的后门。<b>Hook 是扩展点，不是提权点。</b></p>
 *
 * <h3>五个顺序不能换</h3>
 * <ul>
 *   <li>{@code PreToolUse} 在权限<b>之前</b>：它要能提建议、改参数，改完的参数
 *       才是被裁决的那份。放在权限之后，改参数就成了「批准 A、执行 B」。</li>
 *   <li>权限在 handler <b>之前</b>：这是第 6 课那条闸门，不解释。</li>
 *   <li>{@code PostToolUse} 在结果回传模型<b>之前</b>：改写结果才有意义。</li>
 *   <li>{@code UserPromptSubmit} 在用户消息进历史<b>之前</b>：它追加的 system
 *       说明要和这条用户消息一起被模型看到。</li>
 *   <li>{@code Stop} 在返回<b>之前</b>：它是最后一次「其实还没完」的机会。</li>
 * </ul>
 *
 * <h3>异常处理刻意不对称</h3>
 * <p>{@code PreToolUse} 和 {@code PostToolUse} 的异常被<b>捕获</b>，变成一条工具
 * 错误回传给模型；{@code UserPromptSubmit} 和 {@code Stop} 的异常<b>不捕获</b>，
 * 直接终止整次运行。</p>
 *
 * <p>依据是「这次失败有没有人能收拾」。工具 Hook 挂了，本次调用回填一条错误，
 * 模型下一轮还能换个做法，循环仍然自洽。而 UserPromptSubmit 挂了意味着历史压根
 * 没建立起来、Stop 挂了意味着「该不该继续」这个问题没有答案 —— 这两种情况下
 * 硬撑着跑下去，产出的是一次<b>语义不明</b>的运行。宁可抛出去让调用方看见。</p>
 */
public class HookedAgentLoop {

    private final String model;
    private final ModelClient client;
    private final ToolRegistry registry;
    private final ToolContext context;
    private final int maxRounds;
    private final ToolTimeoutGuard timeoutGuard;
    private final TraceIdGenerator traceIdGenerator;

    /** 第 6 课的权限策略。允许为 null：本课的重点是 Hook，不强制配权限。 */
    private final PermissionPolicy policy;

    /** 本课的主角。为 null 时用一个空注册表，全部事件都是空队列。 */
    private final HookRegistry hooks;

    public HookedAgentLoop(String model,
                           ModelClient client,
                           ToolRegistry registry,
                           ToolContext context,
                           int maxRounds,
                           long toolTimeoutMillis,
                           TraceIdGenerator traceIdGenerator,
                           PermissionPolicy policy,
                           HookRegistry hooks) {
        if (model == null || model.trim().isEmpty()) {
            throw new IllegalArgumentException("model 不能为空");
        }
        if (client == null) {
            throw new IllegalArgumentException("client 不能为空");
        }
        if (registry == null) {
            throw new IllegalArgumentException("registry 不能为空");
        }
        if (context == null) {
            throw new IllegalArgumentException("context 不能为空");
        }
        if (maxRounds <= 0) {
            throw new IllegalArgumentException("maxRounds 必须为正数");
        }
        if (traceIdGenerator == null) {
            throw new IllegalArgumentException("traceIdGenerator 不能为空");
        }
        this.model = model;
        this.client = client;
        this.registry = registry;
        this.context = context;
        this.maxRounds = maxRounds;
        this.timeoutGuard = new ToolTimeoutGuard(toolTimeoutMillis);
        this.traceIdGenerator = traceIdGenerator;
        this.policy = policy;
        this.hooks = hooks == null ? new HookRegistry() : hooks;
    }

    /**
     * 跑一次带 Hook 的循环。
     *
     * @throws HookContractException UserPromptSubmit 或 Stop 的回调违约/抛异常时
     */
    public GuardedTrace run(String systemPrompt, String userInput) {
        GuardedTrace trace = new GuardedTrace(traceIdGenerator.next());

        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system(systemPrompt));

        // UserPromptSubmit：在用户消息进历史之前。异常刻意不捕获。
        ChatMessage submitted = ChatMessage.user(userInput);
        HookResult promptHook = hooks.runUserPrompt(submitted);
        messages.add(submitted);
        messages.addAll(promptHook.getAdditionalContext());

        ToolCallMemo memo = new ToolCallMemo();
        boolean stopHookActive = false;

        for (int round = 1; round <= maxRounds; round++) {
            long modelStart = System.currentTimeMillis();
            ChatResponse response;
            try {
                response = client.chat(new ChatRequest(model, messages, 0.0, 1024));
            } catch (RuntimeException e) {
                long millis = System.currentTimeMillis() - modelStart;
                trace.addRound(new RoundTrace(round, "error", null, null, null,
                        e.getClass().getSimpleName(), millis, 0L, 0, 0));
                trace.finish(StopReason.MODEL_ERROR, "（模型调用失败：" + e.getMessage() + "）");
                return trace;
            }
            long modelMillis = System.currentTimeMillis() - modelStart;

            TokenUsage usage = response.getUsage();
            int promptTokens = usage == null ? 0 : usage.getPromptTokens();
            int completionTokens = usage == null ? 0 : usage.getCompletionTokens();
            String finishWire = wireOf(response.getFinishReason());

            if (response.getFinishReason() == FinishReason.LENGTH) {
                trace.addRound(new RoundTrace(round, finishWire, null, null, null, null,
                        modelMillis, 0L, promptTokens, completionTokens));
                trace.finish(StopReason.TRUNCATED, "（输出被截断，请缩短问题或提高 maxOutputTokens）");
                return trace;
            }

            if (response.getFinishReason() != FinishReason.TOOL_CALLS) {
                trace.addRound(new RoundTrace(round, finishWire, null, null, null, null,
                        modelMillis, 0L, promptTokens, completionTokens));

                // Stop：最后一次「其实还没完」的机会。异常刻意不捕获。
                HookResult stopHook = hooks.runStop(messages, stopHookActive);
                if (stopHook.getForceContinue() != null) {
                    messages.addAll(stopHook.getAdditionalContext());
                    messages.add(stopHook.getForceContinue());
                    // 置位之后，下一次 Stop 的续写请求会被注册表吞掉，
                    // 所以「无限续写」在机制上不可能，不靠 Hook 自律。
                    stopHookActive = true;
                    continue;
                }
                trace.finish(StopReason.FINAL_ANSWER, response.getContent());
                return trace;
            }

            ToolCall call = ToolCallCodec.decode(response.getContent());
            if (call == null) {
                trace.addRound(new RoundTrace(round, finishWire, null, null,
                        "protocol_violation", "missing_tool_calls",
                        modelMillis, 0L, promptTokens, completionTokens));
                trace.finish(StopReason.PROTOCOL_VIOLATION,
                        "（模型声明要调工具，但没有给出工具调用内容）");
                return trace;
            }

            messages.add(AgentMessage.assistantToolCall(call).toChatMessage());

            long toolStart = System.currentTimeMillis();
            Outcome outcome = executeWithHooks(call, memo);
            long toolMillis = System.currentTimeMillis() - toolStart;

            trace.addRound(new RoundTrace(round, finishWire, call.getName(), call.getId(),
                    outcome.label, outcome.result.isError() ? outcome.result.getErrorCode() : null,
                    modelMillis, toolMillis, promptTokens, completionTokens));
            if (outcome.decision != null) {
                trace.addDecision(outcome.decision);
            }

            messages.add(AgentMessage.toolResult(call.getId(), outcome.result.getContent())
                    .toChatMessage());
            messages.addAll(outcome.additionalContext);

            // PostToolUse 要求收手：不再跑下一轮，把当前结果当作结局。
            if (outcome.preventContinuation) {
                trace.finish(StopReason.FINAL_ANSWER, outcome.result.getContent());
                return trace;
            }
        }

        trace.finish(StopReason.MAX_ROUNDS,
                "（达到最大轮次 " + maxRounds + "，仍未得到最终答复）");
        return trace;
    }

    /**
     * 一次工具调用的完整链路。
     *
     * <pre>
     * prepare              零副作用，失败直接回传
     *   → PreToolUse       可改参数、可提权限建议、可直接拦下
     *   → 权限裁决          最终决定权在这里，Hook 的建议只是候选
     *   → 幂等缓存
     *   → 限时执行          唯一产生副作用的地方
     *   → PostToolUse      可改结果、可要求收手
     * </pre>
     */
    private Outcome executeWithHooks(ToolCall call, ToolCallMemo memo) {
        PreparedToolCall prepared = registry.prepare(call);
        if (prepared.isFailed()) {
            return Outcome.simple("rejected", prepared.getError());
        }

        // PreToolUse。异常捕获成工具错误：模型下一轮还有机会换做法。
        HookResult preHook;
        try {
            preHook = hooks.runPreTool(prepared);
        } catch (HookContractException e) {
            // 契约违反和执行异常分成两个错误码：前者是 Hook 写错了（改了工具名、
            // 参数没过校验），后者是 Hook 跑挂了。排查方向完全不同。
            return Outcome.simple("hook_contract_error", ToolExecutionResult.error(
                    "hook_contract_error", "PreToolUse Hook 返回了违反契约的更新"));
        } catch (Throwable e) {
            return Outcome.simple("hook_error", ToolExecutionResult.error(
                    "hook_execution_error", "PreToolUse Hook 执行失败"));
        }

        // 改过参数就用改过的那份 —— 注意它已经在注册表里过了三道锁并重新构造。
        PreparedToolCall effective =
                preHook.getUpdatedInput() == null ? prepared : preHook.getUpdatedInput();

        // Hook 直接拦下。这条不进权限裁决，也就不进审计：它不是一次权限决定。
        if (preHook.getBlockingError() != null) {
            return new Outcome("hook_blocked", preHook.getBlockingError(), null,
                    preHook.getAdditionalContext(), false);
        }

        PermissionDecision decision = null;
        if (policy != null) {
            try {
                decision = policy.decide(new PermissionRequest(effective, context,
                        recommendationsOf(preHook), null));
            } catch (RuntimeException e) {
                return new Outcome("policy_error", ToolExecutionResult.error(
                        "permission_evaluation_error", "权限评估失败，本次调用未执行"),
                        null, preHook.getAdditionalContext(), false);
            }
            if (!decision.getBehavior().isAllowed()) {
                return new Outcome("permission_denied", decision.toToolResult(), decision,
                        preHook.getAdditionalContext(), false);
            }
        }

        ToolExecutionResult result;
        ToolExecutionResult cached = memo.lookup(effective.getCall());
        String label;
        if (cached != null) {
            result = cached;
            label = "deduplicated";
        } else {
            result = timeoutGuard.invokeWithTimeout(registry, effective, context);
            memo.remember(effective.getCall(), result);
            label = result.isError() ? "failed" : "executed";
        }

        // PostToolUse。同样捕获异常。
        HookResult postHook;
        try {
            postHook = hooks.runPostTool(effective, result);
        } catch (Throwable e) {
            // 注意：工具<b>已经执行了</b>，副作用已经发生。所以这里不能假装
            // 什么都没发生，要如实回传「结果处理失败」，而不是丢掉结果。
            return new Outcome("hook_error", ToolExecutionResult.error(
                    "hook_execution_error", "PostToolUse Hook 执行失败，工具已执行但结果未能处理"),
                    decision, preHook.getAdditionalContext(), false);
        }

        ToolExecutionResult finalResult =
                postHook.getUpdatedOutput() == null ? result : postHook.getUpdatedOutput();

        List<ChatMessage> merged = new ArrayList<ChatMessage>(preHook.getAdditionalContext());
        merged.addAll(postHook.getAdditionalContext());

        return new Outcome(label, finalResult, decision, merged, postHook.isPreventContinuation());
    }

    /**
     * 把 Hook 的权限建议转成策略的候选。
     *
     * <p>{@code passthrough} 不生成候选：弃权不是意见，塞一条进去只会让审计里
     * 多一行「Hook 说随便」。</p>
     */
    private static List<PermissionDecision> recommendationsOf(HookResult hook) {
        if (hook.getPermissionBehavior() == learn.agent.llm.permission.PermissionBehavior.PASSTHROUGH) {
            return Collections.emptyList();
        }
        return Collections.singletonList(new PermissionDecision(
                hook.getPermissionBehavior(),
                "PreToolUse Hook 建议 " + hook.getPermissionBehavior().getWireValue(),
                "pre-tool-hook"));
    }

    private static String wireOf(FinishReason reason) {
        return reason == null ? "unknown" : reason.name().toLowerCase();
    }

    public void shutdown() {
        timeoutGuard.shutdown();
    }

    /** 一次工具调用的处置结果。 */
    private static final class Outcome {
        private final String label;
        private final ToolExecutionResult result;
        private final PermissionDecision decision;
        private final List<ChatMessage> additionalContext;
        private final boolean preventContinuation;

        private Outcome(String label,
                        ToolExecutionResult result,
                        PermissionDecision decision,
                        List<ChatMessage> additionalContext,
                        boolean preventContinuation) {
            this.label = label;
            this.result = result;
            this.decision = decision;
            this.additionalContext = additionalContext;
            this.preventContinuation = preventContinuation;
        }

        /** 没走到权限、也没有 Hook 上下文的处置结果。 */
        private static Outcome simple(String label, ToolExecutionResult result) {
            return new Outcome(label, result, null,
                    Collections.<ChatMessage>emptyList(), false);
        }
    }
}
