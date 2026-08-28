package learn.agent.llm.lesson06;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.ChatRequest;
import learn.agent.llm.lesson01.ChatResponse;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.ModelClient;
import learn.agent.llm.lesson01.TokenUsage;
import learn.agent.llm.lesson04.AgentMessage;
import learn.agent.llm.lesson04.PreparedToolCall;
import learn.agent.llm.lesson04.ToolCall;
import learn.agent.llm.lesson04.ToolCallCodec;
import learn.agent.llm.lesson04.ToolContext;
import learn.agent.llm.lesson04.ToolExecutionResult;
import learn.agent.llm.lesson04.ToolRegistry;
import learn.agent.llm.lesson05.RoundTrace;
import learn.agent.llm.lesson05.StopReason;
import learn.agent.llm.lesson05.ToolCallMemo;
import learn.agent.llm.lesson05.ToolTimeoutGuard;
import learn.agent.llm.lesson05.TraceIdGenerator;

/**
 * 把权限裁决接进第 5 课的循环。
 *
 * <p>阶段 8 的完成标准是「<b>不修改 Loop 主体</b>就能给某个工具加一条必须人工
 * 确认的策略，并留下审计记录」。所以第 5 课的 {@code AgentLoop} 本课一行未改，
 * 权限走的是构造时注入的 {@link PermissionPolicy}。</p>
 *
 * <p><b>这里有一处必须如实说明的设计债。</b>第 5 课的 {@code AgentLoop} 把
 * {@code executeWithBoundaries} 写成了私有方法，四道边界硬编码在方法体里，
 * 字段也全是 {@code private final}。结果就是本课<b>没法复用它</b>——既不能继承
 * 覆盖那一个方法，也不能从外面替换某道边界，只能把循环骨架重写一遍。</p>
 *
 * <p>这不是「本课偷懒」，而是第 5 课的一个真实教训：<b>「不改主体就能扩展」
 * 是设计出来的，不是自然长出来的。</b>当时把四道边界写死在私有方法里，读起来
 * 最清楚（一个方法从上到下就是全部真相），代价是扩展点为零。真要消掉这笔债，
 * 该做的是把那个方法提成一个 {@code ToolGate} 接口、让边界变成可注入的列表——
 * 但那样第 5 课就得先引入一层抽象，而抽象在你还没见过第二个用例时是讲不清的。
 * 所以这里选择保留重复，把代价写在注释里，而不是回头给第 5 课加抽象。</p>
 *
 * <p>本课新增的那道闸门插在哪：</p>
 * <pre>
 * prepare（白名单+解析+校验，零副作用）
 *   → 【权限裁决】       ← 本课新增，取代第 5 课那个只看 ToolEffect 的破坏性闸门
 *   → 幂等缓存
 *   → 限时执行
 * </pre>
 *
 * <p>为什么它取代而不是叠加在破坏性闸门之上：第 5 课那道闸门只会看
 * {@code ToolEffect.requiresConfirmation()}，是一个写死的 if。本课的
 * {@link PermissionPolicy} 能表达同一件事（注册一条匹配 DESTRUCTIVE 的
 * {@code ask} 规则），还能表达它表达不了的事——按参数拦、按身份拦、
 * 硬边界不可翻盘、裁决留痕。两道叠着放，同一件事就有两个真相来源。</p>
 */
public class GuardedAgentLoop {

    /** 模型名，透传给 {@link ChatRequest}。 */
    private final String model;

    /** 模型客户端。 */
    private final ModelClient client;

    /** 工具白名单。 */
    private final ToolRegistry registry;

    /** 程序提供的受控环境。 */
    private final ToolContext context;

    /** 最大轮次。 */
    private final int maxRounds;

    /** 工具超时守卫。 */
    private final ToolTimeoutGuard timeoutGuard;

    /** trace id 生成器。 */
    private final TraceIdGenerator traceIdGenerator;

    /** 权限策略。本课的主角，构造时注入。 */
    private final PermissionPolicy policy;

    public GuardedAgentLoop(String model,
                            ModelClient client,
                            ToolRegistry registry,
                            ToolContext context,
                            int maxRounds,
                            long toolTimeoutMillis,
                            TraceIdGenerator traceIdGenerator,
                            PermissionPolicy policy) {
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
        if (policy == null) {
            throw new IllegalArgumentException("policy 不能为空，没有策略就不该用这个类（用第 5 课的 AgentLoop）");
        }
        this.model = model;
        this.client = client;
        this.registry = registry;
        this.context = context;
        this.maxRounds = maxRounds;
        this.timeoutGuard = new ToolTimeoutGuard(toolTimeoutMillis);
        this.traceIdGenerator = traceIdGenerator;
        this.policy = policy;
    }

