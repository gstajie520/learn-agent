package learn.agent.llm.plan;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import com.fasterxml.jackson.databind.JsonNode;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRequest;
import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.ModelClient;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.hook.HookCallback;
import learn.agent.llm.hook.HookContext;
import learn.agent.llm.hook.HookEvent;
import learn.agent.llm.hook.HookRegistry;
import learn.agent.llm.hook.HookResult;
import learn.agent.llm.permission.ApprovalProvider;
import learn.agent.llm.permission.AuditSink;
import learn.agent.llm.permission.PermissionBehavior;
import learn.agent.llm.permission.PermissionDecision;
import learn.agent.llm.permission.PermissionPolicy;
import learn.agent.llm.permission.PermissionRequest;
import learn.agent.llm.permission.PermissionRule;
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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link SubagentTool} 的行为测试。
 *
 * <p>每个测试的注释说明它在证明哪条规则。本课的规则集中在一件事上：
 * <b>子 Agent 隔离的是历史，不是权限。</b>八条边界里有五条在守这句话的后半句。</p>
 */
public class SubagentToolTest {

    /** 场景：20x20，上限 5，cam-01 受保护。 */
    private static SceneSnapshot scene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-01", DeviceType.RADAR);
        devices.put("cam-01", DeviceType.CAMERA);
        return new SceneSnapshot(20, 20, 5, devices, Collections.singleton("cam-01"));
    }

    private static ToolContext context() {
        return new ToolContext("parent-user", scene());
    }

    /** 直接调 task 工具，跳过父循环 —— 本测试类关注的是委派本身。 */
    private static ToolExecutionResult invokeTask(SubagentTool tool, String description) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(tool.getToolDefinition());
        String args = "{\"description\":\"" + description + "\"}";
        ToolCall call = new ToolCall("call-1", SubagentTool.TOOL_NAME, args);
        PreparedToolCall prepared = registry.prepare(call);
        if (prepared.isFailed()) {
            return prepared.getError();
        }
        return registry.invoke(prepared, context());
    }

    /** 一个只读工具，执行时把调用记进 trace。 */
    private static ToolDefinition inspectTool(final List<String> trace) {
        return new ToolDefinition("inspect", "查看证据", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        trace.add("handler:inspect");
                        return ToolExecutionResult.success("证据：radar-01 在线");
                    }
                });
    }

    /** 子 Agent 的典型剧本：先查一次证据，再给结论。 */
    private static FakeModelClient childModel() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(ToolCallCodec.encode(new ToolCall("c1", "inspect", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("查过了：radar-01 在线。", FinishReason.STOP, new TokenUsage(150, 30));
        return fake;
    }

    private static SubagentConfig config(final ModelClient model, final ToolRegistry tools) {
        return new SubagentConfig(
                new ModelClientFactory() {
                    @Override
                    public ModelClient create() {
                        return model;
                    }
                },
                new ToolRegistryFactory() {
                    @Override
                    public ToolRegistry create() {
                        return tools;
                    }
                },
                new HookRegistry(), new PermissionPolicy());
    }

    @Test
    @DisplayName("父 Agent 只拿到最终结论，看不到子 Agent 的中间轨迹")
    void shouldReturnOnlyFinalConclusion() {
        // 这是本课存在的理由：子 Agent 读文件、搜符号的几十轮结果不该进父上下文。
        List<String> trace = new ArrayList<String>();
        ToolRegistry childTools = new ToolRegistry();
        childTools.register(inspectTool(trace));

        SubagentTool tool = new SubagentTool(config(childModel(), childTools));
        ToolExecutionResult result = invokeTask(tool, "检查 radar-01 状态");

        assertFalse(result.isError());
        assertEquals("查过了：radar-01 在线。", result.getContent());
        // 子 Agent 确实调过工具，但那条轨迹没有出现在父 Agent 拿到的结果里。
        assertTrue(trace.contains("handler:inspect"));
        assertFalse(result.getContent().contains("证据：radar-01 在线"));
    }

    @Test
    @DisplayName("子 Agent 的历史是全新的，不含父 Agent 的任何消息")
    void shouldStartChildWithFreshHistory() {
        // 隔离历史是本课的核心机制。子 Agent 的第一条 user 消息必须是委派描述本身。
        ToolRegistry childTools = new ToolRegistry();
        childTools.register(inspectTool(new ArrayList<String>()));
        FakeModelClient fake = childModel();

        SubagentTool tool = new SubagentTool(config(fake, childTools));
        invokeTask(tool, "检查 radar-01 状态");

        ChatRequest first = fake.getRequest(0);
        // 恰好两条：system 是子 Agent 的职责提示，user 是委派描述。
        assertEquals(2, first.getMessages().size());
        assertEquals(SubagentConfig.DEFAULT_SYSTEM_PROMPT, first.getMessages().get(0).getContent());
        assertEquals("检查 radar-01 状态", first.getMessages().get(1).getContent());
    }

    @Test
    @DisplayName("每次委派都新建模型和工具注册表")
    void shouldCreateFreshDependenciesPerTask() {
        // 用工厂而不是实例的理由：两次委派共享一个 FakeModelClient 的话，
        // 第二次会接着读第一次剩下的响应队列，两个无关子任务互相污染。
        final List<ModelClient> models = new ArrayList<ModelClient>();
        final List<ToolRegistry> registries = new ArrayList<ToolRegistry>();

        SubagentConfig config = new SubagentConfig(
                new ModelClientFactory() {
                    @Override
                    public ModelClient create() {
                        FakeModelClient fake = new FakeModelClient();
                        fake.enqueueResponse("结论", FinishReason.STOP, new TokenUsage(10, 5));
                        models.add(fake);
                        return fake;
                    }
                },
                new ToolRegistryFactory() {
                    @Override
                    public ToolRegistry create() {
                        ToolRegistry registry = new ToolRegistry();
                        registries.add(registry);
                        return registry;
                    }
                },
                new HookRegistry(), new PermissionPolicy());

        SubagentTool tool = new SubagentTool(config);
        invokeTask(tool, "第一个任务");
        invokeTask(tool, "第二个任务");

        assertEquals(2, models.size());
        assertEquals(2, registries.size());
        assertNotSame(models.get(0), models.get(1));
        assertNotSame(registries.get(0), registries.get(1));
    }

    @Test
    @DisplayName("子 Agent 拿不到 task 工具，递归委派在配置期就被拦下")
    void shouldRejectRecursiveDelegation() {
        // 允许递归委派会让一次调用长出一棵深度不可控的 Agent 树，
        // 成本和结束时间都没法预估。所以这条在配置期就拦，不留到运行期。
        final ToolRegistry pollutedTools = new ToolRegistry();
        pollutedTools.register(new ToolDefinition(SubagentTool.TOOL_NAME, "冒充的 task",
                "{}", ToolEffect.READ, new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        return ToolExecutionResult.success("不该被执行");
                    }
                }));

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("结论", FinishReason.STOP, new TokenUsage(10, 5));

        SubagentTool tool = new SubagentTool(config(fake, pollutedTools));
        ToolExecutionResult result = invokeTask(tool, "试图递归");

        assertTrue(result.isError());
        assertEquals("subagent_configuration_error", result.getErrorCode());
        // 模型一次都没被调用：拦在建循环之前，不是等它跑起来再拦。
        assertEquals(0, fake.getCallCount());
    }

    @Test
    @DisplayName("父 Agent 的权限策略对子 Agent 同样生效")
    void shouldShareParentPermissionPolicy() {
        // 本课最重要的一条边界：隔离的是历史，不是权限。
        // 如果子 Agent 能绕过父策略，那 task 就成了提权工具 ——
        // 模型只要把想做的事包装成一次委派，就能跳过全部裁决。
        final List<PermissionDecision> audited = new ArrayList<PermissionDecision>();
        PermissionPolicy policy = new PermissionPolicy(
                Collections.singletonList(new PermissionRule("deny-inspect",
                        PermissionBehavior.DENY, "测试用：一律拒绝 inspect",
                        new PermissionRule.Matcher() {
                            @Override
                            public boolean matches(PermissionRequest request) {
                                return "inspect".equals(
                                        request.getPrepared().getDefinition().getName());
                            }
                        })),
                (ApprovalProvider) null,
                new AuditSink() {
                    @Override
                    public void record(PermissionRequest request, PermissionDecision decision) {
                        audited.add(decision);
                    }
                });

        List<String> trace = new ArrayList<String>();
        ToolRegistry childTools = new ToolRegistry();
        childTools.register(inspectTool(trace));

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(ToolCallCodec.encode(new ToolCall("c1", "inspect", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("被拒绝了，我改用别的办法。", FinishReason.STOP, new TokenUsage(120, 20));

        SubagentConfig config = new SubagentConfig(
                new ModelClientFactory() {
                    @Override
                    public ModelClient create() {
                        return fake;
                    }
                },
                new ToolRegistryFactory() {
                    @Override
                    public ToolRegistry create() {
                        return childTools;
                    }
                },
                new HookRegistry(), policy);

        SubagentTool tool = new SubagentTool(config);
        ToolExecutionResult result = invokeTask(tool, "检查设备");

        assertFalse(result.isError());
        // handler 一次都没执行：父策略在子 Agent 里照样拦得住。
        assertFalse(trace.contains("handler:inspect"));
        // 而且留下了审计记录 —— 子 Agent 的操作同样可追溯。
        assertEquals(1, audited.size());
        assertEquals(PermissionBehavior.DENY, audited.get(0).getBehavior());
    }

    @Test
    @DisplayName("父 Agent 的 Hook 对子 Agent 同样触发")
    void shouldShareParentHooks() {
        // 和权限同理：Hook 是治理边界，不能因为换了一层循环就失效。
        // 否则「工具返回的手机号要脱敏」这类规则在子 Agent 里就全漏了。
        final List<String> fired = new ArrayList<String>();
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext ctx) {
                fired.add("pre:" + ctx.getPrepared().getDefinition().getName());
                return HookResult.noop();
            }
        });

        ToolRegistry childTools = new ToolRegistry();
        childTools.register(inspectTool(new ArrayList<String>()));

        SubagentConfig config = new SubagentConfig(
                new ModelClientFactory() {
                    @Override
                    public ModelClient create() {
                        return childModel();
                    }
                },
                new ToolRegistryFactory() {
                    @Override
                    public ToolRegistry create() {
                        return childTools;
                    }
                },
                hooks, new PermissionPolicy());

        invokeTask(new SubagentTool(config), "检查设备");

        assertEquals(Collections.singletonList("pre:inspect"), fired);
    }

    @Test
    @DisplayName("子 Agent 用光轮数：回结构化错误，不回最后一条工具结果")
    void shouldReportTurnLimitWithoutLeakingToolResult() {
        // 关键在后半句。回最后一条工具结果的话，父 Agent 会把一段中间产物
        // 当成子任务的结论 —— 它看不出这是「没做完」还是「做完了」。
        ToolRegistry childTools = new ToolRegistry();
        childTools.register(inspectTool(new ArrayList<String>()));

        // 一个永远只调工具、从不给结论的模型。
        FakeModelClient fake = new FakeModelClient();
        for (int i = 0; i < SubagentConfig.MAX_SUBAGENT_ROUNDS + 5; i++) {
            fake.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall("c" + i, "inspect", "{}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        }

        SubagentTool tool = new SubagentTool(config(fake, childTools));
        ToolExecutionResult result = invokeTask(tool, "永远做不完的任务");

        assertTrue(result.isError());
        assertEquals("subagent_turn_limit", result.getErrorCode());
        // 最后一条工具结果没有泄漏进父上下文。
        assertFalse(result.getContent().contains("证据：radar-01 在线"));
    }

    @Test
    @DisplayName("子 Agent 内部异常被清洗，不把栈信息回传父模型")
    void shouldSanitizeChildFailure() {
        // 异常文本里可能有内部路径、SQL、配置键名。它进了父上下文就等于
        // 进了模型可见范围，而模型下一轮可能把它复述给用户。
        SubagentConfig config = new SubagentConfig(
                new ModelClientFactory() {
                    @Override
                    public ModelClient create() {
                        throw new IllegalStateException(
                                "内部细节：jdbc:mysql://10.0.0.7:3306/scene 密码错误");
                    }
                },
                new ToolRegistryFactory() {
                    @Override
                    public ToolRegistry create() {
                        return new ToolRegistry();
                    }
                },
                new HookRegistry(), new PermissionPolicy());

        SubagentTool tool = new SubagentTool(config);
        ToolExecutionResult result = invokeTask(tool, "会炸的任务");

        assertTrue(result.isError());
        assertEquals("subagent_execution_error", result.getErrorCode());
        assertFalse(result.getContent().contains("jdbc"));
        assertFalse(result.getContent().contains("10.0.0.7"));
    }

    @Test
    @DisplayName("空描述被参数校验拦下")
    void shouldRejectBlankDescription() {
        // 空描述意味着「去做点什么」。子 Agent 会自己编一个任务，
        // 而它编的任务和父 Agent 想要的没有任何关系。
        ToolRegistry childTools = new ToolRegistry();
        SubagentTool tool = new SubagentTool(config(childModel(), childTools));

        ToolExecutionResult result = invokeTask(tool, "   ");

        assertTrue(result.isError());
        assertEquals("invalid_arguments", result.getErrorCode());
    }

    @Test
    @DisplayName("maxRounds 只能收紧，不能放大")
    void shouldOnlyAllowTighteningMaxRounds() {
        // 上限是成本闸门。允许调用方放大，等于允许它把闸门抬高到任意高度 ——
        // 那这个闸门就不存在了。
        ModelClientFactory models = new ModelClientFactory() {
            @Override
            public ModelClient create() {
                return new FakeModelClient();
            }
        };
        ToolRegistryFactory tools = new ToolRegistryFactory() {
            @Override
            public ToolRegistry create() {
                return new ToolRegistry();
            }
        };

        // 收紧允许。
        SubagentConfig tightened = new SubagentConfig(models, tools, new HookRegistry(), new PermissionPolicy(),
                SubagentConfig.DEFAULT_SYSTEM_PROMPT, 5, 1000L);
        assertEquals(5, tightened.getMaxRounds());

        // 放大拒绝。
        assertThrows(IllegalArgumentException.class,
                () -> new SubagentConfig(models, tools, new HookRegistry(), new PermissionPolicy(),
                        SubagentConfig.DEFAULT_SYSTEM_PROMPT,
                        SubagentConfig.MAX_SUBAGENT_ROUNDS + 1, 1000L));
    }

    @Test
    @DisplayName("配置期就拒绝空工厂、空 Hook 注册表、空策略和空提示词")
    void shouldValidateConfigEagerly() {
        ModelClientFactory models = new ModelClientFactory() {
            @Override
            public ModelClient create() {
                return new FakeModelClient();
            }
        };
        ToolRegistryFactory tools = new ToolRegistryFactory() {
            @Override
            public ToolRegistry create() {
                return new ToolRegistry();
            }
        };

        assertThrows(IllegalArgumentException.class,
                () -> new SubagentConfig(null, tools, new HookRegistry(), new PermissionPolicy()));
        assertThrows(IllegalArgumentException.class,
                () -> new SubagentConfig(models, null, new HookRegistry(), new PermissionPolicy()));
        // hooks 为 null 不允许：父 Agent 没配 Hook 时应该传空注册表，
        // 而不是传 null —— 后者读起来像「子 Agent 不受 Hook 管」。
        // 两个参数分别单独试，否则测不出是哪一个触发的异常。
        assertThrows(IllegalArgumentException.class,
                () -> new SubagentConfig(models, tools, null, new PermissionPolicy()));
        // policy 为 null 同样不允许，理由完全对称。这条曾经是允许的，
        // 而它配合「循环在 policy 为 null 时跳过整段裁决」就是一条提权路径：
        // 父 Agent 有策略，调用方给子 Agent 传 null，裁决就整段消失了。
        assertThrows(IllegalArgumentException.class,
                () -> new SubagentConfig(models, tools, new HookRegistry(), null));
        assertThrows(IllegalArgumentException.class,
                () -> new SubagentConfig(models, tools, new HookRegistry(), new PermissionPolicy(), "  ", 5, 1000L));
    }

    @Test
    @DisplayName("子 Agent 共享父 Agent 的 identity 和场景")
    void shouldShareParentContext() {
        // 隔离历史不等于换一个身份。子 Agent 以父 Agent 的身份操作，
        // 审计里看到的也应该是同一个人 —— 否则「谁干的」就断链了。
        final List<ToolContext> observed = new ArrayList<ToolContext>();
        ToolRegistry childTools = new ToolRegistry();
        childTools.register(new ToolDefinition("inspect", "查看", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        observed.add(ctx);
                        return ToolExecutionResult.success("ok");
                    }
                }));

        SubagentTool tool = new SubagentTool(config(childModel(), childTools));
        invokeTask(tool, "检查设备");

        assertEquals(1, observed.size());
        assertEquals("parent-user", observed.get(0).getIdentity());
        assertTrue(observed.get(0).getScene().hasDevice("radar-01"));
    }

    @Test
    @DisplayName("task 的副作用等级是 EXTERNAL 语义：不需要人工确认，但也不是只读")
    void shouldDeclareWriteEffect() {
        // 教材里 task 标的是 external。Java 侧 ToolEffect 只有 READ/WRITE/DESTRUCTIVE，
        // 取 WRITE：它不可逆的部分由子 Agent 自己调的工具承担，而那些工具
        // 各自都要过同一套裁决。把 task 本身标成 DESTRUCTIVE 会让每次委派都弹确认框。
        ToolRegistry childTools = new ToolRegistry();
        SubagentTool tool = new SubagentTool(config(childModel(), childTools));

        assertEquals(ToolEffect.WRITE, tool.getToolDefinition().getEffect());
        assertFalse(tool.getToolDefinition().getEffect().requiresConfirmation());
    }
}
