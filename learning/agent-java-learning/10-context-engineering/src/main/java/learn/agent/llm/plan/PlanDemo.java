package learn.agent.llm.plan;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.hook.HookRegistry;
import learn.agent.llm.hook.HookedAgentLoop;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.GuardedTrace;
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

/**
 * 阶段 9 第 1 课的教学入口：会话计划。
 *
 * <p>五个场景，从「完整快照怎么工作」一路演示到「Hook 这条路径的代价」：</p>
 * <ol>
 *   <li>写入完整快照，看工具结果回传了什么；</li>
 *   <li>增量式的错误参数被校验层一次性挡下；</li>
 *   <li>连续三轮不更新计划，{@code beforeModel()} 注入提醒；</li>
 *   <li>提醒发出后立刻清零，不会每轮重复；</li>
 *   <li>接进阶段 8 的循环，观察提醒<b>留在了历史里</b>这个代价。</li>
 * </ol>
 *
 * <p>运行：</p>
 * <pre>
 * [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
 * mvn -o -pl 10-context-engineering -am package -DskipTests
 * java "-Dfile.encoding=UTF-8" -cp '10-context-engineering/target/classes;05-llm-client/target/classes;06-structured-output/target/classes;07-tool-calling/target/classes;08-agent-loop/target/classes;09-agent-guardrails/target/classes;10-context-engineering/target/dependency/*' learn.agent.llm.plan.PlanDemo
 * </pre>
 */
public class PlanDemo {

    public static void main(String[] args) {
        demoWriteSnapshot();
        demoIncrementalRejected();
        demoStaleReminder();
        demoReminderNotRepeated();
        demoInsideLoop();
    }

    /** 场景一：写入完整快照，工具结果把系统接受的样子回传给模型。 */
    private static void demoWriteSnapshot() {
        System.out.println("=== 场景一：完整快照写入 ===");

        TodoTracker tracker = new TodoTracker();
        ToolRegistry registry = new ToolRegistry();
        registry.register(tracker.getToolDefinition());

        ToolExecutionResult result = write(registry, tracker,
                "[{\"content\":\"读取配置\",\"status\":\"completed\"},"
                        + "{\"content\":\"接入雷达设备\",\"status\":\"in_progress\"},"
                        + "{\"content\":\"补充回归测试\",\"status\":\"pending\"}]");

        System.out.println("工具结果：" + result.getContent());
        System.out.println("内存快照：" + tracker.getTodos());
        System.out.println("要点：结果原样回传，模型才能确认自己有没有漏项、状态有没有写反。");
        System.out.println();
    }

    /** 场景二：模型试图只改一项，校验层一次列出全部问题。 */
    private static void demoIncrementalRejected() {
        System.out.println("=== 场景二：增量补丁与非法状态被一次性挡下 ===");

        TodoTracker tracker = new TodoTracker();
        ToolRegistry registry = new ToolRegistry();
        registry.register(tracker.getToolDefinition());

        // 模型想「只把第 2 项标记完成」，于是传了一个对象而不是数组。
        ToolExecutionResult patch = prepareOnly(registry,
                "{\"todos\":{\"index\":2,\"status\":\"completed\"}}");
        System.out.println("增量补丁 -> " + patch.getErrorCode() + "：" + patch.getContent());

        // 三项各错一处：状态拼错、描述空白、状态用了没有的 blocked。
        ToolExecutionResult multi = prepareOnly(registry,
                "{\"todos\":["
                        + "{\"content\":\"读取配置\",\"status\":\"done\"},"
                        + "{\"content\":\"   \",\"status\":\"pending\"},"
                        + "{\"content\":\"接入设备\",\"status\":\"blocked\"}"
                        + "]}");
        System.out.println("三处错误 -> " + multi.getErrorCode());
        System.out.println(multi.getContent());
        System.out.println("要点：一次列全部错误。分三轮告诉模型，就要多烧三轮 token。");
        System.out.println();
    }

    /** 场景三：连续三轮别的工具，提醒被注入。 */
    private static void demoStaleReminder() {
        System.out.println("=== 场景三：计划陈旧后注入提醒 ===");

        TodoTracker tracker = new TodoTracker();

        for (int round = 1; round <= TodoTracker.STALE_TOOL_ROUNDS; round++) {
            tracker.recordToolRound(Arrays.asList("list_devices"));
            List<ChatMessage> injected = tracker.beforeModel();
            System.out.println("第 " + round + " 轮后：陈旧计数=" + tracker.getNonTodoToolRounds()
                    + "，注入消息数=" + injected.size());
            if (!injected.isEmpty()) {
                System.out.println("  注入内容[" + injected.get(0).getRole().getWireValue() + "]："
                        + injected.get(0).getContent());
            }
        }
        System.out.println("要点：提醒是请求级临时消息，调用方只拼进这一次请求，不写进历史。");
        System.out.println();
    }

