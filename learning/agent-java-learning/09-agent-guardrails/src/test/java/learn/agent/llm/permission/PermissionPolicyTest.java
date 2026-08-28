package learn.agent.llm.permission;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.structured.DeviceType;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;
import learn.agent.llm.tool.ToolRegistry;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link PermissionPolicy} 的测试：四态归约、硬边界不可翻盘、ask 的 fail-closed、审计是闸门。
 *
 * <p>本课的完成标准是「不改 Loop 主体就能给某个工具加一条必须人工确认的策略，
 * 并留下审计记录」。所以这里断言的都是<b>可观察的输出</b>——behavior、source、reason、
 * 审计条数——而不是内部调用顺序。source 和 reason 是审计的追责依据，属于契约。</p>
 */
public class PermissionPolicyTest {

    /** 什么都不做的 handler：本类只测裁决，不测执行。 */
    private static final class NoopHandler implements ToolHandler {
        @Override
        public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
            return ToolExecutionResult.success("ok");
        }
    }

    /** 记录收到了什么的审计器。 */
    private static final class RecordingAudit implements AuditSink {
        final List<PermissionDecision> records = new ArrayList<PermissionDecision>();
        final List<PermissionRequest> requests = new ArrayList<PermissionRequest>();

        @Override
        public void record(PermissionRequest request, PermissionDecision decision) {
            requests.add(request);
            records.add(decision);
        }
    }

    /** 落盘失败的审计器，用来证明审计是闸门。 */
    private static final class FailingAudit implements AuditSink {
        @Override
        public void record(PermissionRequest request, PermissionDecision decision) {
            throw new IllegalStateException("审计库写不进去");
        }
    }

    /** 固定答复的审批器，并记录被问了几次。 */
    private static final class StubApproval implements ApprovalProvider {
        private final PermissionDecision answer;
        int askedCount = 0;
        PermissionRequest lastRequest;

        private StubApproval(PermissionDecision answer) {
            this.answer = answer;
        }

        @Override
        public PermissionDecision decide(PermissionRequest request) {
            askedCount++;
            lastRequest = request;
            return answer;
        }
    }

    private ToolRegistry registry() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ, new NoopHandler()));
        registry.register(new ToolDefinition(
                "delete_device", "删除设备", "{}", ToolEffect.DESTRUCTIVE, new NoopHandler()));
        return registry;
    }

    private ToolContext context(String... protectedIds) {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("cam-02", DeviceType.CAMERA);
        Set<String> guarded = new LinkedHashSet<String>(Arrays.asList(protectedIds));
        return new ToolContext("test-user", new SceneSnapshot(20, 20, 5, devices, guarded));
    }

    private PermissionRequest requestOf(String tool, String rawArguments, ToolContext context) {
        PreparedToolCall prepared = registry().prepare(new ToolCall("call-1", tool, rawArguments));
        assertFalse(prepared.isFailed(), "测试前提：这次调用必须能通过 prepare");
        return new PermissionRequest(prepared, context);
    }

    private PermissionRequest readRequest() {
        return requestOf("list_devices", "{}", context());
    }

    private PermissionRule rule(String name, PermissionBehavior behavior, final String toolName) {
        return new PermissionRule(name, behavior, "测试规则 " + name, new PermissionRule.Matcher() {
            @Override
            public boolean matches(PermissionRequest request) {
                return request.getToolName().equals(toolName);
            }
        });
    }

    /** 没有任何规则拦下时归一为放行，且 source 记成 default 而不是假装某条规则批的。 */
    @Test
    public void shouldNormalizePassthroughToAllow() {
        PermissionDecision decision = new PermissionPolicy().decide(readRequest());

        assertEquals(PermissionBehavior.ALLOW, decision.getBehavior());
        assertEquals("default", decision.getSource());
    }

    /** 弃权票不参与计票：只有一条 passthrough 规则时，结果仍是 default 归一的放行。 */
    @Test
    public void shouldIgnorePassthroughCandidatesInReduction() {
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(rule("abstain", PermissionBehavior.PASSTHROUGH, "list_devices")),
                null, null);

        PermissionDecision decision = policy.decide(readRequest());

        assertEquals(PermissionBehavior.ALLOW, decision.getBehavior());
        assertEquals("default", decision.getSource(),
                "passthrough 不该被当成一条有效的放行决定");
    }

    /** 显式 allow 规则命中时，source 是规则名，能和无人反对的 default 放行区分开。 */
    @Test
    public void shouldAttributeExplicitAllowToItsRule() {
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(rule("read-ok", PermissionBehavior.ALLOW, "list_devices")),
                null, null);

        assertEquals("read-ok", policy.decide(readRequest()).getSource());
    }

    /** deny 压过 allow，无论 allow 规则注册得更早。 */
    @Test
    public void shouldLetDenyBeatAllowRegardlessOfOrder() {
        PermissionPolicy policy = new PermissionPolicy(Arrays.asList(
                rule("allow-first", PermissionBehavior.ALLOW, "list_devices"),
                rule("deny-second", PermissionBehavior.DENY, "list_devices")), null, null);

        PermissionDecision decision = policy.decide(readRequest());

        assertEquals(PermissionBehavior.DENY, decision.getBehavior());
        assertEquals("deny-second", decision.getSource());
    }

    /** 同级冲突取候选列表里最早的那条，让结果不依赖遍历顺序的偶然性。 */
    @Test
    public void shouldPickEarliestCandidateAtSameLevel() {
        PermissionPolicy policy = new PermissionPolicy(Arrays.asList(
                rule("deny-a", PermissionBehavior.DENY, "list_devices"),
                rule("deny-b", PermissionBehavior.DENY, "list_devices")), null, null);

        assertEquals("deny-a", policy.decide(readRequest()).getSource());
    }

    /** 破坏性工具默认要人工确认，没配审批器就拒绝——默认答案是不执行。 */
    @Test
    public void shouldDenyDestructiveWhenNoApproverConfigured() {
        PermissionDecision decision = new PermissionPolicy()
                .decide(requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context()));

        assertEquals(PermissionBehavior.DENY, decision.getBehavior());
        assertEquals("approval", decision.getSource());
    }

    /** 人工批准后放行：这是完成标准里「加一条必须确认的策略」跑通的正例。 */
    @Test
    public void shouldAllowDestructiveAfterHumanApproval() {
        StubApproval approval = new StubApproval(new PermissionDecision(
                PermissionBehavior.ALLOW, "运维已确认", "human:ops"));
        PermissionPolicy policy = new PermissionPolicy(null, approval, null);

        PermissionDecision decision = policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context()));

        assertEquals(PermissionBehavior.ALLOW, decision.getBehavior());
        assertEquals("human:ops", decision.getSource());
        assertEquals(1, approval.askedCount);
    }

    /** 交给审批器的请求里带着那条 ask，否则审批器不知道要确认什么。 */
    @Test
    public void shouldHandApprovalTheProposedAsk() {
        StubApproval approval = new StubApproval(new PermissionDecision(
                PermissionBehavior.ALLOW, "确认", "human"));
        new PermissionPolicy(null, approval, null)
                .decide(requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context()));

        assertEquals(PermissionBehavior.ASK,
                approval.lastRequest.getProposedDecision().getBehavior());
    }

    /** 审批器抛异常按拒绝处理：审批环节自己坏了不能等于放行。 */
    @Test
    public void shouldDenyWhenApproverThrows() {
        PermissionPolicy policy = new PermissionPolicy(null, new ApprovalProvider() {
            @Override
            public PermissionDecision decide(PermissionRequest request) {
                throw new IllegalStateException("审批服务超时");
            }
        }, null);

        assertEquals(PermissionBehavior.DENY, policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context())).getBehavior());
    }

    /** 审批器返回 null 按拒绝处理。 */
    @Test
    public void shouldDenyWhenApproverReturnsNull() {
        PermissionPolicy policy = new PermissionPolicy(null, new StubApproval(null), null);

        assertEquals(PermissionBehavior.DENY, policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context())).getBehavior());
    }

    /** 审批器又返回 ask 等于没裁决，按拒绝处理，避免 ask 无限传递下去。 */
    @Test
    public void shouldDenyWhenApproverReturnsAskAgain() {
        StubApproval approval = new StubApproval(new PermissionDecision(
                PermissionBehavior.ASK, "我也定不了", "human"));
        PermissionPolicy policy = new PermissionPolicy(null, approval, null);

        assertEquals(PermissionBehavior.DENY, policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context())).getBehavior());
    }

    /** 审批器返回 passthrough 同样不算最终态，按拒绝处理。 */
    @Test
    public void shouldDenyWhenApproverReturnsPassthrough() {
        StubApproval approval = new StubApproval(new PermissionDecision(
                PermissionBehavior.PASSTHROUGH, "弃权", "human"));
        PermissionPolicy policy = new PermissionPolicy(null, approval, null);

        assertEquals(PermissionBehavior.DENY, policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context())).getBehavior());
    }

    /** 受保护设备是硬边界：人工批准也翻不过来，而且审批器压根不该被问。 */
    @Test
    public void shouldMakeHardBoundaryUnappealable() {
        StubApproval approval = new StubApproval(new PermissionDecision(
                PermissionBehavior.ALLOW, "我批了", "human:ops"));
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(rule("allow-all", PermissionBehavior.ALLOW, "delete_device")),
                approval, null);

        PermissionDecision decision = policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context("cam-01")));

        assertEquals(PermissionBehavior.DENY, decision.getBehavior());
        assertEquals(0, approval.askedCount, "硬边界拒绝时不该去打扰人");
    }

    /** 非受保护设备不受硬边界影响，仍按正常的「需确认」流程走。 */
    @Test
    public void shouldNotApplyHardBoundaryToUnprotectedDevice() {
        StubApproval approval = new StubApproval(new PermissionDecision(
                PermissionBehavior.ALLOW, "确认", "human"));
        PermissionPolicy policy = new PermissionPolicy(null, approval, null);

        PermissionDecision decision = policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-02\"}", context("cam-01")));

        assertEquals(PermissionBehavior.ALLOW, decision.getBehavior());
        assertEquals(1, approval.askedCount);
    }

    /** 规则判断抛异常算这条规则投了拒绝票，而不是当它没说话。 */
    @Test
    public void shouldDenyWhenRuleMatcherThrows() {
        PermissionPolicy policy = new PermissionPolicy(Arrays.asList(
                new PermissionRule("broken", PermissionBehavior.ALLOW, "有 bug 的规则",
                        new PermissionRule.Matcher() {
                            @Override
                            public boolean matches(PermissionRequest request) {
                                throw new IllegalStateException("规则里有 bug");
                            }
                        })), null, null);

        PermissionDecision decision = policy.decide(readRequest());

        assertEquals(PermissionBehavior.DENY, decision.getBehavior());
        assertEquals("broken", decision.getSource(), "要能追到是哪条规则出的问题");
    }

    /** 规则谓词抛的是 Error（比如自我递归的 StackOverflowError）也要收敛成 deny。 */
    @Test
    public void shouldDenyWhenRuleMatcherThrowsError() {
        PermissionPolicy policy = new PermissionPolicy(Arrays.asList(
                new PermissionRule("overflow", PermissionBehavior.ALLOW, "会栈溢出的规则",
                        new PermissionRule.Matcher() {
                            @Override
                            public boolean matches(PermissionRequest request) {
                                throw new StackOverflowError("谓词自我递归了");
                            }
                        })), null, null);

        PermissionDecision decision = policy.decide(readRequest());

        assertEquals(PermissionBehavior.DENY, decision.getBehavior(),
                "只抓 RuntimeException 的话异常会窜出 decide()，既没有 deny 也没有审计");
        assertEquals("overflow", decision.getSource());
    }

    /** 审批器抛 Error 同样 fail-closed，不能让异常窜出去绕过审计。 */
    @Test
    public void shouldDenyWhenApproverThrowsError() {
        RecordingAudit audit = new RecordingAudit();
        PermissionPolicy policy = new PermissionPolicy(null, new ApprovalProvider() {
            @Override
            public PermissionDecision decide(PermissionRequest request) {
                throw new StackOverflowError("审批器炸了");
            }
        }, audit);

        PermissionDecision decision = policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context()));

        assertEquals(PermissionBehavior.DENY, decision.getBehavior());
        assertEquals(1, audit.records.size(), "审批器炸了也要留下一条记录");
    }

    /** 审批器没收敛时，deny 的原因要带上原来那条 ask 在问什么，否则审计看不出所以然。 */
    @Test
    public void shouldKeepProposedReasonWhenApprovalUnresolved() {
        PermissionPolicy policy = new PermissionPolicy(null,
                new StubApproval(new PermissionDecision(
                        PermissionBehavior.PASSTHROUGH, "我不表态", "lazy")), null);

        PermissionDecision decision = policy.decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context()));

        assertEquals(PermissionBehavior.DENY, decision.getBehavior());
        assertTrue(decision.getReason().contains("不可逆操作需要人工审批"),
                "要能从审计记录反推出这条 ask 原本在问什么，实际：" + decision.getReason());
    }

    /** 三元组相同的裁决要相等：审计断言靠的是结构相等，不是同一个对象。 */
    @Test
    public void shouldCompareDecisionsByValue() {
        PermissionDecision one = new PermissionDecision(
                PermissionBehavior.DENY, "设备受保护", "protected-device");
        PermissionDecision two = new PermissionDecision(
                PermissionBehavior.DENY, "设备受保护", "protected-device");

        assertEquals(one, two);
        assertEquals(one.hashCode(), two.hashCode());
        assertNotEquals(one, new PermissionDecision(
                PermissionBehavior.DENY, "设备受保护", "some-rule"),
                "source 不同就是不同的决定：同样的拒绝，追责对象不一样");
    }

    /** 规则拿到的参数是副本，改它影响不到审计和硬边界看到的那一份。 */
    @Test
    public void shouldHandRulesADetachedArgumentsCopy() {
        PermissionRequest request = requestOf(
                "delete_device", "{\"targetId\":\"cam-01\"}", context());

        ((com.fasterxml.jackson.databind.node.ObjectNode) request.getArgumentsSnapshot())
                .put("targetId", "gate-99");

        assertEquals("cam-01",
                request.getArgumentsSnapshot().get("targetId").asText(),
                "快照被改了还能读回原值，说明每次给的都是新副本");
    }

    /** 一次裁决只写一条审计，记的是最终决定，所以审计里永远看不到 ask。 */
    @Test
    public void shouldRecordExactlyOneFinalDecision() {
        RecordingAudit audit = new RecordingAudit();
        StubApproval approval = new StubApproval(new PermissionDecision(
                PermissionBehavior.ALLOW, "运维已确认", "human:ops"));

        new PermissionPolicy(null, approval, audit).decide(
                requestOf("delete_device", "{\"targetId\":\"cam-01\"}", context()));

        assertEquals(1, audit.records.size());
        assertEquals(PermissionBehavior.ALLOW, audit.records.get(0).getBehavior());
        assertTrue(audit.records.get(0).getBehavior().isFinal(),
                "审计里只该出现 allow/deny 这两种最终态");
    }

    /** 拒绝也要留痕，否则「谁被拦下过」这个问题事后无法回答。 */
    @Test
    public void shouldRecordDenialsToo() {
        RecordingAudit audit = new RecordingAudit();
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(rule("no-read", PermissionBehavior.DENY, "list_devices")),
                null, audit);

        policy.decide(readRequest());

        assertEquals(1, audit.records.size());
        assertEquals(PermissionBehavior.DENY, audit.records.get(0).getBehavior());
    }

    /** 审计写不进去就让整次裁决失败：留不下记录的放行等于没有约束。 */
    @Test
    public void shouldFailDecisionWhenAuditFails() {
        final PermissionPolicy policy = new PermissionPolicy(null, null, new FailingAudit());

        assertThrows(IllegalStateException.class, new org.junit.jupiter.api.function.Executable() {
            @Override
            public void execute() {
                policy.decide(readRequest());
            }
        });
    }

    /** Hook 建议只是候选之一：它的 allow 拦不住一条 deny 规则。 */
    @Test
    public void shouldTreatRecommendationAsCandidateOnly() {
        PreparedToolCall prepared = registry().prepare(new ToolCall("call-1", "list_devices", "{}"));
        PermissionRequest request = new PermissionRequest(prepared, context(),
                Arrays.asList(new PermissionDecision(
                        PermissionBehavior.ALLOW, "hook 说可以", "hook:demo")),
                null);
        PermissionPolicy policy = new PermissionPolicy(
                Arrays.asList(rule("no-read", PermissionBehavior.DENY, "list_devices")),
                null, null);

        assertEquals(PermissionBehavior.DENY, policy.decide(request).getBehavior());
    }

    /** prepare 已经失败的调用不许进权限层，免得审计里堆满无意义记录。 */
    @Test
    public void shouldRejectFailedPreparedCall() {
        final PreparedToolCall failed = registry().prepare(new ToolCall("call-1", "no_such_tool", "{}"));
        assertTrue(failed.isFailed());

        assertThrows(PermissionContractException.class,
                new org.junit.jupiter.api.function.Executable() {
                    @Override
                    public void execute() {
                        new PermissionRequest(failed, context());
                    }
                });
    }

    /** 拒绝决定转成工具错误时用固定错误码，模型据此向用户解释而不是以为执行了。 */
    @Test
    public void shouldConvertDenialToToolError() {
        PermissionDecision decision = new PermissionPolicy(
                Arrays.asList(rule("no-read", PermissionBehavior.DENY, "list_devices")),
                null, null).decide(readRequest());

        ToolExecutionResult result = decision.toToolResult();

        assertTrue(result.isError());
        assertEquals("permission_denied", result.getErrorCode());
    }
}