    /**
     * 跑一次带权限裁决的循环。
     *
     * <p>返回 {@link GuardedTrace}：字段和第 5 课的 {@code AgentTrace} 一致，
     * 额外带上本次运行的全部权限裁决，供审计断言。</p>
     */
    public GuardedTrace run(String systemPrompt, String userInput) {
        GuardedTrace trace = new GuardedTrace(traceIdGenerator.next());

        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system(systemPrompt));
        messages.add(ChatMessage.user(userInput));

        ToolCallMemo memo = new ToolCallMemo();

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
            Outcome outcome = executeWithBoundaries(call, memo);
            long toolMillis = System.currentTimeMillis() - toolStart;

            trace.addRound(new RoundTrace(round, finishWire, call.getName(), call.getId(),
                    outcome.label, outcome.result.isError() ? outcome.result.getErrorCode() : null,
                    modelMillis, toolMillis, promptTokens, completionTokens));
            if (outcome.decision != null) {
                trace.addDecision(outcome.decision);
            }

            messages.add(AgentMessage.toolResult(call.getId(), outcome.result.getContent())
                    .toChatMessage());
        }

        trace.finish(StopReason.MAX_ROUNDS,
                "（达到最大轮次 " + maxRounds + "，仍未得到最终答复）");
        return trace;
    }

    /**
     * 四道边界，第二道换成了权限裁决。
     *
     * <p>顺序仍然是刻意的：<b>裁决必须在幂等缓存之前</b>。理由和第 5 课把破坏性
     * 闸门放在缓存前是同一条——「没有执行」这件事不需要缓存。反过来如果先查缓存，
     * 一次被批准过的调用就会绕过后续所有裁决，权限等于只在第一次生效。</p>
     */
    private Outcome executeWithBoundaries(ToolCall call, ToolCallMemo memo) {
        // 1) 白名单 + 参数校验。prepare 失败连策略都不用问，因为没有合法的
        //    definition/arguments 可供裁决，也就不该进审计。
        PreparedToolCall prepared = registry.prepare(call);
        if (prepared.isFailed()) {
            return Outcome.withoutDecision("rejected", prepared.getError());
        }

        // 2) 权限裁决。本课新增的闸门。
        PermissionDecision decision;
        try {
            decision = policy.decide(new PermissionRequest(prepared, context,
                    Collections.<PermissionDecision>emptyList(), null));
        } catch (RuntimeException e) {
            // 审计失败会走到这里。审计是闸门不是日志：留痕失败就等于
            // 「决定没留下记录，副作用却发生了」，所以宁可不执行。
            //
            // 这里也不往 trace 里记裁决：policy.decide 抛异常意味着它没能产出一个
            // 可信的决定，编一个假的进 trace 只会让审计更难读。
            return Outcome.withoutDecision("policy_error", ToolExecutionResult.error(
                    "permission_evaluation_error", "权限评估失败，本次调用未执行"));
        }

        if (!decision.getBehavior().isAllowed()) {
            // deny：转成工具错误回传。模型据此向用户解释，而不是以为自己执行了。
            return new Outcome("permission_denied", decision.toToolResult(), decision);
        }

        // 3) 幂等缓存。
        ToolExecutionResult cached = memo.lookup(call);
        if (cached != null) {
            return new Outcome("deduplicated", cached, decision);
        }

        // 4) 带超时执行。唯一产生副作用的地方。
        ToolExecutionResult result = timeoutGuard.invokeWithTimeout(registry, prepared, context);
        memo.remember(call, result);
        return new Outcome(result.isError() ? "failed" : "executed", result, decision);
    }

    /** 同第 5 课：{@code FinishReason} 是纯枚举，没有 wire 值访问器。 */
    private static String wireOf(FinishReason reason) {
        return reason == null ? "unknown" : reason.name().toLowerCase();
    }

    /** 释放工具执行线程池。 */
    public void shutdown() {
        timeoutGuard.shutdown();
    }

    /**
     * 一次工具执行的处置结果。
     *
     * <p>{@code decision} 可以为 null：参数校验就失败的调用压根没走到权限，
     * 此时「没有裁决」和「裁决为放行」必须能区分开，所以用 null 而不是塞一个
     * 假的 allow 进去。</p>
     */
    private static final class Outcome {
        private final String label;
        private final ToolExecutionResult result;
        private final PermissionDecision decision;

        private Outcome(String label, ToolExecutionResult result, PermissionDecision decision) {
            this.label = label;
            this.result = result;
            this.decision = decision;
        }

        /** 没走到权限裁决的处置结果。 */
        private static Outcome withoutDecision(String label, ToolExecutionResult result) {
            return new Outcome(label, result, null);
        }
    }
}
