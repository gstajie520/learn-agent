package learn.agent.llm.loop;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.ModelException;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.structured.DeviceType;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolCallCodec;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;
import learn.agent.llm.tool.ToolRegistry;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link AgentLoop} 的测试：循环的终止条件、四道工具边界、以及每轮的 trace 记录。
 *
 * <p>第 4 课已经证明了「模型请求 → 程序执行 → 结果回传」这个闭环。本课新增三件事，
 * 测试重点也在这三件事上：工具超时、重复调用幂等、trace id 与每轮结构化记录。</p>
 */
public class AgentLoopTest {

    /** 记录被调用次数的只读工具。 */
    private static final class CountingHandler implements ToolHandler {
        int callCount = 0;

        @Override
        public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
            callCount++;
            return ToolExecutionResult.success("设备列表：cam-01");
        }
    }

    /** 睡固定时长的工具，用来触发超时。 */
    private static final class SleepingHandler implements ToolHandler {
        private final long sleepMillis;

        private SleepingHandler(long sleepMillis) {
            this.sleepMillis = sleepMillis;
        }

        @Override
        public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
            try {
                Thread.sleep(sleepMillis);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            return ToolExecutionResult.success("终于返回了");
        }
    }

    private ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        return new ToolContext("test-user", new SceneSnapshot(20, 20, 5, devices));
    }

    private ToolRegistry registryWith(ToolHandler listHandler) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, listHandler));
        registry.register(new ToolDefinition(
                "delete_device", "删除设备", "{}", ToolEffect.DESTRUCTIVE,
                new CountingHandler()));
        return registry;
    }

    private AgentLoop loopOf(FakeModelClient fake, ToolRegistry registry,
                             int maxRounds, long toolTimeoutMillis) {
        return new AgentLoop("deepseek-v4-flash", fake, registry, context(),
                maxRounds, toolTimeoutMillis, TraceIdGenerator.fixed("trace-001"));
    }

    /** 一次完整往返：模型调工具，程序执行，结果回传，模型据此给最终答复。 */
    @Test
    public void shouldCompleteFullRoundTrip() {
        CountingHandler handler = new CountingHandler();
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("场景里有 1 台摄像头 cam-01。",
                FinishReason.STOP, new TokenUsage(150, 30));

        AgentTrace trace = loopOf(fake, registryWith(handler), 5, 1000L)
                .run("你是场景管理助手", "看看有哪些设备");

        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
        assertEquals("场景里有 1 台摄像头 cam-01。", trace.getFinalAnswer());
        assertEquals(2, trace.getRoundCount(), "一次工具调用 + 一次最终答复 = 2 轮");
        assertEquals(1, handler.callCount);
    }

    /** trace id 贯穿整次运行，每轮都有一条记录，token 按轮累加。 */
    @Test
    public void shouldRecordTraceForEveryRound() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("好了。", FinishReason.STOP, new TokenUsage(150, 30));

        AgentTrace trace = loopOf(fake, registryWith(new CountingHandler()), 5, 1000L)
                .run("你是助手", "看看设备");

        assertEquals("trace-001", trace.getTraceId());
        assertEquals(300, trace.getTotalTokens(), "100+20+150+30");

        RoundTrace first = trace.getRounds().get(0);
        assertEquals(1, first.getRound(), "轮次从 1 开始，和人读日志的习惯一致");
        assertEquals("list_devices", first.getToolName());
        assertEquals("call-1", first.getToolCallId());
        assertEquals("executed", first.getToolOutcome());
        assertNull(first.getErrorCode());

        RoundTrace second = trace.getRounds().get(1);
        assertFalse(second.hasToolCall(), "最终答复那一轮不调工具");
    }

    /** 工具卡住时循环不跟着卡死，返回 tool_timeout 并继续把结果回传给模型。 */
    @Test
    public void shouldTimeOutSlowTool() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ,
                new SleepingHandler(2000L)));

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("工具超时了，请稍后再试。",
                FinishReason.STOP, new TokenUsage(150, 30));

        AgentLoop loop = loopOf(fake, registry, 5, 100L);
        AgentTrace trace = loop.run("你是助手", "看看设备");
        loop.shutdown();

        assertEquals("tool_timeout", trace.getRounds().get(0).getErrorCode());
        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason(),
                "超时是工具的失败，不是循环的失败：结果回传后模型仍能收尾");
    }

    /** 相同工具名 + 相同参数只真正执行一次，第二次命中幂等缓存。 */
    @Test
    public void shouldDeduplicateRepeatedToolCall() {
        CountingHandler handler = new CountingHandler();
        FakeModelClient fake = new FakeModelClient();
        // 模型连着两轮请求同一个工具、同样的参数，只有 tool_call_id 不同。
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-2", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 20));
        fake.enqueueResponse("场景里有 1 台摄像头。",
                FinishReason.STOP, new TokenUsage(150, 30));

        AgentTrace trace = loopOf(fake, registryWith(handler), 5, 1000L)
                .run("你是助手", "看看设备");

        assertEquals(1, handler.callCount, "同样的调用只应真正执行一次");
        assertEquals("executed", trace.getRounds().get(0).getToolOutcome());
        assertEquals("deduplicated", trace.getRounds().get(1).getToolOutcome());
    }

    /** 破坏性工具不执行，只回传等待确认，且这个处置被记进 trace。 */
    @Test
    public void shouldBlockDestructiveTool() {
        CountingHandler handler = new CountingHandler();
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "delete_device", "{\"id\":\"cam-01\"}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("删除 cam-01 是不可逆操作，请确认。",
                FinishReason.STOP, new TokenUsage(150, 30));

        AgentTrace trace = loopOf(fake, registryWith(handler), 5, 1000L)
                .run("你是助手", "删掉 cam-01");

        assertEquals("blocked_destructive", trace.getRounds().get(0).getToolOutcome());
        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
    }

    /** 未注册的工具名被白名单拦下，错误回传后模型可以改口。 */
    @Test
    public void shouldRejectToolOutsideWhitelist() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "drop_database", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("没有这个工具，我只能列出设备。",
                FinishReason.STOP, new TokenUsage(150, 30));

        AgentTrace trace = loopOf(fake, registryWith(new CountingHandler()), 5, 1000L)
                .run("你是助手", "删库");

        assertEquals("rejected", trace.getRounds().get(0).getToolOutcome());
        assertEquals("tool_not_found", trace.getRounds().get(0).getErrorCode());
    }

    /** 轮次上限是保险丝：耗尽后立刻停止，不再调用模型。 */
    @Test
    public void shouldStopAtMaxRounds() {
        FakeModelClient fake = new FakeModelClient();
        for (int i = 0; i < 3; i++) {
            // 每轮换一个参数，避免命中幂等缓存，确保测的是轮次上限本身。
            fake.enqueueResponse(
                    ToolCallCodec.encode(
                            new ToolCall("call-" + i, "list_devices", "{\"page\":" + i + "}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        }

        AgentTrace trace = loopOf(fake, registryWith(new CountingHandler()), 3, 1000L)
                .run("你是助手", "看看设备");

        assertEquals(StopReason.MAX_ROUNDS, trace.getStopReason());
        assertEquals(3, fake.getCallCount(), "达到上限后不应再调用模型");
        assertTrue(trace.getStopReason().isAbnormal(), "轮次耗尽属于非正常结束，应可被告警");
    }

    /** 输出被截断时如实终止，不继续循环重复同样的失败。 */
    @Test
    public void shouldStopOnTruncation() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("我正在查", FinishReason.LENGTH, new TokenUsage(100, 1024));

        AgentTrace trace = loopOf(fake, registryWith(new CountingHandler()), 5, 1000L)
                .run("你是助手", "写一篇长报告");

        assertEquals(StopReason.TRUNCATED, trace.getStopReason());
        assertEquals(1, fake.getCallCount());
    }

    /** 模型声明要调工具却没给出调用内容，按协议违约终止而不是当成最终答复。 */
    @Test
    public void shouldStopOnProtocolViolation() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("我要调工具了", FinishReason.TOOL_CALLS, new TokenUsage(100, 20));

        AgentTrace trace = loopOf(fake, registryWith(new CountingHandler()), 5, 1000L)
                .run("你是助手", "看看设备");

        assertEquals(StopReason.PROTOCOL_VIOLATION, trace.getStopReason());
        assertEquals("missing_tool_calls", trace.getRounds().get(0).getErrorCode());
    }

    /** 模型调用本身失败时仍记下这一轮，否则 trace 上看不到最后发生了什么。 */
    @Test
    public void shouldRecordRoundWhenModelCallFails() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueError(ModelException.ErrorType.AUTHENTICATION, "密钥无效");

        AgentTrace trace = loopOf(fake, registryWith(new CountingHandler()), 5, 1000L)
                .run("你是助手", "看看设备");

        assertEquals(StopReason.MODEL_ERROR, trace.getStopReason());
        assertEquals(1, trace.getRoundCount(), "失败那一轮也要留下记录");
        assertEquals("error", trace.getRounds().get(0).getFinishReason());
    }
}
