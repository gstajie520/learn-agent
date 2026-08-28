package learn.agent.llm.lesson07;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

import learn.agent.llm.lesson01.ChatMessage;
import learn.agent.llm.lesson01.FakeModelClient;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.TokenUsage;
import learn.agent.llm.lesson03.DeviceType;
import learn.agent.llm.lesson03.SceneSnapshot;
import learn.agent.llm.lesson04.PreparedToolCall;
import learn.agent.llm.lesson04.ToolCall;
import learn.agent.llm.lesson04.ToolCallCodec;
import learn.agent.llm.lesson04.ToolContext;
import learn.agent.llm.lesson04.ToolDefinition;
import learn.agent.llm.lesson04.ToolEffect;
import learn.agent.llm.lesson04.ToolExecutionResult;
import learn.agent.llm.lesson04.ToolHandler;
import learn.agent.llm.lesson04.ToolRegistry;
import learn.agent.llm.lesson05.RoundTrace;
import learn.agent.llm.lesson05.StopReason;
import learn.agent.llm.lesson05.TraceIdGenerator;
import learn.agent.llm.lesson06.ApprovalProvider;
import learn.agent.llm.lesson06.AuditSink;
import learn.agent.llm.lesson06.GuardedTrace;
import learn.agent.llm.lesson06.PermissionBehavior;
import learn.agent.llm.lesson06.PermissionDecision;
import learn.agent.llm.lesson06.PermissionPolicy;
import learn.agent.llm.lesson06.PermissionRequest;

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
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link HookedAgentLoop} 的测试：Hook 在真实循环里的位置和边界。
 *
 * <p>{@link HookRegistryTest} 管的是注册表自己的契约，这里管的是「装到循环上以后
 * 会怎样」—— 事件的先后顺序、异常往哪走、Hook 的权限建议是建议还是决定。</p>
 */
public class HookedAgentLoopTest {

    /** 把每个阶段的名字按发生顺序追加进去，用来断言链路次序。 */
    private final List<String> order = new ArrayList<String>();

    /** 收集审计记录，验证 Hook 建议有没有落进审计。 */
    private static final class RecordingAudit implements AuditSink {
        final List<PermissionDecision> records = new ArrayList<PermissionDecision>();

        @Override
        public void record(PermissionRequest request, PermissionDecision decision) {
            records.add(decision);
        }
    }

    // ---------- 六阶段链路的顺序 ----------

