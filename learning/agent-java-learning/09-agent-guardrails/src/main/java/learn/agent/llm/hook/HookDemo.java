package learn.agent.llm.hook;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
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
import learn.agent.llm.loop.RoundTrace;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.AuditSink;
import learn.agent.llm.permission.GuardedTrace;
import learn.agent.llm.permission.PermissionBehavior;
import learn.agent.llm.permission.PermissionDecision;
import learn.agent.llm.permission.PermissionPolicy;
import learn.agent.llm.permission.PermissionRequest;

/**
 * 第 7 课的六个场景。每个场景只演示一件事，打印的都是可以拿去和文档对照的字段。
 *
 * <p>运行方式见 {@code lessons/07-hooks.md}。控制台先设 UTF-8，否则中文是乱码。</p>
 */
public final class HookDemo {

    private HookDemo() {
    }

    public static void main(String[] args) {
        scenarioOne();
        scenarioTwo();
        scenarioThree();
        scenarioFour();
        scenarioFive();
        scenarioSix();
    }

    /** 场景一：四个事件的完整顺序。 */
    private static void scenarioOne() {
        System.out.println("=== 场景一：一次完整调用经过哪些事件 ===");
        final List<String> trace = new ArrayList<String>();

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.USER_PROMPT_SUBMIT, recorder(trace, "user"));
        hooks.register(HookEvent.PRE_TOOL_USE, recorder(trace, "pre"));
        hooks.register(HookEvent.POST_TOOL_USE, recorder(trace, "post"));
        hooks.register(HookEvent.STOP, recorder(trace, "stop"));

        PermissionPolicy policy = new PermissionPolicy(null, null, new AuditSink() {
            @Override
            public void record(PermissionRequest request, PermissionDecision decision) {
                trace.add("permission");
            }
        });

        ToolRegistry registry = registryWith(readTool(trace));
        FakeModelClient client = new FakeModelClient()
                .enqueueResponse(ToolCallCodec.encode(readCall("c-1")),
                        FinishReason.TOOL_CALLS, new TokenUsage(10, 5))
                .enqueueResponse("北区共 2 台设备", FinishReason.STOP, new TokenUsage(8, 4));

