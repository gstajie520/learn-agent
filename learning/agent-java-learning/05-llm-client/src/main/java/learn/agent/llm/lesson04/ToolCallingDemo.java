package learn.agent.llm.lesson04;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import learn.agent.llm.lesson01.FakeModelClient;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.TokenUsage;
import learn.agent.llm.lesson03.DeviceType;
import learn.agent.llm.lesson03.SceneSnapshot;
import learn.agent.llm.lesson03.ValidationResult;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 阶段 5 第 4 课的教学入口：工具调用循环。
 *
 * <p>本课要看清的核心是<b>决策权从程序转移到了模型</b>。第 3 课是程序
 * 要求模型填一张固定表单；本课是模型自己决定「要不要调工具、调哪个、
 * 传什么参数」，程序只负责执行和把关。</p>
 *
 * <p>运行：</p>
 * <pre>
 * [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
 * mvn -o -pl 05-llm-client -am package -DskipTests
 * java "-Dfile.encoding=UTF-8" -cp '05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.lesson04.ToolCallingDemo
 * </pre>
 */
public class ToolCallingDemo {

    public static void main(String[] args) {
        ToolRegistry registry = buildRegistry();
        SceneSnapshot scene = buildScene();
        ToolContext context = new ToolContext("demo-user", scene);

        System.out.println("已注册工具：" + registry.names());
        System.out.println("当前场景：" + scene);
        System.out.println();

        demoHappyPath(registry, context);
        demoUnknownTool(registry, context);
        demoInvalidArguments(registry, context);
        demoDestructiveNeedsConfirmation(registry, context);
        demoMaxRounds(registry, context);
    }

    /** 场景一：模型调 list_devices，程序执行，结果回传，模型给出最终答复。 */
    private static void demoHappyPath(ToolRegistry registry, ToolContext context) {
        System.out.println("=== 场景一：一次完整的「请求工具 → 执行 → 回传」往返 ===");

        FakeModelClient fake = new FakeModelClient();
        // 第一轮：模型决定调 list_devices。
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
        // 第二轮：拿到工具结果后，模型给出最终答复。
        fake.enqueueResponse(
                "当前场景里有 3 台设备：cam-01（摄像头）、cam-02（摄像头）、fence-main（围栏）。",
                FinishReason.STOP, new TokenUsage(200, 40));

        ToolCallingService service = new ToolCallingService("deepseek-v4-flash", fake, registry, context, 5);
        String answer = service.run("你是场景管理助手", "现在有哪些设备？");

        System.out.println("最终答复：" + answer);
        System.out.println("模型被调用了 " + fake.getCallCount() + " 次（一次要工具，一次给答复）");
        System.out.println("要点：模型自己决定调 list_devices，程序执行后把结果以 TOOL 角色回传。");
        System.out.println();
    }

    /** 场景二：模型编了一个不存在的工具名。 */
    private static void demoUnknownTool(ToolRegistry registry, ToolContext context) {
        System.out.println("=== 场景二：模型幻觉出一个不存在的工具 ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-2", "delete_everything", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 20));
        // 模型拿到「工具不存在」的错误后，改口给出答复。
        fake.enqueueResponse(
                "抱歉，我没有删除全部设备的权限。",
                FinishReason.STOP, new TokenUsage(150, 20));

        ToolCallingService service = new ToolCallingService("deepseek-v4-flash", fake, registry, context, 5);
        String answer = service.run("你是场景管理助手", "把场景清空");

        System.out.println("最终答复：" + answer);
        System.out.println("要点：模型编的工具名被注册表白名单拦住，错误回传后模型自己改口。");
        System.out.println();
    }

    /** 场景三：模型传了非法参数。 */
    private static void demoInvalidArguments(ToolRegistry registry, ToolContext context) {
        System.out.println("=== 场景三：参数不是合法 JSON ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-3", "list_devices", "这不是JSON")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 20));
        fake.enqueueResponse(
                "我重新查一下设备。",
                FinishReason.STOP, new TokenUsage(150, 20));

        ToolCallingService service = new ToolCallingService("deepseek-v4-flash", fake, registry, context, 5);
        String answer = service.run("你是场景管理助手", "看看设备");

        System.out.println("最终答复：" + answer);
        System.out.println("要点：参数解析失败是预期内事件，变成错误回传，而不是让程序崩掉。");
        System.out.println();
    }

    /** 场景四：破坏性工具不执行，只回传「等待确认」。 */
    private static void demoDestructiveNeedsConfirmation(ToolRegistry registry, ToolContext context) {
        System.out.println("=== 场景四：破坏性工具被拦下，等待人工确认 ★ ===");

        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-4", "delete_device",
                        "{\"targetId\":\"cam-01\"}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
        fake.enqueueResponse(
                "我准备删除摄像头 cam-01，这是一次不可逆操作，请确认是否继续。",
                FinishReason.STOP, new TokenUsage(180, 40));

        ToolCallingService service = new ToolCallingService("deepseek-v4-flash", fake, registry, context, 5);
        String answer = service.run("你是场景管理助手", "把 cam-01 删掉");

        System.out.println("最终答复：" + answer);
        System.out.println("要点：★ 模型「能调」delete_device，但程序「不执行」，只回传等待确认。");
        System.out.println("     删除是否发生，决定权在程序（进而在人），不在模型。");
        System.out.println();
    }

    /** 场景五：模型一直调工具，达到轮数上限。 */
    private static void demoMaxRounds(ToolRegistry registry, ToolContext context) {
        System.out.println("=== 场景五：模型陷入工具循环，被轮数上限打断 ===");

        FakeModelClient fake = new FakeModelClient();
        // 连续三轮都调 list_devices，永远不给最终答复。
        for (int i = 0; i < 3; i++) {
            fake.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall("call-loop-" + i, "list_devices", "{}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        }

        ToolCallingService service = new ToolCallingService("deepseek-v4-flash", fake, registry, context, 3);
        String answer = service.run("你是场景管理助手", "看看设备");

        System.out.println("最终答复：" + answer);
        System.out.println("要点：maxToolRounds 是防死循环烧钱的保险丝，不是业务逻辑。");
        System.out.println();
    }

    /** 构造工具注册表：三个工具，覆盖三种副作用等级。 */
    private static ToolRegistry buildRegistry() {
        ToolRegistry registry = new ToolRegistry();

        // 只读工具：列出设备。
        registry.register(new ToolDefinition(
                "list_devices",
                "列出当前场景里的所有设备及其类型",
                "{\"type\":\"object\",\"properties\":{}}",
                ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        SceneSnapshot scene = context.getScene();
                        if (scene.getDeviceCount() == 0) {
                            return ToolExecutionResult.success("当前场景没有设备。");
                        }
                        StringBuilder sb = new StringBuilder("当前设备：");
                        for (Map.Entry<String, DeviceType> e : scene.getDevices().entrySet()) {
                            sb.append(e.getKey()).append("（").append(e.getValue().getWireValue()).append("）、");
                        }
                        return ToolExecutionResult.success(sb.toString());
                    }
                }));

        // 写工具：新增设备（本课只生成预览，不落库）。
        registry.register(new ToolDefinition(
                "create_device",
                "在指定坐标新增一台设备",
                "{\"type\":\"object\",\"properties\":{\"deviceType\":{\"type\":\"string\"},"
                        + "\"x\":{\"type\":\"integer\"},\"y\":{\"type\":\"integer\"}}}",
                ToolEffect.WRITE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success(
                                "已生成新增设备预览（未落库）：" + arguments.toString());
                    }
                }));

        // 破坏性工具：删除设备。必须人工确认。
        registry.register(new ToolDefinition(
                "delete_device",
                "删除指定设备（不可逆，需人工确认）",
                "{\"type\":\"object\",\"properties\":{\"targetId\":{\"type\":\"string\"}}}",
                ToolEffect.DESTRUCTIVE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success(
                                "已删除设备：" + arguments.path("targetId").asText());
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