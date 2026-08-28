package learn.agent.llm.lesson06;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.lesson01.FakeModelClient;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.TokenUsage;
import learn.agent.llm.lesson03.DeviceType;
import learn.agent.llm.lesson03.SceneSnapshot;
import learn.agent.llm.lesson04.ToolCall;
import learn.agent.llm.lesson04.ToolCallCodec;
import learn.agent.llm.lesson04.ToolContext;
import learn.agent.llm.lesson04.ToolDefinition;
import learn.agent.llm.lesson04.ToolEffect;
import learn.agent.llm.lesson04.ToolExecutionResult;
import learn.agent.llm.lesson04.ToolHandler;
import learn.agent.llm.lesson04.ToolRegistry;
import learn.agent.llm.lesson05.TraceIdGenerator;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 阶段 8 的教学入口：给工具加一条「必须人工确认」的策略，并留下审计记录。
 *
 * <p>阶段 8 的完成标准有个关键限定 ——「<b>不修改 Loop 主体</b>」。所以本课
 * 第 5 课的 {@code AgentLoop} 一行没改，策略是从构造参数注进
 * {@link GuardedAgentLoop} 的。场景三就是这条标准的现场演示。</p>
 *
 * <p>运行：</p>
 * <pre>
 * [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
 * mvn -o -pl 05-llm-client -am package -DskipTests
 * java "-Dfile.encoding=UTF-8" -cp '05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.lesson06.PermissionDemo
 * </pre>
 */
public class PermissionDemo {

    public static void main(String[] args) {
        SceneSnapshot scene = buildScene();
        ToolContext context = new ToolContext("demo-user", scene);

        System.out.println("当前场景：" + scene);
        System.out.println("受保护设备：" + scene.getProtectedDeviceIds());
        System.out.println();

        demoReadNeedsNoApproval(context);
        demoDestructiveAsksFirst(context);
        demoHumanApprovalDecides(context);
        demoHardBoundaryCannotBeAppealed(context);
        demoAuditIsAGateNotALog(context);
    }

    /** 场景一：只读工具直接放行，没人被打扰。 */
    private static void demoReadNeedsNoApproval(ToolContext context) {
        System.out.println("=== 场景一：只读工具无需审批 ===");

        RecordingAudit audit = new RecordingAudit();
        PermissionPolicy policy = new PermissionPolicy(null, approveAll(), audit);

        PermissionDecision decision = policy.decide(request(context, "list_devices", "{}"));

        System.out.println("裁决：" + decision);
        System.out.println("审批器是否被问过：否（只读工具压根没进 ask 分支）");
        System.out.println("审计条数：" + audit.records.size());
        System.out.println("说明：只读工具没有副作用，拦它只会让人对提示疲劳。");
        System.out.println();
    }

    /** 场景二：破坏性工具默认进入待审批，没有审批器时 fail-closed。 */
    private static void demoDestructiveAsksFirst(ToolContext context) {
        System.out.println("=== 场景二：破坏性工具默认需要确认，没人审批就拒绝 ★ ===");

        RecordingAudit audit = new RecordingAudit();
        // 刻意不配审批器。
        PermissionPolicy policy = new PermissionPolicy(null, null, audit);

        PermissionDecision decision = policy.decide(
                request(context, "delete_device", "{\"targetId\":\"cam-01\"}"));

        System.out.println("裁决：" + decision);
        System.out.println("说明：ask 是中间态，绝不会离开 policy。没有审批器时它收敛成 deny，");
        System.out.println("      而不是「没人管就放过」——默认答案必须是不执行。");
        System.out.println("审计记录：" + audit.records.get(0));
        System.out.println();
    }

    /** 场景三：不改 Loop 主体，加一条必须人工确认的策略。这就是完成标准。 */
    private static void demoHumanApprovalDecides(ToolContext context) {
        System.out.println("=== 场景三：不改 Loop 主体，给 delete_device 加人工确认 ★★ ===");

        for (boolean humanApproves : new boolean[]{false, true}) {
            RecordingAudit audit = new RecordingAudit();
            // 一条规则 + 一个审批器 + 一个审计器，全部从构造参数注入。
            PermissionPolicy policy = new PermissionPolicy(
                    Arrays.asList(new PermissionRule(
                            "delete-needs-human", PermissionBehavior.ASK,
                            "删除设备不可逆，必须人工确认",
                            new PermissionRule.Matcher() {
                                @Override
                                public boolean matches(PermissionRequest request) {
                                    return "delete_device".equals(request.getToolName());
                                }
                            })),
                    fixedApprover(humanApproves),
                    audit);

            CountingHandler deleteHandler = new CountingHandler();
            FakeModelClient fake = new FakeModelClient();
            fake.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall(
                            "call-1", "delete_device", "{\"targetId\":\"cam-01\"}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
            fake.enqueueResponse("我按你的意思处理完了。",
                    FinishReason.STOP, new TokenUsage(160, 25));

            GuardedAgentLoop loop = new GuardedAgentLoop(
                    "deepseek-v4-flash", fake, registryWith(deleteHandler), context,
                    5, 1000L, TraceIdGenerator.fixed("trace-demo"), policy);

            GuardedTrace trace;
            try {
                trace = loop.run("你是场景管理助手", "把 cam-01 删掉");
            } finally {
                loop.shutdown();
            }

            System.out.println("-- 人工" + (humanApproves ? "批准" : "驳回") + " --");
            System.out.print(trace.render());
            System.out.println("   handler 实际执行次数：" + deleteHandler.callCount);
            System.out.println("   审计记录：" + audit.records.get(0));
        }
        System.out.println("说明：Loop 的代码两次完全一样，变的只有注进去的策略和审批结果。");
        System.out.println("      驳回时 handler 执行 0 次，模型收到 permission_denied 并据此回话。");
        System.out.println();
    }

    /** 场景四：硬边界不可翻盘，连人都不能批。 */
    private static void demoHardBoundaryCannotBeAppealed(ToolContext context) {
        System.out.println("=== 场景四：受保护设备的硬边界，人也批不动 ★ ===");

        RecordingAudit audit = new RecordingAudit();
        CountingApprover approver = new CountingApprover(true);
        // 规则和 Hook 都想放行，审批器也会批准。
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(new PermissionRule(
                        "ops-can-delete-anything", PermissionBehavior.ALLOW,
                        "运维有删除权限",
                        new PermissionRule.Matcher() {
                            @Override
                            public boolean matches(PermissionRequest request) {
                                return true;
                            }
                        })),
                approver, audit);

        List<PermissionDecision> hookSaysAllow = new ArrayList<PermissionDecision>();
        hookSaysAllow.add(new PermissionDecision(
                PermissionBehavior.ALLOW, "Hook 认为没问题", "hook"));

        PermissionDecision decision = policy.decide(new PermissionRequest(
                registryWith(new CountingHandler()).prepare(new ToolCall(
                        "call-1", "delete_device", "{\"targetId\":\"gate-99\"}")),
                context, hookSaysAllow, null));

        System.out.println("裁决：" + decision);
        System.out.println("审批器被问过几次：" + approver.callCount + "（应为 0）");
        System.out.println("说明：gate-99 在受保护集合里。硬边界给的是 deny，而 deny 在归约里");
        System.out.println("      压过一切 —— 规则的 allow、Hook 的 allow 都不算数，审批器连问都不问。");
        System.out.println("      「能被批准的边界」不是边界，是提示。");
        System.out.println();
    }

    /** 场景五：审计写不进去，这次调用就不许执行。 */
    private static void demoAuditIsAGateNotALog(ToolContext context) {
        System.out.println("=== 场景五：审计是闸门，不是日志 ★★ ===");

        CountingHandler handler = new CountingHandler();
        PermissionPolicy policy = new PermissionPolicy(null, approveAll(), new AuditSink() {
            @Override
            public void record(PermissionRequest request, PermissionDecision decision) {
                throw new IllegalStateException("审计库连不上");
            }
        });

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
        fake.enqueueResponse("刚才那步没能完成。",
                FinishReason.STOP, new TokenUsage(150, 20));

        GuardedAgentLoop loop = new GuardedAgentLoop(
                "deepseek-v4-flash", fake, registryWith(handler), context,
                5, 1000L, TraceIdGenerator.fixed("trace-audit"), policy);

        GuardedTrace trace;
        try {
            trace = loop.run("你是场景管理助手", "看看有哪些设备");
        } finally {
            loop.shutdown();
        }

        System.out.print(trace.render());
        System.out.println("   handler 实际执行次数：" + handler.callCount + "（应为 0）");
        System.out.println("说明：这是一个只读工具，本来一定会放行。但审计写失败了，");
        System.out.println("      所以它也不执行 —— 否则就会出现「副作用发生了，却没有任何记录」。");
        System.out.println("      把 record 的异常吞掉是最容易犯、也最难发现的错。");
        System.out.println();
    }

    // ---------- 下面是脚手架 ----------

    /** 带受保护设备的场景。 */
    private static SceneSnapshot buildScene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("gate-99", DeviceType.CAMERA);
        Set<String> protectedIds = new LinkedHashSet<String>();
        protectedIds.add("gate-99");
        return new SceneSnapshot(20, 20, 10, devices, protectedIds);
    }

    private static PermissionRequest request(ToolContext context, String tool, String args) {
        return new PermissionRequest(
                registryWith(new CountingHandler()).prepare(new ToolCall("call-1", tool, args)),
                context);
    }

    private static ToolRegistry registryWith(ToolHandler deleteHandler) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, new CountingHandler()));
        registry.register(new ToolDefinition(
                "delete_device", "删除设备", "{}", ToolEffect.DESTRUCTIVE, deleteHandler));
        return registry;
    }

    private static ApprovalProvider approveAll() {
        return fixedApprover(true);
    }

    private static ApprovalProvider fixedApprover(final boolean approve) {
        return new ApprovalProvider() {
            @Override
            public PermissionDecision decide(PermissionRequest request) {
                return approve
                        ? new PermissionDecision(PermissionBehavior.ALLOW, "人工批准", "human")
                        : new PermissionDecision(PermissionBehavior.DENY, "人工驳回", "human");
            }
        };
    }

    /** 数一下审批器被问了几次，用来证明硬边界不问人。 */
    private static final class CountingApprover implements ApprovalProvider {
        private final boolean approve;
        private int callCount = 0;

        private CountingApprover(boolean approve) {
            this.approve = approve;
        }

        @Override
        public PermissionDecision decide(PermissionRequest request) {
            callCount++;
            return approve
                    ? new PermissionDecision(PermissionBehavior.ALLOW, "人工批准", "human")
                    : new PermissionDecision(PermissionBehavior.DENY, "人工驳回", "human");
        }
    }

    /** 把审计记录存内存，方便打印。 */
    private static final class RecordingAudit implements AuditSink {
        private final List<String> records = new ArrayList<String>();

        @Override
        public void record(PermissionRequest request, PermissionDecision decision) {
            records.add("tool=" + request.getToolName()
                    + " identity=" + request.getContext().getIdentity()
                    + " behavior=" + decision.getBehavior().getWireValue()
                    + " source=" + decision.getSource()
                    + " reason=" + decision.getReason());
        }
    }

    /** 数执行次数的 handler。 */
    private static final class CountingHandler implements ToolHandler {
        private int callCount = 0;

        @Override
        public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
            callCount++;
            return ToolExecutionResult.success("已处理");
        }
    }
}
