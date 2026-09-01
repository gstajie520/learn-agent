package learn.agent.llm.hook;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.loop.RoundTrace;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.GuardedTrace;
import learn.agent.llm.structured.DeviceType;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolCallCodec;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;
import learn.agent.llm.tool.ToolRegistry;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 取证用探针：幂等键算的是模型原始参数，缓存的值却是 Hook 改过参数跑出来的结果。
 *
 * <p>{@code HookedAgentLoop} 用 {@code effective.getCall()} 查缓存，而
 * {@code HookRegistry} 规范化 updatedInput 时保留的是<b>模型原始的那个</b>
 * {@code ToolCall}（连带它的 rawArguments），{@code ToolCallMemo.keyOf} 又只看
 * 「工具名 + rawArguments」。两条测试分别打这个错位的两个方向。</p>
 */
public class MemoKeyFollowsEffectiveArgumentsTest {

    /** handler 每次实际看到的 limit，按执行顺序记录。 */
    private final List<Integer> executedLimits = new ArrayList<Integer>();

    /**
     * 原始参数相同、Hook 改成不同值时，第二次不能吃第一次的缓存。
     *
     * <p>这是危险的那个方向：真正被裁决、被执行的是 Hook 改过的参数，但幂等键
     * 记的是模型原文。原文相同就命中缓存，于是「批准 limit=20」拿回的是
     * 「limit=10 跑出来的结果」—— 缓存版的「批准 A、执行 B」。</p>
     */
    @Test
    public void shouldNotServeCachedResultWhenHookRewritesArgumentsDifferently() {
        // 两轮的原始参数完全一样，Hook 按调用次序改成 10、20。
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            private int calls = 0;

            @Override
            public HookResult handle(HookContext context) {
                calls++;
                PreparedToolCall original = context.getPrepared();
                ObjectNode rewritten = JsonNodeFactory.instance.objectNode();
                rewritten.put("limit", calls * 10);
                return HookResult.builder()
                        .updatedInput(PreparedToolCall.ready(
                                original.getCall(), original.getDefinition(), rewritten))
                        .build();
            }
        });

        FakeModelClient client = new FakeModelClient();
        enqueueCall(client, "call-1", "{\"limit\":1}");
        enqueueCall(client, "call-2", "{\"limit\":1}");
        client.enqueueResponse("看完了", FinishReason.STOP, new TokenUsage(10, 5));

        GuardedTrace trace = run(client, hooks);

        assertEquals(Arrays.asList(10, 20), executedLimits,
                "Hook 改出来的两份参数不同，两次都该真执行；实际执行序列：" + executedLimits);
        assertEquals(Arrays.asList("executed", "executed"), toolOutcomesOf(trace),
                "第二轮不该被判成 deduplicated：它的有效参数和第一轮不同");
    }

    /**
     * 原始参数不同、Hook 收敛成同一份时，第二次应当命中缓存。
     *
     * <p>反方向：幂等键既然算的是模型原文，Hook 把两份不同的原文收敛成同一份
     * 有效参数之后，缓存就失效了 —— 同一个副作用会落两次。这正是
     * {@code ToolCallMemo} 存在的理由所要挡住的那件事。</p>
     */
    @Test
    public void shouldDeduplicateWhenHookNormalizesArgumentsToTheSameValue() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                PreparedToolCall original = context.getPrepared();
                ObjectNode clamped = JsonNodeFactory.instance.objectNode();
                clamped.put("limit", 10);
                return HookResult.builder()
                        .updatedInput(PreparedToolCall.ready(
                                original.getCall(), original.getDefinition(), clamped))
                        .build();
            }
        });

        FakeModelClient client = new FakeModelClient();
        enqueueCall(client, "call-1", "{\"limit\":100}");
        enqueueCall(client, "call-2", "{\"limit\":999}");
        client.enqueueResponse("看完了", FinishReason.STOP, new TokenUsage(10, 5));

        GuardedTrace trace = run(client, hooks);

        assertEquals(Arrays.asList(10), executedLimits,
                "两轮的有效参数都是 limit=10，只该真执行一次；实际执行序列：" + executedLimits);
        assertEquals(Arrays.asList("executed", "deduplicated"), toolOutcomesOf(trace),
                "第二轮该命中缓存");
    }

    // ---------- 脚手架 ----------

    private static void enqueueCall(FakeModelClient client, String id, String rawArguments) {
        client.enqueueResponse(
                ToolCallCodec.encode(new ToolCall(id, "read_device", rawArguments)),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
    }

    private ToolDefinition readTool() {
        return new ToolDefinition("read_device", "查设备", "{\"type\":\"object\"}",
                ToolEffect.READ, new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        int limit = arguments.get("limit").asInt();
                        executedLimits.add(limit);
                        return ToolExecutionResult.success("读到了 limit=" + limit);
                    }
                });
    }

    private GuardedTrace run(FakeModelClient client, HookRegistry hooks) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(readTool());
        HookedAgentLoop loop = new HookedAgentLoop("fake-model", client, registry,
                context(), 5, 2000L, TraceIdGenerator.fixed("trace-probe-b"), null, hooks);
        try {
            return loop.run("你是设备助手", "检查设备");
        } finally {
            loop.shutdown();
        }
    }

    private static List<String> toolOutcomesOf(GuardedTrace trace) {
        List<String> outcomes = new ArrayList<String>();
        for (RoundTrace round : trace.getRounds()) {
            if (round.hasToolCall()) {
                outcomes.add(round.getToolOutcome());
            }
        }
        return outcomes;
    }

    private static ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        return new ToolContext("operator-1", new SceneSnapshot(20, 20, 10, devices));
    }
}