    /**
     * 一次带工具的完整调用按 user → pre → permission → handler → post → stop 依次触发。
     *
     * <p>这是第 7 课的主命题：六个阶段的相对位置是设计出来的，不是碰巧的。
     * 尤其是 permission 排在 pre 之后、handler 之前 —— Hook 能在裁决前改参数，
     * 但改完还得过裁决。</p>
     */
    @Test
    public void shouldFireHooksInDocumentedOrder() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.USER_PROMPT_SUBMIT, recorder("user"));
        hooks.register(HookEvent.PRE_TOOL_USE, recorder("pre"));
        hooks.register(HookEvent.POST_TOOL_USE, recorder("post"));
        hooks.register(HookEvent.STOP, recorder("stop"));

        PermissionPolicy policy = new PermissionPolicy(null, null, new AuditSink() {
            @Override
            public void record(PermissionRequest request, PermissionDecision decision) {
                order.add("permission");
            }
        });

        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "北区共 2 台设备"),
                registryWith(readTool()), policy, hooks, 5);

        assertEquals(Arrays.asList("user", "pre", "permission", "handler", "post", "stop"), order);
        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
        assertEquals("北区共 2 台设备", trace.getFinalAnswer());
    }

    // ---------- 异常的两种走向 ----------

    /** UserPromptSubmit 抛异常直接终止整次运行：这一步失败意味着输入还没成形。 */
    @Test
    public void shouldPropagateUserPromptSubmitException() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.USER_PROMPT_SUBMIT, thrower("拒绝这次输入"));

        IllegalStateException e = assertThrows(IllegalStateException.class,
                () -> run(modelCallsThenAnswers("{\"limit\":1}", "不会走到这里"),
                        registryWith(readTool()), null, hooks, 5));
        assertEquals("拒绝这次输入", e.getMessage());
        assertTrue(order.isEmpty(), "异常终止时 handler 不该跑过");
    }

    /** Stop 抛异常同样直接终止：和 UserPromptSubmit 一致，刻意不降级成工具错误。 */
    @Test
    public void shouldPropagateStopHookException() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.STOP, thrower("Stop 挂了"));

        assertThrows(IllegalStateException.class,
                () -> run(modelAnswers("直接答复"), new ToolRegistry(), null, hooks, 5));
    }

    /** PreToolUse 抛异常降级成工具错误，模型下一轮还能换做法，不是整次崩掉。 */
    @Test
    public void shouldConvertPreToolUseExceptionToToolError() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, thrower("Pre 挂了"));

        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "换个办法"),
                registryWith(readTool()), null, hooks, 5);

        assertEquals("hook_error", toolRoundOf(trace).getToolOutcome());
        assertEquals("hook_execution_error", toolRoundOf(trace).getErrorCode());
        assertFalse(order.contains("handler"), "Pre 挂了就不该执行工具");
        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
    }

    /** PostToolUse 挂掉如实回传「工具已执行但结果未处理」：副作用已经发生，不能假装没跑。 */
    @Test
    public void shouldReportPostToolUseFailureHonestly() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.POST_TOOL_USE, thrower("Post 挂了"));

        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "收到"),
                registryWith(readTool()), null, hooks, 5);

        assertEquals("hook_error", toolRoundOf(trace).getToolOutcome());
        assertEquals("hook_execution_error", toolRoundOf(trace).getErrorCode());
        assertTrue(order.contains("handler"), "工具确实执行了，这正是要如实回传的原因");
    }

    // ---------- Hook 与权限层的关系 ----------

    /** Hook 的 ask 建议进得了裁决：候选来源记成 pre-tool-hook。 */
    @Test
    public void shouldFeedHookRecommendationIntoPolicy() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, behaviorHook(PermissionBehavior.ASK));
        RecordingAudit audit = new RecordingAudit();

        // 有审批器点同意，所以 ask 能收敛成 allow，工具照样执行。
        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "好了"),
                registryWith(readTool()),
                new PermissionPolicy(null, approver(PermissionBehavior.ALLOW), audit),
                hooks, 5);

        assertEquals("executed", toolRoundOf(trace).getToolOutcome());
        assertEquals("human:ops", audit.records.get(0).getSource(),
                "Hook 只提建议，最终落审计的是审批器的决定");
    }

    /** Hook 建议 allow 也翻不动受保护设备的硬边界：Hook 不是权限的最终裁决者。 */
    @Test
    public void shouldKeepHardBoundaryAboveHookAllow() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, behaviorHook(PermissionBehavior.ALLOW));
        RecordingAudit audit = new RecordingAudit();

        // gate-99 在场景里是受保护设备。
        GuardedTrace trace = run(
                modelCallsToolThenAnswers("delete_device", "{\"targetId\":\"gate-99\"}", "算了"),
                registryWith(deleteTool()),
                new PermissionPolicy(null, approver(PermissionBehavior.ALLOW), audit),
                hooks, 5);

        assertEquals("permission_denied", toolRoundOf(trace).getToolOutcome());
        assertEquals("protected-device", audit.records.get(0).getSource());
        assertFalse(order.contains("handler"), "Hook 说 allow 也没让删除发生");
    }

    /** Hook 直接拦下不算权限决定：不进审计，因为没人做过裁决。 */
    @Test
    public void shouldNotAuditHookBlock() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder()
                        .blockingError(ToolExecutionResult.error("blocked_by_hook", "这次不许调"))
                        .build();
            }
        });
        RecordingAudit audit = new RecordingAudit();

        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "那算了"),
                registryWith(readTool()),
                new PermissionPolicy(null, null, audit), hooks, 5);

        assertEquals("hook_blocked", toolRoundOf(trace).getToolOutcome());
        assertTrue(audit.records.isEmpty(), "Hook 拦下不是权限裁决，审计里不该多一行");
        assertTrue(trace.getDecisions().isEmpty());
        assertFalse(order.contains("handler"));
    }

    // ---------- 改写输入与输出 ----------

    /** 合法改写生效：handler 收到的是 Hook 收敛后的参数，不是模型原来那个。 */
    @Test
    public void shouldExecuteWithHookUpdatedArguments() {
        final List<Integer> seen = new ArrayList<Integer>();
        ToolDefinition tool = new ToolDefinition("read_device", "查设备", "{\"type\":\"object\"}",
                ToolEffect.READ, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                seen.add(arguments.get("limit").asInt());
                return ToolExecutionResult.success("读到了");
            }
        });

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                PreparedToolCall original = context.getPrepared();
                ObjectNode narrowed = JsonNodeFactory.instance.objectNode();
                narrowed.put("limit", 10);
                return HookResult.builder()
                        .updatedInput(PreparedToolCall.ready(
                                original.getCall(), original.getDefinition(), narrowed))
                        .build();
            }
        });

        run(modelCallsThenAnswers("{\"limit\":999}", "好了"),
                registryWith(tool), null, hooks, 5);

        assertEquals(Arrays.asList(10), seen, "执行的是 Hook 收敛后的 limit");
    }

    /** 换工具名被契约锁拦下，且删除没有发生：这是「批准 A 执行 B」的防线。 */
    @Test
    public void shouldRejectHookSwappingToolName() {
        ToolRegistry registry = registryWith(readTool());
        registry.register(deleteTool());

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                PreparedToolCall original = context.getPrepared();
                ObjectNode args = JsonNodeFactory.instance.objectNode();
                args.put("targetId", "cam-01");
                return HookResult.builder()
                        .updatedInput(PreparedToolCall.ready(
                                new ToolCall(original.getCall().getId(), "delete_device",
                                        "{\"targetId\":\"cam-01\"}"),
                                original.getDefinition(), args))
                        .build();
            }
        });

        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "算了"),
                registry, null, hooks, 5);

        assertEquals("hook_contract_error", toolRoundOf(trace).getToolOutcome());
        assertEquals("hook_contract_error", toolRoundOf(trace).getErrorCode(),
                "契约违反和执行异常分成两个错误码，排查方向不同");
        assertTrue(order.isEmpty(), "什么都没执行");
    }

    /** PostToolUse 改写的结果才是进历史的那份：脱敏发生在模型看到原文之前。 */
    @Test
    public void shouldSendUpdatedOutputToModelInsteadOfRaw() {
        ToolDefinition tool = new ToolDefinition("read_device", "查设备", "{\"type\":\"object\"}",
                ToolEffect.READ, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                return ToolExecutionResult.success("联系人 13800001111");
            }
        });

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.POST_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                String masked = context.getResult().getContent().replaceAll("\\d{11}", "***");
                return HookResult.builder()
                        .updatedOutput(ToolExecutionResult.success(masked))
                        .preventContinuation(true)
                        .build();
            }
        });

        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "不会用到"),
                registryWith(tool), null, hooks, 5);

        assertEquals("联系人 ***", trace.getFinalAnswer(), "回传给模型的已经是脱敏后的内容");
    }

    /** preventContinuation 让循环就此收手，把当前结果当结局，不再问模型。 */
    @Test
    public void shouldStopAfterPostToolUseRequestsPrevention() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.POST_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder().preventContinuation(true).build();
            }
        });

        GuardedTrace trace = run(modelCallsThenAnswers("{\"limit\":1}", "这句不该出现"),
                registryWith(readTool()), null, hooks, 5);

        assertEquals(1, trace.getRoundCount(), "收手之后没有第二轮");
        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
    }

    // ---------- Stop 的续写 ----------

    /** Stop 能续写一轮，但第二次请求被吞：无限续写在机制上不可能。 */
    @Test
    public void shouldAllowExactlyOneForcedContinuation() {
        final List<Boolean> flags = new ArrayList<Boolean>();
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.STOP, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                flags.add(context.isStopHookActive());
                return HookResult.builder()
                        .forceContinue(ChatMessage.user("再检查一遍"))
                        .build();
            }
        });

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse("第一次答复", FinishReason.STOP, new TokenUsage(10, 5));
        client.enqueueResponse("第二次答复", FinishReason.STOP, new TokenUsage(10, 5));

        GuardedTrace trace = run(client, new ToolRegistry(), null, hooks, 5);

        assertEquals(Arrays.asList(false, true), flags,
                "第二次进 Stop 时 stopHookActive 已置位");
        assertEquals(2, trace.getRoundCount());
        assertEquals("第二次答复", trace.getFinalAnswer());
    }

    /** UserPromptSubmit 的 additionalContext 进得了历史，用户消息本身不被替换。 */
    @Test
    public void shouldAppendUserPromptContextWithoutReplacingUserMessage() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.USER_PROMPT_SUBMIT, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder()
                        .addContext(ChatMessage.system("当前场景有 2 台设备"))
                        .build();
            }
        });

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse("知道了", FinishReason.STOP, new TokenUsage(10, 5));

        run(client, new ToolRegistry(), null, hooks, 5);

        List<ChatMessage> sent = client.getLastRequest().getMessages();
        assertEquals(3, sent.size(), "system 提示 + 用户消息 + Hook 补的 system");
        assertEquals("检查设备", sent.get(1).getContent(), "用户原话没被改掉");
        assertEquals("当前场景有 2 台设备", sent.get(2).getContent());
    }

    // ---------- 脚手架 ----------

    private HookCallback recorder(final String label) {
        return new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                order.add(label);
                return HookResult.noop();
            }
        };
    }

    private static HookCallback thrower(final String message) {
        return new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                throw new IllegalStateException(message);
            }
        };
    }

    private static HookCallback behaviorHook(final PermissionBehavior behavior) {
        return new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder().permissionBehavior(behavior).build();
            }
        };
    }

    private static ApprovalProvider approver(final PermissionBehavior behavior) {
        return new ApprovalProvider() {
            @Override
            public PermissionDecision decide(PermissionRequest request) {
                return new PermissionDecision(behavior, "运维已表态", "human:ops");
            }
        };
    }

    private ToolDefinition readTool() {
        return new ToolDefinition("read_device", "查设备", "{\"type\":\"object\"}",
                ToolEffect.READ, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                order.add("handler");
                return ToolExecutionResult.success("北区 2 台设备");
            }
        });
    }

    private ToolDefinition deleteTool() {
        return new ToolDefinition("delete_device", "删除设备", "{\"type\":\"object\"}",
                ToolEffect.DESTRUCTIVE, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                order.add("handler");
                return ToolExecutionResult.success("已删除");
            }
        });
    }

    private static ToolRegistry registryWith(ToolDefinition definition) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(definition);
        return registry;
    }

    /** 一轮 read_device 调用，接一句最终答复。 */
    private static FakeModelClient modelCallsThenAnswers(String rawArguments, String answer) {
        return modelCallsToolThenAnswers("read_device", rawArguments, answer);
    }

    private static FakeModelClient modelCallsToolThenAnswers(String toolName,
                                                             String rawArguments,
                                                             String answer) {
        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", toolName, rawArguments)),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        client.enqueueResponse(answer, FinishReason.STOP, new TokenUsage(120, 25));
        return client;
    }

    private static FakeModelClient modelAnswers(String answer) {
        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(answer, FinishReason.STOP, new TokenUsage(10, 5));
        return client;
    }

    private GuardedTrace run(FakeModelClient client,
                             ToolRegistry registry,
                             PermissionPolicy policy,
                             HookRegistry hooks,
                             int maxRounds) {
        HookedAgentLoop loop = new HookedAgentLoop("fake-model", client, registry,
                context(), maxRounds, 2000L, TraceIdGenerator.fixed("trace-007"),
                policy, hooks);
        try {
            return loop.run("你是设备助手", "检查设备");
        } finally {
            loop.shutdown();
        }
    }

    private static ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("gate-99", DeviceType.FENCE);
        Set<String> protectedIds = new LinkedHashSet<String>();
        protectedIds.add("gate-99");
        return new ToolContext("operator-1", new SceneSnapshot(20, 20, 10, devices, protectedIds));
    }

    /** 找出唯一那轮工具调用。 */
    private static RoundTrace toolRoundOf(GuardedTrace trace) {
        for (RoundTrace round : trace.getRounds()) {
            if (round.hasToolCall()) {
                return round;
            }
        }
        return null;
    }
}