    /** 场景四：提醒发出即清零，不会每轮重复刷屏。 */
    private static void demoReminderNotRepeated() {
        System.out.println("=== 场景四：提醒不重复 ===");

        TodoTracker tracker = new TodoTracker();
        for (int i = 0; i < TodoTracker.STALE_TOOL_ROUNDS; i++) {
            tracker.recordToolRound(Arrays.asList("list_devices"));
        }

        System.out.println("第一次读取，注入数=" + tracker.beforeModel().size());
        System.out.println("紧接着再读，注入数=" + tracker.beforeModel().size());
        System.out.println("要点：读取即清零。不清零的话，此后每一轮都会重复注入同一句话。");
        System.out.println();
    }

    /** 场景五：接进阶段 8 的循环。能跑通，但暴露出 Hook 这条路径的代价。 */
    private static void demoInsideLoop() {
        System.out.println("=== 场景五：接进阶段 8 的 HookedAgentLoop ===");

        TodoTracker tracker = new TodoTracker();
        ToolRegistry registry = new ToolRegistry();
        registry.register(tracker.getToolDefinition());
        registry.register(readOnlyTool("list_devices"));

        HookRegistry hooks = new HookRegistry();
        PlanReminderHook.registerOn(hooks, tracker);

        FakeModelClient fake = new FakeModelClient();
        // 连续三轮只读工具，第四轮给最终答复。第三轮之后提醒应当出现。
        for (int i = 1; i <= TodoTracker.STALE_TOOL_ROUNDS; i++) {
            fake.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall("call-" + i, "list_devices", "{}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        }
        fake.enqueueResponse("三台设备都在线。", FinishReason.STOP, new TokenUsage(200, 30));

        HookedAgentLoop loop = new HookedAgentLoop(
                "demo-model", fake, registry, context(), 8, 2000L,
                TraceIdGenerator.fixed("trace-plan-demo"), null, hooks);

        try {
            GuardedTrace trace = loop.run("你是场景管理助手", "检查一下所有设备");
            System.out.println("停止原因：" + trace.getStopReason().getWireValue()
                    + "，轮数=" + trace.getRoundCount());

            // 数一下最后一次请求里出现了几条提醒。
            int reminders = 0;
            for (ChatMessage message : fake.getLastRequest().getMessages()) {
                if (TodoTracker.STALE_REMINDER.equals(message.getContent())) {
                    reminders++;
                }
            }
            System.out.println("最后一次请求的消息数=" + fake.getLastRequest().getMessages().size()
                    + "，其中提醒 " + reminders + " 条");
            System.out.println("要点：提醒确实注入成功了，但它被 append 进了 messages ——");
            System.out.println("      从此每一轮都要为它付 token，历史里也多了一句没人说过的话。");
            System.out.println("      这就是阶段 9 第 5 课要引入 Provider 的原因。");
        } finally {
            loop.shutdown();
        }
        System.out.println();
    }

    /** 走完整链路写一次快照。 */
    private static ToolExecutionResult write(ToolRegistry registry, TodoTracker tracker, String todosJson) {
        ToolCall call = new ToolCall("call-write", TodoTracker.TOOL_NAME,
                "{\"todos\":" + todosJson + "}");
        return registry.invoke(registry.prepare(call), context());
    }

    /** 只走 prepare，用来观察校验错误（不执行，不改状态）。 */
    private static ToolExecutionResult prepareOnly(ToolRegistry registry, String rawArguments) {
        ToolCall call = new ToolCall("call-bad", TodoTracker.TOOL_NAME, rawArguments);
        return registry.prepare(call).getError();
    }

    /** 一个只读工具，用来制造「计划没更新」的轮次。 */
    private static ToolDefinition readOnlyTool(String name) {
        return new ToolDefinition(name, "列出当前场景里的设备", "{\"type\":\"object\"}",
                ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        return ToolExecutionResult.success("cam-01, cam-02, fence-main");
                    }
                });
    }

    private static ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("cam-02", DeviceType.CAMERA);
        devices.put("fence-main", DeviceType.FENCE);
        SceneSnapshot scene = new SceneSnapshot(100, 100, 10, devices);
        return new ToolContext("demo-user", scene);
    }

    /** 供场景一复用的空列表，避免每处都写 new ArrayList。 */
    private static final List<String> NO_TOOLS = new ArrayList<String>();
}
