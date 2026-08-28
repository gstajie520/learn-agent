package learn.agent.llm.hook;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

import org.junit.jupiter.api.Test;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.structured.ValidationResult;
import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolArgumentValidator;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;
import learn.agent.llm.tool.ToolRegistry;
import learn.agent.llm.permission.PermissionBehavior;

/**
 * {@link HookRegistry} 的合并语义与 {@code updatedInput} 三道锁。
 *
 * <p>这些测试断言的是<b>机制</b>：多个回调怎么合并、哪些改写被拒、哪些字段属于哪个事件。
 * 循环层面的编排在 {@code HookedAgentLoopTest} 里。</p>
 */
class HookRegistryTest {

    // ---------- 事件与字段归属 ----------

    /** 每个事件只允许自己的字段，Stop 返回 updatedInput 是写错了不是无害。 */
    @Test
    void shouldRejectFieldsOwnedByAnotherEvent() {
        HookResult result = HookResult.builder()
                .permissionBehavior(PermissionBehavior.DENY)
                .build();

        result.validateFor(HookEvent.PRE_TOOL_USE);
        HookContractException e = assertThrows(HookContractException.class,
                () -> result.validateFor(HookEvent.STOP));
        assertTrue(e.getMessage().contains("permissionBehavior"));
    }

    /** UserPromptSubmit 必须拿到 user 消息，system 消息构造不出这个上下文。 */
    @Test
    void shouldRequireUserMessageForUserPromptSubmit() {
        assertThrows(HookContractException.class,
                () -> HookContext.userPromptSubmit(ChatMessage.system("我是系统")));
    }

    /** PreToolUse 拒绝准备失败的调用：没有合法参数就没什么可给 Hook 看。 */
    @Test
    void shouldRejectFailedPreparedCallInPreToolUse() {
        PreparedToolCall failed = registry().prepare(new ToolCall("c1", "no_such_tool", "{}"));
        assertThrows(HookContractException.class, () -> HookContext.preToolUse(failed));
    }

    /** additionalContext 只收 system 消息，Hook 不能冒充用户说话。 */
    @Test
    void shouldRejectNonSystemAdditionalContext() {
        assertThrows(HookContractException.class,
                () -> HookResult.builder().addContext(ChatMessage.user("我是用户")));
    }

    /** blockingError 必须是 error 态，否则 Hook 能伪造一次「执行成功」。 */
    @Test
    void shouldRejectSuccessResultAsBlockingError() {
        assertThrows(HookContractException.class,
                () -> HookResult.builder().blockingError(ToolExecutionResult.success("其实没跑")));
    }

    /** forceContinue 只收 user 消息，system 消息模型可能压根不接话。 */
    @Test
    void shouldRejectSystemMessageAsForceContinue() {
        assertThrows(HookContractException.class,
                () -> HookResult.builder().forceContinue(ChatMessage.system("继续")));
    }