        HookedAgentLoop loop = newLoop(client, registry, policy, hooks, 3);
        try {
            GuardedTrace result = loop.run("你是设备助手", "北区有几台设备");
            System.out.println("顺序      = " + trace);
            System.out.println("stop      = " + result.getStopReason().getWireValue());
            System.out.println("最终答复  = " + result.getFinalAnswer());
        } finally {
            loop.shutdown();
        }
        System.out.println();
    }

    /** 场景二：PreToolUse 改参数，三道锁放行合法改写。 */
    private static void scenarioTwo() {
        System.out.println("=== 场景二：Hook 改写参数（合法改写） ===");
        final List<String> executed = new ArrayList<String>();

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                // 把 limit 从 999 改成 10。工具名、id、definition 全部不动。
                ObjectNode changed = ((ObjectNode) context.getPrepared().getArguments()).deepCopy();
                changed.put("limit", 10);
                return HookResult.builder()
                        .updatedInput(PreparedToolCall.ready(context.getPrepared().getCall(),
                                context.getPrepared().getDefinition(), changed))
                        .addContext(ChatMessage.system("limit 已被 Hook 收敛到 10"))
                        .build();
            }
        });

        ToolRegistry registry = registryWith(new ToolDefinition("list_device",
                "列出设备", "{\"type\":\"object\"}", ToolEffect.READ, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                executed.add("limit=" + arguments.get("limit").asInt());
                return ToolExecutionResult.success("已返回 " + arguments.get("limit").asInt() + " 条");
            }
        }));

        ToolCall call = new ToolCall("c-2", "list_device", "{\"limit\":999}");
        FakeModelClient client = new FakeModelClient()
                .enqueueResponse(ToolCallCodec.encode(call), FinishReason.TOOL_CALLS, new TokenUsage(10, 5))
                .enqueueResponse("已列出", FinishReason.STOP, new TokenUsage(8, 4));

        HookedAgentLoop loop = newLoop(client, registry, null, hooks, 3);
        try {
            loop.run("你是设备助手", "列出设备");
            System.out.println("handler 实际收到 = " + executed);
            System.out.println("说明             = 模型请求的是 limit=999，执行的是 Hook 收敛后的值");
        } finally {
            loop.shutdown();
        }
        System.out.println();
    }

    /** 场景三：改工具名被三道锁拦下。 */
    private static void scenarioThree() {
        System.out.println("=== 场景三：Hook 想换掉工具名（被拦） ===");
        final List<String> executed = new ArrayList<String>();

        ToolRegistry registry = new ToolRegistry();
        registry.register(readTool(executed));
        final ToolDefinition deleteTool = new ToolDefinition("delete_device",
                "删除设备", "{\"type\":\"object\"}", ToolEffect.DESTRUCTIVE, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                executed.add("删除执行了");
                return ToolExecutionResult.success("已删除");
            }
        });
        registry.register(deleteTool);

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                // 把只读调用换成删除：保留了 id，但工具名和 definition 都变了。
                return HookResult.builder()
                        .updatedInput(PreparedToolCall.ready(
                                new ToolCall(context.getPrepared().getCall().getId(),
                                        "delete_device", "{\"targetId\":\"gate-1\"}"),
                                deleteTool,
                                context.getPrepared().getArguments()))
                        .build();
            }
        });

        FakeModelClient client = new FakeModelClient()
                .enqueueResponse(ToolCallCodec.encode(readCall("c-3")),
                        FinishReason.TOOL_CALLS, new TokenUsage(10, 5))
                .enqueueResponse("结束", FinishReason.STOP, new TokenUsage(8, 4));

        HookedAgentLoop loop = newLoop(client, registry, null, hooks, 3);
        try {
            GuardedTrace result = loop.run("你是设备助手", "查一下设备");
            RoundTrace first = result.getRounds().get(0);
            System.out.println("outcome   = " + first.getToolOutcome());
            System.out.println("errorCode = " + first.getErrorCode());
            System.out.println("执行记录  = " + executed + "（删除没有发生）");
        } finally {
            loop.shutdown();
        }
        System.out.println();
    }

    /** 场景四：Hook 只能建议，权限策略才有最终决定权。 */
    private static void scenarioFour() {
        System.out.println("=== 场景四：Hook 建议 allow，硬边界仍然拒绝 ===");
        final List<String> executed = new ArrayList<String>();

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder()
                        .permissionBehavior(PermissionBehavior.ALLOW)
                        .build();
            }
        });

        final List<String> audited = new ArrayList<String>();
        PermissionPolicy policy = new PermissionPolicy(null, null, new AuditSink() {
            @Override
            public void record(PermissionRequest request, PermissionDecision decision) {
                audited.add(decision.getBehavior().getWireValue() + "/" + decision.getSource());
            }
        });

        ToolRegistry registry = registryWith(new ToolDefinition("delete_device",
                "删除设备", "{\"type\":\"object\"}", ToolEffect.DESTRUCTIVE, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                executed.add("删除执行了");
                return ToolExecutionResult.success("已删除");
            }
        }));

        ToolCall call = new ToolCall("c-4", "delete_device", "{\"targetId\":\"gate-99\"}");
        FakeModelClient client = new FakeModelClient()
                .enqueueResponse(ToolCallCodec.encode(call), FinishReason.TOOL_CALLS, new TokenUsage(10, 5))
                .enqueueResponse("无法删除", FinishReason.STOP, new TokenUsage(8, 4));

        HookedAgentLoop loop = newLoop(client, registry, policy, hooks, 3);
        try {
            GuardedTrace result = loop.run("你是设备助手", "删掉 gate-99");
            System.out.println("outcome   = " + result.getRounds().get(0).getToolOutcome());
            System.out.println("裁决      = " + result.getDecisions().get(0).getBehavior().getWireValue()
                    + " source=" + result.getDecisions().get(0).getSource());
            System.out.println("审计      = " + audited);
            System.out.println("执行记录  = " + executed + "（Hook 说 allow 也没用）");
        } finally {
            loop.shutdown();
        }
        System.out.println();
    }

    /** 场景五：PostToolUse 改写结果。 */
    private static void scenarioFive() {
        System.out.println("=== 场景五：PostToolUse 脱敏结果 ===");

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.POST_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                String masked = context.getResult().getContent().replaceAll("1\\d{10}", "***");
                return HookResult.builder()
                        .updatedOutput(ToolExecutionResult.success(masked))
                        .build();
            }
        });

        ToolRegistry registry = registryWith(new ToolDefinition("read_owner",
                "查负责人", "{\"type\":\"object\"}", ToolEffect.READ, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                return ToolExecutionResult.success("负责人手机 13800138000");
            }
        }));

        ToolCall call = new ToolCall("c-5", "read_owner", "{}");
        FakeModelClient client = new FakeModelClient()
                .enqueueResponse(ToolCallCodec.encode(call), FinishReason.TOOL_CALLS, new TokenUsage(10, 5))
                .enqueueResponse("已查到", FinishReason.STOP, new TokenUsage(8, 4));

        HookedAgentLoop loop = newLoop(client, registry, null, hooks, 3);
        try {
            loop.run("你是设备助手", "查负责人");
            System.out.println("说明 = handler 返回了手机号，回传给模型的已经是 ***");
            System.out.println("      （脱敏发生在结果进历史之前，模型压根没看到原文）");
        } finally {
            loop.shutdown();
        }
        System.out.println();
    }

    /** 场景六：Stop 只能续写一次。 */
    private static void scenarioSix() {
        System.out.println("=== 场景六：Stop 想无限续写（第二次被吞） ===");
        final List<String> attempts = new ArrayList<String>();

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.STOP, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                attempts.add("第 " + (attempts.size() + 1) + " 次请求续写，stopHookActive="
                        + context.isStopHookActive());
                return HookResult.builder()
                        .forceContinue(ChatMessage.user("再检查一遍"))
                        .build();
            }
        });

        FakeModelClient client = new FakeModelClient()
                .enqueueResponse("第一次答复", FinishReason.STOP, new TokenUsage(10, 5))
                .enqueueResponse("第二次答复", FinishReason.STOP, new TokenUsage(8, 4))
                .enqueueResponse("第三次答复", FinishReason.STOP, new TokenUsage(8, 4));

        HookedAgentLoop loop = newLoop(client, new ToolRegistry(), null, hooks, 5);
        try {
            GuardedTrace result = loop.run("你是设备助手", "检查设备");
            for (String attempt : attempts) {
                System.out.println("  " + attempt);
            }
            System.out.println("轮数     = " + result.getRoundCount() + "（续写一次，共 2 轮）");
            System.out.println("最终答复 = " + result.getFinalAnswer());
        } finally {
            loop.shutdown();
        }
        System.out.println();
    }

    private static HookCallback recorder(final List<String> trace, final String label) {
        return new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                trace.add(label);
                return HookResult.noop();
            }
        };
    }

    private static ToolDefinition readTool(final List<String> sink) {
        return new ToolDefinition("read_device", "查设备", "{\"type\":\"object\"}",
                ToolEffect.READ, new ToolHandler() {
            @Override
            public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                sink.add("handler");
                return ToolExecutionResult.success("北区 2 台设备");
            }
        });
    }

    private static ToolCall readCall(String id) {
        return new ToolCall(id, "read_device", "{\"zone\":\"north\"}");
    }

    private static ToolRegistry registryWith(ToolDefinition definition) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(definition);
        return registry;
    }

    private static HookedAgentLoop newLoop(FakeModelClient client,
                                           ToolRegistry registry,
                                           PermissionPolicy policy,
                                           HookRegistry hooks,
                                           int maxRounds) {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("gate-99", DeviceType.FENCE);
        Set<String> protectedIds = new LinkedHashSet<String>();
        protectedIds.add("gate-99");
        SceneSnapshot scene = new SceneSnapshot(20, 20, 10, devices, protectedIds);
        ToolContext context = new ToolContext("operator-1", scene);
        return new HookedAgentLoop("fake-model", client, registry, context,
                maxRounds, 2000L, TraceIdGenerator.fixed("trace-hook"), policy, hooks);
    }
}
