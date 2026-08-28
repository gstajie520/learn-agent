package learn.agent.llm.loop;

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

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 阶段 7 的教学入口：把工具边界补齐，并让每一轮都可追溯。
 *
 * <p>第 4 课已经跑通了「模型选工具 → 程序执行 → 结果回传」。本课加的三件事
 * 都是那个循环放到线上才会暴露的问题：工具卡住不返回、模型重复调同一个工具、
 * 以及出了问题事后无法复盘。</p>
 *
 * <p>运行：</p>
 * <pre>
 * [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
 * mvn -o -pl 05-llm-client -am package -DskipTests
 * java "-Dfile.encoding=UTF-8" -cp '05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.loop.AgentLoopDemo
 * </pre>
 */
public class AgentLoopDemo {

    public static void main(String[] args) {
        SceneSnapshot scene = buildScene();
        ToolContext context = new ToolContext("demo-user", scene);

        System.out.println("当前场景：" + scene);
        System.out.println();

        demoTraceOfNormalRun(context);
        demoToolTimeout(context);
        demoDuplicateToolCall(context);
        demoMaxRounds(context);
        demoProtocolViolation(context);
    }

    /** 场景一：正常跑完一次，看 trace 记下了什么。 */
    private static void demoTraceOfNormalRun(ToolContext context) {
        System.out.println("=== 场景一：一次正常往返的完整 trace ★ ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
        fake.enqueueResponse(
                "当前有 3 台设备：cam-01、cam-02、fence-main。",
                FinishReason.STOP, new TokenUsage(210, 45));

        AgentLoop loop = newLoop(fake, buildRegistry(), context, 5, 1000L, "trace-normal");
        AgentTrace trace = loop.run("你是场景管理助手", "现在有哪些设备？");
        loop.shutdown();

        System.out.println(trace.render());
        System.out.println("要点：★ run 返回的是 AgentTrace 而不是一个字符串。");
        System.out.println("     停止原因、轮数、每轮调了什么、花了多少 token，都是可断言的字段，");
        System.out.println("     不需要去正则匹配模型说的话。");
        System.out.println();
    }

    /** 场景二：工具卡住，超时闸门放弃等待。 */
    private static void demoToolTimeout(ToolContext context) {
        System.out.println("=== 场景二：工具卡住不返回，超时后放弃等待 ★ ===");

        ToolRegistry registry = buildRegistry();
        // 一个永远慢的工具：模拟下游接口挂住。
        registry.register(new ToolDefinition(
                "slow_scan",
                "全场景扫描（很慢）",
                "{\"type\":\"object\",\"properties\":{}}",
                ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        try {
                            Thread.sleep(5000L);
                        } catch (InterruptedException e) {
                            Thread.currentThread().interrupt();
                        }
                        return ToolExecutionResult.success("扫描完成");
                    }
                }));

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-slow", "slow_scan", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        fake.enqueueResponse(
                "扫描暂时没有响应，我稍后重试，或者你可以先看设备列表。",
                FinishReason.STOP, new TokenUsage(160, 30));

        // 超时设成 200ms，工具要 5000ms，必然超时。
        AgentLoop loop = newLoop(fake, registry, context, 5, 200L, "trace-timeout");
        AgentTrace trace = loop.run("你是场景管理助手", "扫描一下整个场景");
        loop.shutdown();

        System.out.println(trace.render());
        System.out.println("要点：★ 超时结束的是「等待」，不是「执行」。");
        System.out.println("     future.cancel(true) 只发中断信号，工具可能仍在后台跑完 5 秒。");
        System.out.println("     所以错误文案是「已放弃等待」，而不是「已取消」——这条闸门是最后一道防线，");
        System.out.println("     工具自己也该有超时。");
        System.out.println();
    }

    /** 场景三：模型重复调同一个工具，第二次命中幂等缓存。 */
    private static void demoDuplicateToolCall(ToolContext context) {
        System.out.println("=== 场景三：重复的工具调用只真正执行一次 ★ ===");

        final int[] executions = new int[1];
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "create_device",
                "在指定坐标新增一台设备",
                "{\"type\":\"object\",\"properties\":{\"deviceType\":{\"type\":\"string\"}}}",
                ToolEffect.WRITE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        executions[0]++;
                        return ToolExecutionResult.success("已新增设备（第 " + executions[0] + " 次执行）");
                    }
                }));

        String sameArguments = "{\"deviceType\":\"radar\"}";
        FakeModelClient fake = new FakeModelClient();
        // 两轮参数完全一样，只有 tool_call_id 不同——这正是模型犯的典型错。
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-a", "create_device", sameArguments)),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-b", "create_device", sameArguments)),
                FinishReason.TOOL_CALLS, new TokenUsage(140, 30));
        fake.enqueueResponse(
                "雷达已新增完成。",
                FinishReason.STOP, new TokenUsage(180, 20));

        AgentLoop loop = newLoop(fake, registry, context, 5, 1000L, "trace-dedup");
        AgentTrace trace = loop.run("你是场景管理助手", "加一台雷达");
        loop.shutdown();

        System.out.println(trace.render());
        System.out.println("handler 实际执行次数：" + executions[0] + "（模型请求了 2 次）");
        System.out.println("要点：★ 幂等键是「工具名 + 原始参数串」，故意不含 tool_call_id——");
        System.out.println("     那个 id 每次都不同，算进去就永远命中不了。");
        System.out.println("     失败结果不缓存：一次偶发超时不该在整个会话里变成永久失败。");
        System.out.println();
    }

    /** 场景四：模型一直调工具，轮数上限打断。 */
    private static void demoMaxRounds(ToolContext context) {
        System.out.println("=== 场景四：轮数耗尽，停止原因是 max_rounds ===");

        FakeModelClient fake = new FakeModelClient();
        for (int i = 0; i < 3; i++) {
            // 参数每轮不同，避免命中幂等缓存，纯粹测轮数。
            fake.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall("call-loop-" + i, "create_device",
                            "{\"deviceType\":\"radar\",\"seq\":" + i + "}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        }

        AgentLoop loop = newLoop(fake, buildRegistry(), context, 3, 1000L, "trace-maxrounds");
        AgentTrace trace = loop.run("你是场景管理助手", "一直加设备");
        loop.shutdown();

        System.out.println(trace.render());
        System.out.println("要点：停止原因是枚举 MAX_ROUNDS，调用方一个 if 就能判断这次是异常收尾，");
        System.out.println("     不用去猜模型那句话是「答完了」还是「被打断了」。");
        System.out.println();
    }

    /** 场景五：模型说要调工具，但内容解不出工具调用。 */
    private static void demoProtocolViolation(ToolContext context) {
        System.out.println("=== 场景五：finish_reason 说有工具调用，内容里却没有 ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("我打算查一下设备列表", FinishReason.TOOL_CALLS, new TokenUsage(100, 20));

        AgentLoop loop = newLoop(fake, buildRegistry(), context, 5, 1000L, "trace-protocol");
        AgentTrace trace = loop.run("你是场景管理助手", "看看设备");
        loop.shutdown();

        System.out.println(trace.render());
        System.out.println("要点：协议自相矛盾时立刻停，不猜模型想干什么。");
        System.out.println("     再发一轮只会拿到同样矛盾的响应，还多花一次钱。");
        System.out.println();
    }

    /** 统一构造 AgentLoop，trace id 固定，便于对照输出。 */
    private static AgentLoop newLoop(FakeModelClient fake,
                                     ToolRegistry registry,
                                     ToolContext context,
                                     int maxRounds,
                                     long toolTimeoutMillis,
                                     String traceId) {
        return new AgentLoop("deepseek-v4-flash", fake, registry, context,
                maxRounds, toolTimeoutMillis, TraceIdGenerator.fixed(traceId));
    }

    /** 复用第 4 课的三种副作用等级：只读、写、破坏性。 */
    private static ToolRegistry buildRegistry() {
        ToolRegistry registry = new ToolRegistry();

        registry.register(new ToolDefinition(
                "list_devices",
                "列出当前场景里的所有设备及其类型",
                "{\"type\":\"object\",\"properties\":{}}",
                ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        StringBuilder sb = new StringBuilder("当前设备：");
                        for (Map.Entry<String, DeviceType> e : ctx.getScene().getDevices().entrySet()) {
                            sb.append(e.getKey()).append("（").append(e.getValue().getWireValue()).append("）、");
                        }
                        return ToolExecutionResult.success(sb.toString());
                    }
                }));

        registry.register(new ToolDefinition(
                "create_device",
                "在指定坐标新增一台设备",
                "{\"type\":\"object\",\"properties\":{\"deviceType\":{\"type\":\"string\"}}}",
                ToolEffect.WRITE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        return ToolExecutionResult.success("已生成新增设备预览（未落库）：" + arguments.toString());
                    }
                }));

        registry.register(new ToolDefinition(
                "delete_device",
                "删除指定设备（不可逆，需人工确认）",
                "{\"type\":\"object\",\"properties\":{\"targetId\":{\"type\":\"string\"}}}",
                ToolEffect.DESTRUCTIVE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext ctx) {
                        return ToolExecutionResult.success("已删除设备：" + arguments.path("targetId").asText());
                    }
                }));

        return registry;
    }

    /** 构造一个固定场景。 */
    private static SceneSnapshot buildScene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("cam-02", DeviceType.CAMERA);
        devices.put("fence-main", DeviceType.FENCE);
        return new SceneSnapshot(200, 200, 20, devices);
    }
}