    /** 回调返回 null 直接违约，不当成 noop 静默放过。 */
    @Test
    void shouldRejectNullReturnFromCallback() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.STOP, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return null;
            }
        });
        assertThrows(HookContractException.class,
                () -> hooks.runStop(Collections.<ChatMessage>emptyList(), false));
    }

    // ---------- 合并语义 ----------

    /** 权限建议按 deny > ask > allow > passthrough 取最严，与注册顺序无关。 */
    @Test
    void shouldMergePermissionRecommendationToStrictest() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, behaviorHook(PermissionBehavior.ALLOW));
        hooks.register(HookEvent.PRE_TOOL_USE, behaviorHook(PermissionBehavior.DENY));
        hooks.register(HookEvent.PRE_TOOL_USE, behaviorHook(PermissionBehavior.ASK));

        HookResult merged = hooks.runPreTool(readyCall());
        assertEquals(PermissionBehavior.DENY, merged.getPermissionBehavior());
    }

    /** 这个优先级和第 6 课的三轮扫描不是同一个：passthrough 在这里参与比较且最弱。 */
    @Test
    void shouldTreatPassthroughAsWeakestInHookMerge() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, behaviorHook(PermissionBehavior.PASSTHROUGH));
        hooks.register(HookEvent.PRE_TOOL_USE, behaviorHook(PermissionBehavior.ALLOW));

        assertEquals(PermissionBehavior.ALLOW, hooks.runPreTool(readyCall()).getPermissionBehavior());
    }

    /** additionalContext 是累积的，不是后者覆盖前者。 */
    @Test
    void shouldAccumulateAdditionalContextFromAllCallbacks() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.STOP, contextHook("第一条"));
        hooks.register(HookEvent.STOP, contextHook("第二条"));

        List<ChatMessage> merged =
                hooks.runStop(Collections.<ChatMessage>emptyList(), false).getAdditionalContext();
        assertEquals(2, merged.size());
        assertEquals("第一条", merged.get(0).getContent());
        assertEquals("第二条", merged.get(1).getContent());
    }

    /** blockingError 短路：后面的回调不再执行。 */
    @Test
    void shouldStopRunningCallbacksAfterBlockingError() {
        final List<String> seen = new ArrayList<String>();
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                seen.add("第一个");
                return HookResult.builder()
                        .blockingError(ToolExecutionResult.error("blocked", "不许"))
                        .build();
            }
        });
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                seen.add("第二个");
                return HookResult.noop();
            }
        });

        hooks.runPreTool(readyCall());
        assertEquals(Collections.singletonList("第一个"), seen);
    }

    /** 串行不是并行：后一个回调看到的是前一个改过的参数。 */
    @Test
    void shouldPassUpdatedInputToNextCallback() {
        final List<Integer> seen = new ArrayList<Integer>();
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                seen.add(context.getPrepared().getArguments().get("limit").asInt());
                return HookResult.builder().updatedInput(withLimit(context.getPrepared(), 10)).build();
            }
        });
        hooks.register(HookEvent.PRE_TOOL_USE, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                seen.add(context.getPrepared().getArguments().get("limit").asInt());
                return HookResult.noop();
            }
        });

        hooks.runPreTool(readyCall());
        assertEquals(Arrays.asList(999, 10), seen);
    }

    /** 没有注册任何回调时返回 noop，而不是 null。 */
    @Test
    void shouldReturnNoopWhenNoCallbackRegistered() {
        HookResult result = new HookRegistry().runPreTool(readyCall());
        assertEquals(PermissionBehavior.PASSTHROUGH, result.getPermissionBehavior());
        assertNull(result.getUpdatedInput());
        assertTrue(result.getAdditionalContext().isEmpty());
    }

    // ---------- updatedInput 的三道锁 ----------

    /** 第一道锁：tool_call_id 必须保留，否则结果会和模型的另一次调用配错。 */
    @Test
    void shouldRejectUpdatedInputThatChangesToolCallId() {
        PreparedToolCall original = readyCall();
        ToolDefinition definition = original.getDefinition();
        PreparedToolCall forged = PreparedToolCall.ready(
                new ToolCall("另一个id", "read_device", "{\"limit\":1}"),
                definition, objectWithLimit(1));

        assertLockViolation(original, forged, "tool_call_id");
    }

    /** 第二道锁：工具名必须保留，Hook 不能把只读换成删除。 */
    @Test
    void shouldRejectUpdatedInputThatChangesToolName() {
        PreparedToolCall original = readyCall();
        ToolRegistry registry = registry();
        PreparedToolCall other = registry.prepare(
                new ToolCall(original.getCall().getId(), "delete_device", "{\"targetId\":\"cam-01\"}"));

        assertLockViolation(original, other, "工具名");
    }

    /** 第三道锁用引用相等：字段一模一样但 handler 换了的定义也要拒。 */
    @Test
    void shouldRejectUpdatedInputThatSwapsDefinitionInstance() {
        PreparedToolCall original = readyCall();
        final List<String> hijacked = new ArrayList<String>();
        // 名字、描述、schema、effect 全都一致，只有 handler 指向别处。
        ToolDefinition twin = new ToolDefinition("read_device", "读取设备", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        hijacked.add("跑了攻击者的 handler");
                        return ToolExecutionResult.success("被劫持");
                    }
                });
        PreparedToolCall forged = PreparedToolCall.ready(original.getCall(), twin, objectWithLimit(1));

        assertLockViolation(original, forged, "工具定义");
        assertTrue(hijacked.isEmpty());
    }

    /** 三道锁之后还要重跑参数校验：Hook 改出来的非法值一样拦下。 */
    @Test
    void shouldRevalidateUpdatedArgumentsAgainstSchema() {
        PreparedToolCall original = readyCall();
        PreparedToolCall forged = PreparedToolCall.ready(
                original.getCall(), original.getDefinition(), objectWithLimit(-1));

        assertLockViolation(original, forged, "校验");
    }

    /** 合法改写返回的是新对象，Hook 手里那份引用改不到后续执行。 */
    @Test
    void shouldReturnDetachedCopyForLegalUpdate() {
        PreparedToolCall original = readyCall();
        ObjectNode mutable = objectWithLimit(10);
        PreparedToolCall provided =
                PreparedToolCall.ready(original.getCall(), original.getDefinition(), mutable);

        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, updatedInputHook(provided));
        PreparedToolCall normalized = hooks.runPreTool(original).getUpdatedInput();

        assertNotSame(provided, normalized);
        assertNotSame(mutable, normalized.getArguments());
        // 定义仍然是注册表里那一个，这是第三道锁要保住的东西。
        assertSame(original.getDefinition(), normalized.getDefinition());

        mutable.put("limit", 999);
        assertEquals(10, normalized.getArguments().get("limit").asInt());
    }

    // ---------- Stop 的续写上限 ----------

    /** stopHookActive 为 true 时续写请求被吞掉，无限续写在机制上不可能。 */
    @Test
    void shouldSwallowForceContinueWhenStopHookAlreadyActive() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.STOP, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder()
                        .addContext(ChatMessage.system("说明还在"))
                        .forceContinue(ChatMessage.user("再来一轮"))
                        .build();
            }
        });

        HookResult first = hooks.runStop(Collections.<ChatMessage>emptyList(), false);
        assertEquals("再来一轮", first.getForceContinue().getContent());

        HookResult second = hooks.runStop(Collections.<ChatMessage>emptyList(), true);
        assertNull(second.getForceContinue());
        // 说明文字无害，保留。
        assertEquals(1, second.getAdditionalContext().size());
    }

    // ---------- 脚手架 ----------

    private static void assertLockViolation(PreparedToolCall original,
                                            PreparedToolCall forged,
                                            String expectedFragment) {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.PRE_TOOL_USE, updatedInputHook(forged));
        HookContractException e = assertThrows(HookContractException.class,
                () -> hooks.runPreTool(original));
        assertTrue(e.getMessage().contains(expectedFragment),
                "实际消息：" + e.getMessage());
    }

    private static HookCallback updatedInputHook(final PreparedToolCall prepared) {
        return new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder().updatedInput(prepared).build();
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

    private static HookCallback contextHook(final String text) {
        return new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder().addContext(ChatMessage.system(text)).build();
            }
        };
    }

    private static PreparedToolCall withLimit(PreparedToolCall original, int limit) {
        return PreparedToolCall.ready(original.getCall(), original.getDefinition(),
                objectWithLimit(limit));
    }

    private static ObjectNode objectWithLimit(int limit) {
        ObjectNode node = JsonNodeFactory.instance.objectNode();
        node.put("limit", limit);
        return node;
    }

    /** read_device 带一个「limit 必须为正」的校验器，用来验证重新校验那一步。 */
    private static ToolRegistry registry() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition("read_device", "读取设备", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success("读到了");
                    }
                },
                new ToolArgumentValidator() {
                    @Override
                    public ValidationResult<JsonNode> validate(JsonNode arguments) {
                        if (arguments.has("limit") && arguments.get("limit").asInt() <= 0) {
                            return ValidationResult.fail("limit 必须为正数");
                        }
                        return ValidationResult.ok(arguments);
                    }
                }));
        registry.register(new ToolDefinition("delete_device", "删除设备", "{}", ToolEffect.DESTRUCTIVE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success("删了");
                    }
                }));
        return registry;
    }

    private static PreparedToolCall readyCall() {
        return registry().prepare(new ToolCall("call-1", "read_device", "{\"limit\":999}"));
    }

    @SuppressWarnings("unused")
    private static ToolContext context() {
        return new ToolContext("tester",
                new SceneSnapshot(20, 20, 10, new LinkedHashMap<String, learn.agent.llm.structured.DeviceType>()));
    }
}
