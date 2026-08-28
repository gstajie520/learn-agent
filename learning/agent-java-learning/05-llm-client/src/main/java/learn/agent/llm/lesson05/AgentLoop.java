package learn.agent.llm.lesson05;

import java.util.ArrayList;
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
import learn.agent.llm.lesson04.ToolDefinition;
import learn.agent.llm.lesson04.ToolExecutionResult;
import learn.agent.llm.lesson04.ToolRegistry;

/**
 * 手写的最小 Agent 循环：把第 4 课的一次往返扩展成一个带完整边界的循环。
 *
 * <p>路线图给的伪代码只有七行：</p>
 * <pre>{@code
 * messages = [system, user]
 * for round in 1..N:
 *     response = model(messages, tools)
 *     if 没有 tool_calls: return response
 *     for tool_call in response.tool_calls:
 *         result = execute_tool(tool_call)
 *         messages.add(tool_result)
 * return 超过最大轮次
 * }</pre>
 *
 * <p>这个类就是这七行，加上七行里没写、但少一条就会在生产出事的边界：</p>
 * <ul>
 *   <li><b>最大轮次</b>：模型可能永远不给最终答复，循环得有保险丝；</li>
 *   <li><b>工具白名单</b>：{@link ToolRegistry} 说了算，模型编的名字进不来；</li>
 *   <li><b>参数校验</b>：第 4 课的 {@code prepare} 负责，零副作用；</li>
 *   <li><b>工具超时</b>：{@link ToolTimeoutGuard}，工具卡住循环不能跟着卡住；</li>
 *   <li><b>异常回传</b>：工具报错变成 tool 消息回传，模型有机会改参数重试；</li>
 *   <li><b>重复调用幂等</b>：{@link ToolCallMemo}，同样的调用不重复产生副作用；</li>
 *   <li><b>每轮 trace</b>：{@link AgentTrace}，轮次、工具名、耗时、token 全记上。</li>
 * </ul>
 *
 * <p>和第 4 课 {@code ToolCallingService} 的关系：那个类演示「一次往返怎么闭环」，
 * 这个类演示「循环怎么在真实世界里不失控」。两个都保留，因为先看清骨架、
 * 再看清边界，比一上来就看一个塞满防御逻辑的类容易得多。</p>
 *
 * <p>本课回答阶段 7 的完成标准四问：</p>
 * <ul>
 *   <li><b>谁决定调用工具</b>：模型。它在响应里给出 finish_reason=tool_calls。</li>
 *   <li><b>谁真正执行工具</b>：程序。{@link ToolRegistry#invoke} 是唯一入口，
 *       而且破坏性工具连程序都不执行，要等人点头。</li>
 *   <li><b>工具结果如何回到模型</b>：以 TOOL 角色追加进消息列表，带原始 tool_call_id。</li>
 *   <li><b>什么时候结束</b>：见 {@link StopReason} 的五种情况。</li>
 * </ul>
 */
public class AgentLoop {

    /** 模型名，透传给 {@link ChatRequest}。 */
    private final String model;

    /** 模型客户端；测试注入 Fake，生产注入 HTTP 实现，本类不用改。 */
    private final ModelClient client;

    /** 工具白名单。模型只能调这里注册过的工具。 */
    private final ToolRegistry registry;

    /** 程序提供的受控环境，工具执行时从这里拿身份和场景。 */
    private final ToolContext context;

    /** 最大轮次，防止模型一直调工具不收尾。 */
    private final int maxRounds;

    /** 工具超时守卫。 */
    private final ToolTimeoutGuard timeoutGuard;

    /** trace id 生成器；构造时注入，测试里可以给一个固定值。 */
    private final TraceIdGenerator traceIdGenerator;

    public AgentLoop(String model,
                     ModelClient client,
                     ToolRegistry registry,
                     ToolContext context,
                     int maxRounds,
                     long toolTimeoutMillis,
                     TraceIdGenerator traceIdGenerator) {
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
    }

    /**
     * 跑一次完整的 Agent 循环。
     *
     * <p>返回 {@link AgentTrace} 而不是只返回答复文本：调用方既要拿到结果，
     * 也要能回答「为什么结束、跑了几轮、花了多少 token」。第 4 课只返回
     * String，那个签名没法回答后面三个问题。</p>
     *
     * @param systemPrompt 系统规则
     * @param userInput    用户输入
     * @return 本次运行的完整轨迹，含最终答复和结束原因
     */
    public AgentTrace run(String systemPrompt, String userInput) {
        AgentTrace trace = new AgentTrace(traceIdGenerator.next());

        // 消息列表是循环里唯一会变的状态。
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system(systemPrompt));
        messages.add(ChatMessage.user(userInput));

        // 幂等缓存的生命周期 == 一次 run。跨会话幂等要落 Redis，见 ToolCallMemo 的说明。
        ToolCallMemo memo = new ToolCallMemo();

