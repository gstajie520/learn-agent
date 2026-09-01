package learn.agent.llm.hook;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.loop.AgentLoop;
import learn.agent.llm.loop.AgentTrace;
import learn.agent.llm.loop.RoundTrace;
import learn.agent.llm.loop.StopReason;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.GuardedAgentLoop;
import learn.agent.llm.permission.GuardedTrace;
import learn.agent.llm.permission.PermissionPolicy;
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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 三个循环之间的<b>行为一致性</b>测试。
 *
 * <h3>这个测试类为什么存在</h3>
 * <p>阶段 7、8 各写了一个循环骨架（{@link AgentLoop}、{@link GuardedAgentLoop}、
 * {@link HookedAgentLoop}），后两个是从前一个复制出来再加能力的。复制的代价不是
 * 「代码重复」这种审美问题，而是<b>下游那份可能悄悄漏掉上游的一道边界</b> ——
 * 加新能力时注意力都在新能力上，没人会重新检查旧闸门还在不在。</p>
 *
 * <p>这正是真实发生过的事：{@code HookedAgentLoop} 复制骨架时整块漏掉了破坏性
 * 闸门（连 {@code ToolEffect} 都不在 import 列表里），于是「接了 Hook 和权限的
 * 循环」在不配策略时，对不可逆操作的防护<b>比最原始的 AgentLoop 还弱</b> ——
 * 而恰恰是这种循环最容易让人以为防护更强。三个循环各自的单测都是绿的，
 * 因为<b>没有任何一个测试同时看着三份</b>。</p>
 *
 * <p>所以这里把「无论加了什么能力都必须成立」的规则抽出来，对每个循环各跑一遍。
 * 它的价值不在于覆盖率，而在于<b>第四次复制骨架时会立刻红</b>。比消掉那 120 行
 * 重复更划算：重复本身不伤人，重复之后的静默分叉才伤人。</p>
 *
 * <h3>为什么不是参数化测试</h3>
 * <p>三个循环的构造签名和返回类型都不同（{@code AgentTrace} 与
 * {@code GuardedTrace} 没有共同父类）。用 {@link Loop} 这个小适配接口把差异
 * 收在一处，比给三个类硬造一个继承关系更诚实 —— 它们确实不是一个类型，
 * 只是<b>必须遵守同一组规则</b>。</p>
 */
public class LoopBehaviorParityTest {

    /** 一次运行的归一化结果，抹掉两种 trace 的类型差异。 */
    private static final class Run {
        final StopReason stopReason;
        final List<RoundTrace> rounds;

        Run(StopReason stopReason, List<RoundTrace> rounds) {
            this.stopReason = stopReason;
            this.rounds = rounds;
        }

        /** @return 第一轮的工具结局，没有工具轮时返回 null */
        String firstToolOutcome() {
            for (RoundTrace round : rounds) {
                if (round.hasToolCall()) {
                    return round.getToolOutcome();
                }
            }
            return null;
        }
    }

    /** 被测循环的适配器：把「怎么构造、怎么跑、怎么关」收在一个 lambda 里。 */
    private interface Loop {
        Run run(FakeModelClient client, ToolRegistry registry, ToolContext context);
    }

