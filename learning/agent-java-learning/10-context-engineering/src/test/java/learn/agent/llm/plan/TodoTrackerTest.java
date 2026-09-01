package learn.agent.llm.plan;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRole;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.PreparedToolCall;
import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolEffect;
import learn.agent.llm.tool.ToolExecutionResult;
import learn.agent.llm.tool.ToolRegistry;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link TodoTracker} 的行为测试。
 *
 * <p>本课要证明的是四件事：完整快照会整体替换、非法快照进不来、
 * 陈旧提醒按轮数触发且只发一次、提醒不进历史。</p>
 */
public class TodoTrackerTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** 工具执行需要一个 context，本课的计划状态不依赖场景，给个空场景即可。 */
    private static ToolContext context() {
        return new ToolContext("test-user", SceneSnapshot.empty(100, 100, 10));
    }

    /** 走完整链路执行一次 todo_write：注册 → prepare → invoke。 */
    private static ToolExecutionResult write(TodoTracker tracker, String rawArguments) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(tracker.getToolDefinition());
        ToolCall call = new ToolCall("call-1", TodoTracker.TOOL_NAME, rawArguments);
        PreparedToolCall prepared = registry.prepare(call);
        if (prepared.isFailed()) {
            return prepared.getError();
        }
        return registry.invoke(prepared, context());
    }

    @Test
    @DisplayName("初始状态：计划为空，陈旧计数为 0")
    void shouldStartEmpty() {
        // 新建的 tracker 不该带任何上一次会话的残留 —— 计划是会话级状态。
        TodoTracker tracker = new TodoTracker();

        assertTrue(tracker.getTodos().isEmpty());
        assertEquals(0, tracker.getNonTodoToolRounds());
    }

    @Test
    @DisplayName("工具是 WRITE 而不是 DESTRUCTIVE，不需要人工确认")
    void shouldNotRequireConfirmation() {
        // 若标成 DESTRUCTIVE，模型每次更新计划都会被闸门挡住等确认，机制直接失效。
        TodoTracker tracker = new TodoTracker();

        assertEquals(ToolEffect.WRITE, tracker.getToolDefinition().getEffect());
        assertFalse(tracker.getToolDefinition().getEffect().requiresConfirmation());
    }

    @Test
    @DisplayName("写入完整快照后，内存状态与工具结果一致")
    void shouldWriteCompleteSnapshot() {
        // 回传给模型的 JSON 必须等于内部状态，否则模型据以推理的东西是假的。
        TodoTracker tracker = new TodoTracker();

        ToolExecutionResult result = write(tracker,
                "{\"todos\":[{\"content\":\"读 README\",\"status\":\"completed\"},"
                        + "{\"content\":\"跑测试\",\"status\":\"in_progress\"},"
                        + "{\"content\":\"写总结\",\"status\":\"pending\"}]}");

        assertFalse(result.isError());
        assertEquals(3, tracker.getTodos().size());
        assertEquals("读 README", tracker.getTodos().get(0).getContent());
        assertEquals(TodoStatus.COMPLETED, tracker.getTodos().get(0).getStatus());
        assertEquals(TodoStatus.IN_PROGRESS, tracker.getTodos().get(1).getStatus());
        assertEquals(TodoStatus.PENDING, tracker.getTodos().get(2).getStatus());
        assertTrue(result.getContent().contains("读 README"));
        assertTrue(result.getContent().contains("in_progress"));
    }

    @Test
    @DisplayName("第二次写入整体替换，不与旧快照合并")
    void shouldReplaceNotMerge() {
        // 完整快照的语义：新表就是全部事实。若做成 merge，模型删不掉任何一项。
        TodoTracker tracker = new TodoTracker();
        write(tracker, "{\"todos\":[{\"content\":\"任务 A\",\"status\":\"pending\"},"
                + "{\"content\":\"任务 B\",\"status\":\"pending\"}]}");

        write(tracker, "{\"todos\":[{\"content\":\"任务 C\",\"status\":\"in_progress\"}]}");

        assertEquals(1, tracker.getTodos().size());
        assertEquals("任务 C", tracker.getTodos().get(0).getContent());
    }

    @Test
    @DisplayName("允许写入空数组：任务全部收尾是合法操作")
    void shouldAllowEmptySnapshot() {
        // 若禁止空数组，模型收尾时无法表达「没有待办了」，只能留一堆 completed 项。
        TodoTracker tracker = new TodoTracker();
        write(tracker, "{\"todos\":[{\"content\":\"任务 A\",\"status\":\"pending\"}]}");

        ToolExecutionResult result = write(tracker, "{\"todos\":[]}");

        assertFalse(result.isError());
        assertTrue(tracker.getTodos().isEmpty());
    }

    @Test
    @DisplayName("返回的快照视图不可修改")
    void shouldReturnUnmodifiableView() {
        // 计划要被序列化给模型看，外部能改它就意味着「模型看到的」和「系统记的」会分叉。
        TodoTracker tracker = new TodoTracker();
        write(tracker, "{\"todos\":[{\"content\":\"任务 A\",\"status\":\"pending\"}]}");

        List<TodoItem> todos = tracker.getTodos();

        assertThrows(UnsupportedOperationException.class,
                () -> todos.add(new TodoItem("偷加的", TodoStatus.PENDING)));
    }

    @Test
    @DisplayName("非法状态字面值被校验层拦下，旧快照不受影响")
    void shouldRejectInvalidStatusAndKeepOldSnapshot() {
        // 校验失败必须发生在写入之前，否则会留下一个半新半旧的计划。
        TodoTracker tracker = new TodoTracker();
        write(tracker, "{\"todos\":[{\"content\":\"任务 A\",\"status\":\"pending\"}]}");

        ToolExecutionResult result = write(tracker,
                "{\"todos\":[{\"content\":\"任务 B\",\"status\":\"blocked\"}]}");

        assertTrue(result.isError());
        assertEquals("invalid_arguments", result.getErrorCode());
        assertEquals(1, tracker.getTodos().size());
        assertEquals("任务 A", tracker.getTodos().get(0).getContent());
    }

    @Test
    @DisplayName("增量补丁形式（todos 不是数组）被拒绝")
    void shouldRejectIncrementalPatch() {
        // 明确拒绝「只改一项」的写法：增量在长上下文里必然漂移。
        TodoTracker tracker = new TodoTracker();

        ToolExecutionResult result = write(tracker,
                "{\"todos\":{\"content\":\"任务 A\",\"status\":\"completed\"}}");

        assertTrue(result.isError());
        assertTrue(result.getContent().contains("完整快照"));
    }

    @Test
    @DisplayName("不足阈值不提醒")
    void shouldNotRemindBeforeThreshold() {
        // 提醒太早会变成噪声，模型会学会忽略它。
        TodoTracker tracker = new TodoTracker();

        tracker.recordToolRound(Collections.singletonList("read_file"));
        tracker.recordToolRound(Collections.singletonList("read_file"));

        assertEquals(2, tracker.getNonTodoToolRounds());
        assertTrue(tracker.beforeModel().isEmpty());
    }

    @Test
    @DisplayName("连续三轮未更新计划后注入 system 提醒")
    void shouldRemindAfterStaleRounds() {
        // 这是本课机制的核心：长任务里靠它把模型的注意力拉回计划。
        TodoTracker tracker = new TodoTracker();

        tracker.recordToolRound(Collections.singletonList("read_file"));
        tracker.recordToolRound(Collections.singletonList("list_devices"));
        tracker.recordToolRound(Collections.singletonList("read_file"));

        List<ChatMessage> injected = tracker.beforeModel();

        assertEquals(1, injected.size());
        assertEquals(ChatRole.SYSTEM, injected.get(0).getRole());
        assertEquals(TodoTracker.STALE_REMINDER, injected.get(0).getContent());
    }

    @Test
    @DisplayName("提醒发出后立即清零，不会连续重复注入")
    void shouldResetAfterReminding() {
        // 不清零的话，一旦跨过阈值，之后每一轮都会重复注入同一条提醒。
        TodoTracker tracker = new TodoTracker();
        for (int i = 0; i < TodoTracker.STALE_TOOL_ROUNDS; i++) {
            tracker.recordToolRound(Collections.singletonList("read_file"));
        }

        assertFalse(tracker.beforeModel().isEmpty());

        assertEquals(0, tracker.getNonTodoToolRounds());
        assertTrue(tracker.beforeModel().isEmpty());
    }

    @Test
    @DisplayName("调用 todo_write 那一轮把陈旧计数归零")
    void shouldResetCounterOnTodoWrite() {
        // 计划刚更新过就没有催的必要，否则提醒会和刚写的快照同时出现在上下文里。
        TodoTracker tracker = new TodoTracker();
        tracker.recordToolRound(Collections.singletonList("read_file"));
        tracker.recordToolRound(Collections.singletonList("read_file"));

        tracker.recordToolRound(Collections.singletonList(TodoTracker.TOOL_NAME));

        assertEquals(0, tracker.getNonTodoToolRounds());
    }

    @Test
    @DisplayName("一轮里同时调了别的工具和 todo_write，也算更新过")
    void shouldResetWhenTodoWriteAppearsAmongOthers() {
        // 判断依据是「这一轮有没有更新计划」，不是「这一轮只干了这件事」。
        TodoTracker tracker = new TodoTracker();
        tracker.recordToolRound(Collections.singletonList("read_file"));

        tracker.recordToolRound(Arrays.asList("read_file", TodoTracker.TOOL_NAME));

        assertEquals(0, tracker.getNonTodoToolRounds());
    }

    @Test
    @DisplayName("没有工具调用的轮次不计数")
    void shouldIgnoreRoundsWithoutTools() {
        // 模型纯说话（例如向用户追问）不算推进任务，拿它催更新计划是误报。
        TodoTracker tracker = new TodoTracker();

        tracker.recordToolRound(Collections.<String>emptyList());
        tracker.recordToolRound(null);

        assertEquals(0, tracker.getNonTodoToolRounds());
    }

    @Test
    @DisplayName("写入成功后陈旧计数归零")
    void shouldResetCounterAfterSuccessfulWrite() {
        // 计数归零必须发生在真正写入之后，而不是在 prepare 阶段。
        TodoTracker tracker = new TodoTracker();
        tracker.recordToolRound(Collections.singletonList("read_file"));
        tracker.recordToolRound(Collections.singletonList("read_file"));

        write(tracker, "{\"todos\":[{\"content\":\"任务 A\",\"status\":\"pending\"}]}");

        assertEquals(0, tracker.getNonTodoToolRounds());
    }

    @Test
    @DisplayName("两个 tracker 实例的计划互不可见")
    void shouldIsolateSessions() {
        // 计划是会话级状态。共享一个实例会让 A 用户的计划出现在 B 的上下文里。
        TodoTracker first = new TodoTracker();
        TodoTracker second = new TodoTracker();

        write(first, "{\"todos\":[{\"content\":\"A 的任务\",\"status\":\"pending\"}]}");

        assertEquals(1, first.getTodos().size());
        assertTrue(second.getTodos().isEmpty());
    }

    @Test
    @DisplayName("工具结果是合法 JSON，且字段顺序确定")
    void shouldSerializeDeterministicJson() throws Exception {
        // 模型要靠这段 JSON 确认「系统收下的计划长什么样」，它必须可解析。
        TodoTracker tracker = new TodoTracker();

        ToolExecutionResult result = write(tracker,
                "{\"todos\":[{\"content\":\"任务 A\",\"status\":\"pending\"}]}");

        JsonNode parsed = MAPPER.readTree(result.getContent());
        assertTrue(parsed.get("todos").isArray());
        assertEquals("任务 A", parsed.get("todos").get(0).get("content").asText());
        assertEquals("pending", parsed.get("todos").get(0).get("status").asText());
    }

    @Test
    @DisplayName("content 前后空白被 trim")
    void shouldTrimContent() {
        // 模型常在描述前后带空格；不 trim 会让同一个任务出现两个版本。
        TodoTracker tracker = new TodoTracker();

        write(tracker, "{\"todos\":[{\"content\":\"  任务 A  \",\"status\":\"pending\"}]}");

        assertEquals("任务 A", tracker.getTodos().get(0).getContent());
    }

    @Test
    @DisplayName("TodoItem 拒绝空内容和 null 状态")
    void shouldRejectInvalidTodoItem() {
        // 走到构造函数说明校验层已放行，这时还有空值是我们自己的代码写错了。
        assertThrows(IllegalArgumentException.class, () -> new TodoItem("  ", TodoStatus.PENDING));
        assertThrows(IllegalArgumentException.class, () -> new TodoItem("任务", null));
    }

    @Test
    @DisplayName("状态字面值解析：认识的返回枚举，不认识的返回 null 而不抛异常")
    void shouldParseStatusLeniently() {
        // 输入来自模型，写错是预期内事件，要能变成回传给它的错误而不是崩掉。
        assertEquals(TodoStatus.IN_PROGRESS, TodoStatus.fromWireValue("in_progress"));
        assertEquals(TodoStatus.COMPLETED, TodoStatus.fromWireValue("  completed  "));
        assertNull(TodoStatus.fromWireValue("blocked"));
        assertNull(TodoStatus.fromWireValue(null));
    }

    @Test
    @DisplayName("超过 50 项的快照被拒绝")
    void shouldRejectOversizedSnapshot() {
        // 上限是上下文预算的保护：模型一次塞 500 项会把预算顶爆。
        TodoTracker tracker = new TodoTracker();
        StringBuilder json = new StringBuilder("{\"todos\":[");
        for (int i = 0; i < TodoWriteValidator.MAX_TODOS + 1; i++) {
            if (i > 0) {
                json.append(',');
            }
            json.append("{\"content\":\"任务 ").append(i).append("\",\"status\":\"pending\"}");
        }
        json.append("]}");

        ToolExecutionResult result = write(tracker, json.toString());

        assertTrue(result.isError());
        assertTrue(result.getContent().contains("最多 " + TodoWriteValidator.MAX_TODOS));
    }

    @Test
    @DisplayName("校验错误一次性收集全部问题，不是只报第一条")
    void shouldCollectAllValidationErrors() {
        // 一次全告诉模型，它一轮就能改对；只报第一条要来回三轮，每轮都烧 token。
        TodoTracker tracker = new TodoTracker();

        ToolExecutionResult result = write(tracker,
                "{\"todos\":[{\"content\":\"\",\"status\":\"pending\"},"
                        + "{\"content\":\"任务 B\",\"status\":\"blocked\"},"
                        + "{\"status\":\"pending\"}]}");

        assertTrue(result.isError());
        assertTrue(result.getContent().contains("第 1 项"));
        assertTrue(result.getContent().contains("第 2 项"));
        assertTrue(result.getContent().contains("第 3 项"));
    }

    @Test
    @DisplayName("校验器收到 null 参数返回 fail 而不是抛异常")
    void shouldFailGracefullyOnNullArguments() {
        // 第 3 课的教训：校验器是防线，防线自己不该崩。
        TodoWriteValidator validator = new TodoWriteValidator();

        assertFalse(validator.validate(null).isValid());
    }

    @Test
    @DisplayName("缺少 todos 字段时给出明确指引")
    void shouldExplainMissingTodosField() {
        // 错误信息要能让模型下一轮改对，只说「非法」等于让它继续猜。
        TodoTracker tracker = new TodoTracker();

        ToolExecutionResult result = write(tracker, "{}");

        assertTrue(result.isError());
        assertTrue(result.getContent().contains("todos"));
    }

    @Test
    @DisplayName("提醒文案是常量，可被断言也可被 grep")
    void shouldKeepReminderStable() {
        // 文案每次都变的话，测试断言不了、日志也 grep 不出来。
        assertNotNull(TodoTracker.STALE_REMINDER);
        assertTrue(TodoTracker.STALE_REMINDER.contains("todo_write"));
    }
}