        for (int round = 1; round <= maxRounds; round++) {
            long modelStart = System.currentTimeMillis();
            ChatResponse response;
            try {
                response = client.chat(new ChatRequest(model, messages, 0.0, 1024));
            } catch (RuntimeException e) {
                // 模型调用本身失败（重试耗尽、密钥错误等）。记一轮再终止，
                // 否则 trace 上会看不到「最后一轮到底发生了什么」。
                long millis = System.currentTimeMillis() - modelStart;
                trace.addRound(new RoundTrace(round, "error", null, null, null,
                        e.getClass().getSimpleName(), millis, 0L, 0, 0));
                String answer = "（模型调用失败：" + e.getMessage() + "）";
                trace.finish(StopReason.MODEL_ERROR, answer);
                return trace;
            }
            long modelMillis = System.currentTimeMillis() - modelStart;

            TokenUsage usage = response.getUsage();
            int promptTokens = usage == null ? 0 : usage.getPromptTokens();
            int completionTokens = usage == null ? 0 : usage.getCompletionTokens();
            String finishWire = wireOf(response.getFinishReason());

            // 截断：既没有完整答复也没有工具调用，继续循环只会重复同样的失败。
            if (response.getFinishReason() == FinishReason.LENGTH) {
                trace.addRound(new RoundTrace(round, finishWire, null, null, null, null,
                        modelMillis, 0L, promptTokens, completionTokens));
                String answer = "（输出被截断，请缩短问题或提高 maxOutputTokens）";
                trace.finish(StopReason.TRUNCATED, answer);
                return trace;
            }

            // 不是工具调用：这就是最终答复，循环正常结束。
            if (response.getFinishReason() != FinishReason.TOOL_CALLS) {
                trace.addRound(new RoundTrace(round, finishWire, null, null, null, null,
                        modelMillis, 0L, promptTokens, completionTokens));
                trace.finish(StopReason.FINAL_ANSWER, response.getContent());
                return trace;
            }

            // 模型要调工具。
            ToolCall call = ToolCallCodec.decode(response.getContent());
            if (call == null) {
                // 协议违约：声明了 tool_calls 却没给内容。不能当最终答复，也不能继续循环。
                trace.addRound(new RoundTrace(round, finishWire, null, null,
                        "protocol_violation", "missing_tool_calls",
                        modelMillis, 0L, promptTokens, completionTokens));
                String answer = "（模型声明要调工具，但没有给出工具调用内容）";
                trace.finish(StopReason.PROTOCOL_VIOLATION, answer);
                return trace;
            }

            // 模型的工具调用先原样记进消息列表，模型才知道自己上一轮说过什么。
            messages.add(AgentMessage.assistantToolCall(call).toChatMessage());

            long toolStart = System.currentTimeMillis();
            Outcome outcome = executeWithBoundaries(call, memo);
            long toolMillis = System.currentTimeMillis() - toolStart;

            trace.addRound(new RoundTrace(round, finishWire, call.getName(), call.getId(),
                    outcome.label, outcome.result.isError() ? outcome.result.getErrorCode() : null,
                    modelMillis, toolMillis, promptTokens, completionTokens));

            // 结果以 TOOL 角色回传，id 原样带回。成功还是失败都要回传 ——
            // 失败也是信息，模型据此才能改参数重试。
            messages.add(AgentMessage.toolResult(call.getId(), outcome.result.getContent())
                    .toChatMessage());
        }

        // 轮次耗尽：模型一直在调工具，始终没给最终答复。
        String answer = "（达到最大轮次 " + maxRounds + "，仍未得到最终答复）";
        trace.finish(StopReason.MAX_ROUNDS, answer);
        return trace;
    }

    /**
     * 一次工具调用要穿过的四道边界，顺序是刻意的。
     *
     * <ol>
     *   <li><b>prepare</b>：查白名单 + 解析参数 + 校验。零副作用。</li>
     *   <li><b>破坏性闸门</b>：不可逆操作不执行，只回传等待确认。
     *       放在幂等缓存<b>之前</b>，因为「不执行」这件事不需要缓存。</li>
     *   <li><b>幂等缓存</b>：同样的调用命中缓存，不重复产生副作用。</li>
     *   <li><b>超时执行</b>：唯一真正调 handler 的地方。</li>
     * </ol>
     */
    private Outcome executeWithBoundaries(ToolCall call, ToolCallMemo memo) {
        // 1) 白名单 + 参数校验。失败直接回传，绝不执行。
        PreparedToolCall prepared = registry.prepare(call);
        if (prepared.isFailed()) {
            return new Outcome("rejected", prepared.getError());
        }

        // 2) 破坏性闸门。模型能提请求，但程序不替人做决定。
        ToolDefinition definition = prepared.getDefinition();
        if (definition.getEffect().requiresConfirmation()) {
            return new Outcome("blocked_destructive", ToolExecutionResult.success(
                    "工具 " + definition.getName() + " 需要人工确认后才能执行，"
                            + "请向用户说明将要进行的操作并等待确认。"));
        }

        // 3) 幂等缓存。命中就直接返回上次的结果，不再执行。
        ToolExecutionResult cached = memo.lookup(call);
        if (cached != null) {
            return new Outcome("deduplicated", cached);
        }

        // 4) 带超时执行。这里是唯一会产生副作用的地方。
        ToolExecutionResult result = timeoutGuard.invokeWithTimeout(registry, prepared, context);
        memo.remember(call, result);
        return new Outcome(result.isError() ? "failed" : "executed", result);
    }

    /**
     * 把枚举转成日志里用的线值，null 归一成 unknown。
     *
     * <p>第 1 课的 {@link FinishReason} 是个不带字段的纯枚举，没有 wire 值访问器，
     * 所以这里用 {@code name()} 转小写。这么做有个隐含代价：以后给枚举改名，
     * 日志里的字符串会跟着变，历史日志就对不上了。第 3 课之后的枚举
     * （包括本课的 {@link StopReason}）都显式带一个 wireValue 字段，
     * 就是为了避免这件事。</p>
     */
    private static String wireOf(FinishReason reason) {
        return reason == null ? "unknown" : reason.name().toLowerCase();
    }

    /** 释放工具执行线程池。 */
    public void shutdown() {
        timeoutGuard.shutdown();
    }

    /** 一次工具执行的处置结果：怎么处理的 + 结果本身。 */
    private static final class Outcome {
        private final String label;
        private final ToolExecutionResult result;

        private Outcome(String label, ToolExecutionResult result) {
            this.label = label;
            this.result = result;
        }
    }
}