    /** 场景：20x20，上限 5，cam-01 受保护。 */
    private static SceneSnapshot scene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-01", DeviceType.RADAR);
        devices.put("cam-01", DeviceType.CAMERA);
        return new SceneSnapshot(20, 20, 5, devices, Collections.singleton("cam-01"));
    }

    private static ToolContext context() {
        return new ToolContext("parity-user", scene());
    }

    // ---------- 三个被测循环 ----------

    /** 阶段 7 的循环：没有权限系统，破坏性闸门是硬编码的。 */
    private static Loop agentLoop() {
        return (client, registry, context) -> {
            AgentLoop loop = new AgentLoop("m", client, registry, context,
                    5, 2000L, TraceIdGenerator.fixed("parity"));
            try {
                AgentTrace trace = loop.run("你是助手", "处理一下");
                return new Run(trace.getStopReason(), trace.getRounds());
            } finally {
                loop.shutdown();
            }
        };
    }

    /** 阶段 8 的带 Hook 循环，<b>刻意不配策略</b> —— 这是回归发生的那条路径。 */
    private static Loop hookedLoopWithoutPolicy() {
        return (client, registry, context) -> {
            HookedAgentLoop loop = new HookedAgentLoop("m", client, registry, context,
                    5, 2000L, TraceIdGenerator.fixed("parity"), null, new HookRegistry());
            try {
                GuardedTrace trace = loop.run("你是助手", "处理一下");
                return new Run(trace.getStopReason(), trace.getRounds());
            } finally {
                loop.shutdown();
            }
        };
    }

    /**
     * 阶段 8 的带权限循环，配一份<b>空策略</b>。
     *
     * <p>空策略不等于没有策略：{@code PermissionPolicy} 仍然会跑完整裁决，
     * `DESTRUCTIVE` 默认 ask、没有审批器则 fail-closed 成 deny。这正是
     * 「空实例」和「null」的区别所在。</p>
     */
    private static Loop guardedLoopWithEmptyPolicy() {
        return (client, registry, context) -> {
            GuardedAgentLoop loop = new GuardedAgentLoop("m", client, registry, context,
                    5, 2000L, TraceIdGenerator.fixed("parity"), new PermissionPolicy());
            try {
                GuardedTrace trace = loop.run("你是助手", "处理一下");
                return new Run(trace.getStopReason(), trace.getRounds());
            } finally {
                loop.shutdown();
            }
        };
    }

    /**
     * <b>全部三个循环</b>，各自配上「最低限度但合法」的配置。
     *
     * <p>这是本类的主力集合：凡是「无论加了什么能力都必须成立」的规则，
     * 都要对这三个各跑一遍。早先这里只有两个循环，于是
     * {@code GuardedAgentLoop} 的白名单和只读放行<b>根本没被覆盖</b> ——
     * 那两条在它里面漂移了，这个测试也不会红。</p>
     */
    private static Map<String, Loop> allLoops() {
        Map<String, Loop> loops = new LinkedHashMap<String, Loop>();
        loops.put("AgentLoop", agentLoop());
        loops.put("GuardedAgentLoop(空策略)", guardedLoopWithEmptyPolicy());
        loops.put("HookedAgentLoop(policy=null)", hookedLoopWithoutPolicy());
        return loops;
    }

    // ---------- 不变量 ----------

    /**
     * 规则：<b>没配权限策略时，破坏性工具一律不执行。</b>
     *
     * <p>这是本类的头号命题，也是真实回归过的那一条。策略为 null 表示
     * 「这个示例不演示权限系统」，<b>不表示</b>「不可逆操作可以随便执行」。</p>
     *
     * <p>违反会怎样：模型一句话就能让 handler 落下不可逆副作用，而且是在
     * 「看起来防护更完整」的那个循环里。这种错不会抛异常、不会留审计，
     * 只会安静地把设备删掉。</p>
     */
    @Test
    @DisplayName("一致性：没有明确授权时，破坏性工具在每个循环里都不执行")
    void shouldBlockDestructiveToolInEveryLoop() {
        for (Map.Entry<String, Loop> entry : allLoops().entrySet()) {
            String name = entry.getKey();
            List<String> sideEffects = new ArrayList<String>();

            Run run = entry.getValue().run(
                    modelCallsDeleteThenAnswers(),
                    registryWith(destructiveTool(sideEffects)),
                    context());

            // 唯一真正通用的不变量：handler 没跑，副作用没落地。
            assertTrue(sideEffects.isEmpty(),
                    name + "：破坏性 handler 不该执行，实际产生副作用 " + sideEffects);

            // 结局标签按设计就不同，不能强求一致：
            //   AgentLoop / HookedAgentLoop(无策略) 走硬编码兜底闸门 → blocked_destructive
            //   GuardedAgentLoop(空策略) 走裁决，DESTRUCTIVE 默认 ask、
            //     无审批器 fail-closed 成 deny                    → permission_denied
            // 断言「属于这两者之一」，既保住不变量、又不假装三份实现相同。
            String outcome = run.firstToolOutcome();
            assertTrue("blocked_destructive".equals(outcome) || "permission_denied".equals(outcome),
                    name + "：结局应当是 blocked_destructive 或 permission_denied，实际：" + outcome);
        }
    }

    /**
     * 规则：只读工具在每个循环里都<b>正常执行</b>。
     *
     * <p>和上一条成对。少了这条，「把所有工具都拦下」也能让上一条变绿，
     * 那样闸门就从安全措施退化成了功能残废。</p>
     */
    @Test
    @DisplayName("一致性：只读工具在每个循环里都正常执行")
    void shouldExecuteReadToolInEveryLoop() {
        for (Map.Entry<String, Loop> entry : allLoops().entrySet()) {
            String name = entry.getKey();
            List<String> calls = new ArrayList<String>();

            Run run = entry.getValue().run(
                    modelCallsInspectThenAnswers(),
                    registryWith(readTool(calls)),
                    context());

            assertEquals(Collections.singletonList("inspect"), calls,
                    name + "：只读工具应当执行且只执行一次");
            assertEquals("executed", run.firstToolOutcome(),
                    name + "：只读工具的结局应当是 executed");
            assertEquals(StopReason.FINAL_ANSWER, run.stopReason, name + "：应当正常收尾");
        }
    }

    /**
     * 规则：模型编造的工具名在每个循环里都回 {@code tool_not_found}，且不执行任何 handler。
     *
     * <p>模型完全有能力返回一个从没注册过的名字。这条保证白名单在三份骨架里
     * 都还在 —— 它和破坏性闸门一样属于「复制时容易漏掉」的那类边界。</p>
     */
    @Test
    @DisplayName("一致性：未注册的工具名在每个循环里都被白名单拦下")
    void shouldRejectUnknownToolInEveryLoop() {
        for (Map.Entry<String, Loop> entry : allLoops().entrySet()) {
            String name = entry.getKey();
            List<String> calls = new ArrayList<String>();

            FakeModelClient client = new FakeModelClient();
            client.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall("c1", "no_such_tool", "{}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(10, 5));
            client.enqueueResponse("那我换个办法。", FinishReason.STOP, new TokenUsage(10, 5));

            Run run = entry.getValue().run(client, registryWith(readTool(calls)), context());

            assertTrue(calls.isEmpty(), name + "：白名单外的调用不该碰到任何 handler");
            assertEquals("rejected", run.firstToolOutcome(),
                    name + "：未注册工具的结局应当是 rejected");
        }
    }

    /**
     * 规则：{@code GuardedAgentLoop} <b>不接受</b> null 策略。
     *
     * <p>它和上面两个循环走的是相反的路线：与其在运行期兜底，不如在构造期就说清
     * 「没有策略就别用这个类」。两种做法都可以，<b>但必须二者之一</b> ——
     * 既不在构造期拦、又不在运行期兜底，才是真正的漏洞。</p>
     */
    @Test
    @DisplayName("一致性：GuardedAgentLoop 用构造期拒绝代替运行期兜底")
    void shouldRejectNullPolicyAtConstructionForGuardedLoop() {
        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
                () -> new GuardedAgentLoop("m", new FakeModelClient(),
                        registryWith(readTool(new ArrayList<String>())), context(),
                        5, 2000L, TraceIdGenerator.fixed("parity"), null));
        assertTrue(e.getMessage().contains("policy"),
                "异常信息应当点明是 policy 的问题，实际：" + e.getMessage());
    }

    // ---------- 脚手架 ----------

    private static ToolRegistry registryWith(ToolDefinition definition) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(definition);
        return registry;
    }

    /** 一个不可逆工具；执行了就会往 sideEffects 里留下痕迹。 */
    private static ToolDefinition destructiveTool(final List<String> sideEffects) {
        return new ToolDefinition("delete_device", "删除设备（不可逆）",
                "{\"type\":\"object\"}", ToolEffect.DESTRUCTIVE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        sideEffects.add("deleted");
                        return ToolExecutionResult.success("已删除");
                    }
                });
    }

    /** 一个只读工具；执行了就把调用记进 calls。 */
    private static ToolDefinition readTool(final List<String> calls) {
        return new ToolDefinition("inspect", "查看设备",
                "{\"type\":\"object\"}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        calls.add("inspect");
                        return ToolExecutionResult.success("radar-01 在线");
                    }
                });
    }

    private static FakeModelClient modelCallsDeleteThenAnswers() {
        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("c1", "delete_device", "{\"deviceId\":\"radar-01\"}")),
                FinishReason.TOOL_CALLS, new TokenUsage(10, 5));
        client.enqueueResponse("好的，我不删了。", FinishReason.STOP, new TokenUsage(10, 5));
        return client;
    }

    private static FakeModelClient modelCallsInspectThenAnswers() {
        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("c1", "inspect", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(10, 5));
        client.enqueueResponse("radar-01 在线。", FinishReason.STOP, new TokenUsage(10, 5));
        return client;
    }
}
