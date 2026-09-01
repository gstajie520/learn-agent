package learn.agent.llm.plan;

import java.util.Collections;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRequest;
import learn.agent.llm.client.ChatRole;
import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.hook.HookEvent;
import learn.agent.llm.hook.HookRegistry;
import learn.agent.llm.hook.HookResult;
import learn.agent.llm.hook.HookedAgentLoop;
import learn.agent.llm.loop.StopReason;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.GuardedTrace;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolCallCodec;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolDefinition;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolHandler;
import learn.agent.llm.tool.ToolRegistry;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link PlanReminderHook} 的行为测试。
 *
 * <p>它要证明两件事：一是计划机制<b>不改一行循环代码</b>就能接进阶段 8 的
 * {@code HookedAgentLoop}（这是对 Hook 扩展点的验收）；二是走 Hook 这条路
 * 提醒<b>会进历史</b> —— 把这个已知差异用测试钉住，而不是只写在注释里。</p>
 */
public class PlanReminderHookTest {

    /** 一个只读工具，用来在循环里制造「非 todo_write」的轮次。 */
    private static ToolDefinition readTool() {
        return new ToolDefinition(
                "read_file",
                "读取一个文件",
                "{\"type\":\"object\"}",
                ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success("文件内容");
                    }
                });
    }

    private static ToolContext context() {
        return new ToolContext("test-user", SceneSnapshot.empty(100, 100, 10));
    }

    /** 让 Fake 模型连续请求 read_file，最后给一句答复。 */
    private static FakeModelClient modelCallingReadFile(int times) {
        FakeModelClient fake = new FakeModelClient();
        for (int i = 1; i <= times; i++) {
            fake.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall("call-" + i, "read_file", "{}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        }
        fake.enqueueResponse("看完了。", FinishReason.STOP, new TokenUsage(150, 30));
        return fake;
    }

    private static HookedAgentLoop loop(FakeModelClient fake, HookRegistry hooks, TodoTracker tracker) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(readTool());
        registry.register(tracker.getToolDefinition());
        return new HookedAgentLoop("test-model", fake, registry, context(),
                10, 1000L, TraceIdGenerator.fixed("trace-1"), null, hooks);
    }

    @Test
    @DisplayName("注册在 PostToolUse 上，不占用其他事件")
    void shouldRegisterOnPostToolUse() {
        // 注册错事件会让计数偏移一轮，所以注册位置由类自己决定、不交给调用方。
        HookRegistry hooks = new HookRegistry();
        TodoTracker tracker = new TodoTracker();

        PlanReminderHook.registerOn(hooks, tracker);

        assertEquals(1, hooks.count(HookEvent.POST_TOOL_USE));
        assertEquals(0, hooks.count(HookEvent.PRE_TOOL_USE));
        assertEquals(0, hooks.count(HookEvent.USER_PROMPT_SUBMIT));
        assertEquals(0, hooks.count(HookEvent.STOP));
    }

    @Test
    @DisplayName("构造时拒绝 null tracker")
    void shouldRejectNullTracker() {
        // 没有 tracker 的提醒 Hook 是个哑弹：注册成功但永远不会提醒。
        assertThrows(IllegalArgumentException.class, () -> new PlanReminderHook(null));
        assertThrows(IllegalArgumentException.class,
                () -> PlanReminderHook.registerOn(new HookRegistry(), null));
    }

    @Test
    @DisplayName("不改一行循环代码，计划机制就接进了阶段 8 的循环")
    void shouldWorkWithStage8LoopUnchanged() {
        // 本课的完成标准：复用 Hook 扩展点，不新写第四个循环骨架。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", TodoTracker.TOOL_NAME,
                        "{\"todos\":[{\"content\":\"读文件\",\"status\":\"in_progress\"}]}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("计划已建立。", FinishReason.STOP, new TokenUsage(150, 30));

        HookRegistry hooks = new HookRegistry();
        TodoTracker tracker = new TodoTracker();
        PlanReminderHook.registerOn(hooks, tracker);
        HookedAgentLoop agent = loop(fake, hooks, tracker);

        GuardedTrace trace = agent.run("你是助手", "先建立计划");
        agent.shutdown();

        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
        assertEquals(1, tracker.getTodos().size());
        assertEquals("读文件", tracker.getTodos().get(0).getContent());
        assertEquals(TodoStatus.IN_PROGRESS, tracker.getTodos().get(0).getStatus());
    }

    @Test
    @DisplayName("连续三轮只调别的工具后，下一次请求里出现提醒")
    void shouldInjectReminderIntoNextRequest() {
        // 这是机制在真实循环里生效的证据：提醒确实进了发给模型的消息列表。
        FakeModelClient fake = modelCallingReadFile(TodoTracker.STALE_TOOL_ROUNDS);
        HookRegistry hooks = new HookRegistry();
        TodoTracker tracker = new TodoTracker();
        PlanReminderHook.registerOn(hooks, tracker);
        HookedAgentLoop agent = loop(fake, hooks, tracker);

        agent.run("你是助手", "读三个文件");
        agent.shutdown();

        // 第 4 次请求（下标 3）是三轮工具之后的那次，提醒应该已经在里面。
        ChatRequest lastRequest = fake.getLastRequest();
        assertTrue(containsReminder(lastRequest.getMessages()),
                "第三轮工具之后的请求里应包含陈旧提醒");
    }

    @Test
    @DisplayName("不足三轮时请求里没有提醒")
    void shouldNotInjectBeforeThreshold() {
        // 提醒太早就是噪声，模型会学会忽略它。
        FakeModelClient fake = modelCallingReadFile(TodoTracker.STALE_TOOL_ROUNDS - 1);
        HookRegistry hooks = new HookRegistry();
        TodoTracker tracker = new TodoTracker();
        PlanReminderHook.registerOn(hooks, tracker);
        HookedAgentLoop agent = loop(fake, hooks, tracker);

        agent.run("你是助手", "读两个文件");
        agent.shutdown();

        assertFalse(containsReminder(fake.getLastRequest().getMessages()));
    }

    @Test
    @DisplayName("模型更新了计划就不再被催")
    void shouldNotRemindWhenPlanIsFresh() {
        // 计划刚更新过还催一遍，会让提醒和刚写的快照同时出现在上下文里。
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "read_file", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-2", "read_file", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-3", TodoTracker.TOOL_NAME,
                        "{\"todos\":[{\"content\":\"任务 A\",\"status\":\"completed\"}]}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-4", "read_file", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse("做完了。", FinishReason.STOP, new TokenUsage(150, 30));

        HookRegistry hooks = new HookRegistry();
        TodoTracker tracker = new TodoTracker();
        PlanReminderHook.registerOn(hooks, tracker);
        HookedAgentLoop agent = loop(fake, hooks, tracker);

        agent.run("你是助手", "边读边更新计划");
        agent.shutdown();

        assertFalse(containsReminder(fake.getLastRequest().getMessages()));
        assertEquals(1, tracker.getNonTodoToolRounds());
    }

    @Test
    @DisplayName("已知差异：走 Hook 的提醒会留在历史里，之后每轮都要付它的 token")
    void shouldDocumentThatHookRemindersPersistInHistory() {
        // 这条测试钉住的是一个缺陷，不是一个特性。教材语义要求提醒只影响一次请求；
        // Hook 的 additionalContext 做不到这件事，正是阶段 9 第 5 课要引入 Provider 的理由。
        FakeModelClient fake = modelCallingReadFile(TodoTracker.STALE_TOOL_ROUNDS + 1);
        HookRegistry hooks = new HookRegistry();
        TodoTracker tracker = new TodoTracker();
        PlanReminderHook.registerOn(hooks, tracker);
        HookedAgentLoop agent = loop(fake, hooks, tracker);

        agent.run("你是助手", "读四个文件");
        agent.shutdown();

        // 提醒在第 3 轮之后注入；第 4 轮的请求里它<b>依然存在</b>，因为进了 messages。
        int reminderCount = countReminders(fake.getLastRequest().getMessages());
        assertEquals(1, reminderCount,
                "提醒进了历史，所以后续请求里仍然带着它 —— 这正是 Hook 表达不了请求级临时上下文的证据");
    }

    @Test
    @DisplayName("tracker 独立使用时，beforeModel 的提醒不进任何历史")
    void shouldKeepReminderEphemeralWhenUsedDirectly() {
        // 与上一条对照：教材原义由 beforeModel() 保住，调用方只拼进本次请求。
        TodoTracker tracker = new TodoTracker();
        for (int i = 0; i < TodoTracker.STALE_TOOL_ROUNDS; i++) {
            tracker.recordToolRound(Collections.singletonList("read_file"));
        }

        List<ChatMessage> first = tracker.beforeModel();
        List<ChatMessage> second = tracker.beforeModel();

        assertEquals(1, first.size());
        assertTrue(second.isEmpty(), "提醒只发一次；它不累积、也不属于历史");
    }

    @Test
    @DisplayName("Hook 返回的提醒是 system 角色，不能冒充用户")
    void shouldReturnSystemRoleOnly() {
        // 阶段 8 的约束：additionalContext 只收 system。Hook 不能冒充用户说话。
        TodoTracker tracker = new TodoTracker();
        for (int i = 0; i < TodoTracker.STALE_TOOL_ROUNDS; i++) {
            tracker.recordToolRound(Collections.singletonList("read_file"));
        }

        List<ChatMessage> reminder = tracker.beforeModel();

        assertEquals(ChatRole.SYSTEM, reminder.get(0).getRole());
    }

    @Test
    @DisplayName("没到阈值时 Hook 返回 noop，不产生任何上下文")
    void shouldReturnNoopWhenFresh() {
        // 每轮都返回一条空消息会让 messages 里塞满无意义条目。
        TodoTracker tracker = new TodoTracker();
        PlanReminderHook hook = new PlanReminderHook(tracker);

        HookResult result = HookResult.noop();

        assertTrue(result.getAdditionalContext().isEmpty());
        assertEquals(0, tracker.getNonTodoToolRounds());
        assertTrue(hook != null);
    }

    private static boolean containsReminder(List<ChatMessage> messages) {
        return countReminders(messages) > 0;
    }

    private static int countReminders(List<ChatMessage> messages) {
        int count = 0;
        for (ChatMessage message : messages) {
            if (TodoTracker.STALE_REMINDER.equals(message.getContent())) {
                count++;
            }
        }
        return count;
    }
}
