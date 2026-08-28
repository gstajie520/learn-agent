package learn.agent.llm.permission;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
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
import learn.agent.llm.loop.RoundTrace;
import learn.agent.llm.loop.StopReason;
import learn.agent.llm.loop.TraceIdGenerator;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link GuardedAgentLoop} 的测试：权限闸门在循环里的实际效果。
 *
 * <p>阶段 8 的完成标准是「不修改 Loop 主体就能给某个工具加一条必须人工确认的策略，
 * 并留下审计记录」。{@link #shouldAddConfirmationPolicyWithoutTouchingLoop} 就是
 * 对这条标准的直接验证：同一个 Loop 类、同一个注册表，只换构造时传入的策略，
 * 一个工具就从「直接执行」变成「必须人工确认」。</p>
 */
public class GuardedAgentLoopTest {

    /** 记录被调用次数，用来证明「拒绝」时 handler 一次都没跑。 */
    private static final class CountingHandler implements ToolHandler {
        int callCount = 0;

        @Override
        public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
            callCount++;
            return ToolExecutionResult.success("已执行");
        }
    }

    /** 把每条决定收进列表的审计槽。 */
    private static final class RecordingAudit implements AuditSink {
        final List<PermissionDecision> records = new ArrayList<PermissionDecision>();

        @Override
        public void record(PermissionRequest request, PermissionDecision decision) {
            records.add(decision);
        }
    }

    private ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("cam-02", DeviceType.CAMERA);
        return new ToolContext("test-user",
                new SceneSnapshot(20, 20, 5, devices,
                        new LinkedHashSet<String>(Arrays.asList("cam-02"))));
    }

    private ToolRegistry registryWith(CountingHandler deleteHandler) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, new CountingHandler()));
        registry.register(new ToolDefinition(
                "delete_device", "删除设备", "{}", ToolEffect.DESTRUCTIVE, deleteHandler));
        return registry;
    }

    /** 排一次工具调用 + 一次最终答复，构成最短的完整往返。 */
    private FakeModelClient modelCalling(String toolName, String rawArguments) {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", toolName, rawArguments)),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("好了。", FinishReason.STOP, new TokenUsage(150, 30));
        return fake;
    }

    private GuardedAgentLoop loopOf(FakeModelClient fake, ToolRegistry registry,
                                    PermissionPolicy policy) {
        return new GuardedAgentLoop("deepseek-v4-flash", fake, registry, context(),
                5, 1000L, TraceIdGenerator.fixed("trace-006"), policy);
    }

    /** 找出这次运行里唯一那轮工具调用的记录。 */
    private RoundTrace toolRoundOf(GuardedTrace trace) {
        for (RoundTrace round : trace.getRounds()) {
            if (round.hasToolCall()) {
                return round;
            }
        }
        return null;
    }

    /**
     * 阶段 8 的完成标准：只换传入的策略，就让某个工具变成「必须人工确认」，并留下审计记录。
     *
     * <p>Loop 类没有为这条策略改过一行；确认逻辑全在构造参数里。</p>
     */
    @Test
    public void shouldAddConfirmationPolicyWithoutTouchingLoop() {
        CountingHandler deleteHandler = new CountingHandler();
        RecordingAudit audit = new RecordingAudit();

        // 「必须人工确认」= 一条 ask 规则 + 一个会点「同意」的审批器。
        PermissionRule mustConfirm = new PermissionRule(
                "delete-needs-confirmation", PermissionBehavior.ASK,
                "删除设备需要人工确认", new PermissionRule.Matcher() {
            @Override
            public boolean matches(PermissionRequest request) {
                return "delete_device".equals(request.getToolName());
            }
        });
        ApprovalProvider humanSaysYes = new ApprovalProvider() {
            @Override
            public PermissionDecision decide(PermissionRequest request) {
                return new PermissionDecision(PermissionBehavior.ALLOW,
                        "运维已确认删除 cam-01", "human:ops");
            }
        };
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(mustConfirm), humanSaysYes, audit);

        GuardedTrace trace = loopOf(
                modelCalling("delete_device", "{\"targetId\":\"cam-01\"}"),
                registryWith(deleteHandler), policy)
                .run("你是场景管理助手", "删掉 cam-01");

        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
        assertEquals(1, deleteHandler.callCount, "人工确认通过后工具才真正执行");
        assertEquals("executed", toolRoundOf(trace).getToolOutcome());

        assertEquals(1, audit.records.size(), "一次裁决恰好一条审计");
        assertEquals("human:ops", audit.records.get(0).getSource(), "审计里记着是谁批的");
        assertEquals(PermissionBehavior.ALLOW, audit.records.get(0).getBehavior());
    }

    /** 同样的策略骨架，审批器点「拒绝」：handler 一次都不跑，模型收到 permission_denied。 */
    @Test
    public void shouldNotExecuteWhenApproverRejects() {
        CountingHandler deleteHandler = new CountingHandler();
        RecordingAudit audit = new RecordingAudit();
        PermissionRule mustConfirm = new PermissionRule(
                "delete-needs-confirmation", PermissionBehavior.ASK,
                "删除设备需要人工确认", new PermissionRule.Matcher() {
            @Override
            public boolean matches(PermissionRequest request) {
                return "delete_device".equals(request.getToolName());
            }
        });
        ApprovalProvider humanSaysNo = new ApprovalProvider() {
            @Override
            public PermissionDecision decide(PermissionRequest request) {
                return new PermissionDecision(PermissionBehavior.DENY,
                        "运维否决了这次删除", "human:ops");
            }
        };

        GuardedTrace trace = loopOf(
                modelCalling("delete_device", "{\"targetId\":\"cam-01\"}"),
                registryWith(deleteHandler),
                new PermissionPolicy(Arrays.asList(mustConfirm), humanSaysNo, audit))
                .run("你是场景管理助手", "删掉 cam-01");

        assertEquals(0, deleteHandler.callCount, "被拒绝的调用绝不能产生副作用");
        assertEquals("permission_denied", toolRoundOf(trace).getToolOutcome());
        assertEquals("permission_denied", toolRoundOf(trace).getErrorCode(),
                "拒绝以工具错误的形式回传，模型才知道没执行");
        assertEquals(PermissionBehavior.DENY, audit.records.get(0).getBehavior());
    }

    /** 没配审批器时 ask 收敛为拒绝：默认答案是不执行。 */
    @Test
    public void shouldDenyWhenConfirmationNeededButNoApprover() {
        CountingHandler deleteHandler = new CountingHandler();
        // 只有规则，没有审批器。
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(new PermissionRule(
                        "delete-needs-confirmation", PermissionBehavior.ASK,
                        "删除设备需要人工确认", new PermissionRule.Matcher() {
                    @Override
                    public boolean matches(PermissionRequest request) {
                        return "delete_device".equals(request.getToolName());
                    }
                })), null, null);

        GuardedTrace trace = loopOf(
                modelCalling("delete_device", "{\"targetId\":\"cam-01\"}"),
                registryWith(deleteHandler), policy)
                .run("你是场景管理助手", "删掉 cam-01");

        assertEquals(0, deleteHandler.callCount);
        assertEquals("permission_denied", toolRoundOf(trace).getToolOutcome());
    }

    /** 受保护设备的硬边界不可翻盘：审批器说同意也照样不执行。 */
    @Test
    public void shouldKeepHardBoundaryUnappealableInsideLoop() {
        CountingHandler deleteHandler = new CountingHandler();
        RecordingAudit audit = new RecordingAudit();
        ApprovalProvider alwaysYes = new ApprovalProvider() {
            @Override
            public PermissionDecision decide(PermissionRequest request) {
                return new PermissionDecision(PermissionBehavior.ALLOW, "我批了", "human:ops");
            }
        };

        // cam-02 在 context() 里是受保护设备。
        GuardedTrace trace = loopOf(
                modelCalling("delete_device", "{\"targetId\":\"cam-02\"}"),
                registryWith(deleteHandler),
                new PermissionPolicy(null, alwaysYes, audit))
                .run("你是场景管理助手", "删掉 cam-02");

        assertEquals(0, deleteHandler.callCount, "硬边界内的设备谁批都不能删");
        assertEquals("permission_denied", toolRoundOf(trace).getToolOutcome());
        assertEquals(PermissionBehavior.DENY, audit.records.get(0).getBehavior());
    }

    /** 只读工具不受策略影响：没有规则拦它时归一为放行。 */
    @Test
    public void shouldAllowReadToolWithoutAnyRule() {
        CountingHandler deleteHandler = new CountingHandler();
        RecordingAudit audit = new RecordingAudit();

        GuardedTrace trace = loopOf(
                modelCalling("list_devices", "{}"),
                registryWith(deleteHandler),
                new PermissionPolicy(null, null, audit))
                .run("你是场景管理助手", "看看有哪些设备");

        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
        assertEquals("executed", toolRoundOf(trace).getToolOutcome());
        assertEquals("default", audit.records.get(0).getSource(),
                "无人反对时的放行，来源记为 default");
    }

    /** 裁决结果进 trace：审计要能回答「谁批的、依据哪条规则」。 */
    @Test
    public void shouldRecordDecisionInTrace() {
        GuardedTrace trace = loopOf(
                modelCalling("delete_device", "{\"targetId\":\"cam-01\"}"),
                registryWith(new CountingHandler()),
                new PermissionPolicy(null, new ApprovalProvider() {
                    @Override
                    public PermissionDecision decide(PermissionRequest request) {
                        return new PermissionDecision(PermissionBehavior.ALLOW,
                                "运维已确认", "human:ops");
                    }
                }, null))
                .run("你是场景管理助手", "删掉 cam-01");

        assertEquals(1, trace.getDecisions().size());
        assertEquals("human:ops", trace.getDecisions().get(0).getSource());
        assertTrue(trace.render().contains("permission=allow"),
                "渲染出来的轨迹里能看到裁决行");
    }

    /** 参数校验就失败的调用不进权限层，也不进审计。 */
    @Test
    public void shouldNotAuditCallsThatFailedPrepare() {
        RecordingAudit audit = new RecordingAudit();

        GuardedTrace trace = loopOf(
                modelCalling("no_such_tool", "{}"),
                registryWith(new CountingHandler()),
                new PermissionPolicy(null, null, audit))
                .run("你是场景管理助手", "调一个不存在的工具");

        assertEquals("rejected", toolRoundOf(trace).getToolOutcome());
        assertTrue(audit.records.isEmpty(), "没有合法调用可裁决时，审计里不该多出记录");
        assertTrue(trace.getDecisions().isEmpty());
    }

    /** 审计写入失败让整次调用不执行：留痕失败等于没留痕。 */
    @Test
    public void shouldNotExecuteWhenAuditFails() {
        CountingHandler deleteHandler = new CountingHandler();
        AuditSink brokenAudit = new AuditSink() {
            @Override
            public void record(PermissionRequest request, PermissionDecision decision) {
                throw new IllegalStateException("审计库连不上");
            }
        };

        GuardedTrace trace = loopOf(
                modelCalling("list_devices", "{}"),
                registryWith(deleteHandler),
                new PermissionPolicy(null, null, brokenAudit))
                .run("你是场景管理助手", "看看设备");

        assertEquals("policy_error", toolRoundOf(trace).getToolOutcome());
        assertEquals("permission_evaluation_error", toolRoundOf(trace).getErrorCode());
        assertTrue(trace.getDecisions().isEmpty(), "裁决没能完成，trace 里不该有决定");
    }

    /** 裁决在幂等缓存之前：策略对每一次调用都生效，不是只对第一次。 */
    @Test
    public void shouldAdjudicateBeforeCacheOnRepeatedCall() {
        CountingHandler deleteHandler = new CountingHandler();
        RecordingAudit audit = new RecordingAudit();

        // 同一个调用连来两次，第二次仍应经过裁决。
        FakeModelClient fake = new FakeModelClient();
        String encoded = ToolCallCodec.encode(
                new ToolCall("call-1", "delete_device", "{\"targetId\":\"cam-01\"}"));
        fake.enqueueResponse(encoded, FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse(encoded, FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("好了。", FinishReason.STOP, new TokenUsage(150, 30));

        GuardedTrace trace = loopOf(fake, registryWith(deleteHandler),
                new PermissionPolicy(null, new ApprovalProvider() {
                    @Override
                    public PermissionDecision decide(PermissionRequest request) {
                        return new PermissionDecision(PermissionBehavior.ALLOW,
                                "运维已确认", "human:ops");
                    }
                }, audit))
                .run("你是场景管理助手", "删掉 cam-01，再删一次");

        assertEquals(1, deleteHandler.callCount, "幂等缓存让副作用只发生一次");
        assertEquals(2, audit.records.size(), "但两次调用都各自留下了审计记录");
        assertEquals(3, trace.getRoundCount());
    }

    /** 策略为空会在构造时就拒绝：不带策略就该用第 5 课的 AgentLoop。 */
    @Test
    public void shouldRejectNullPolicyAtConstruction() {
        boolean rejected = false;
        try {
            new GuardedAgentLoop("deepseek-v4-flash", new FakeModelClient(),
                    registryWith(new CountingHandler()), context(),
                    5, 1000L, TraceIdGenerator.fixed("t"), null);
        } catch (IllegalArgumentException e) {
            rejected = true;
        }
        assertTrue(rejected, "没有策略却用这个类，属于用错了工具，应当构造即失败");
    }
}
