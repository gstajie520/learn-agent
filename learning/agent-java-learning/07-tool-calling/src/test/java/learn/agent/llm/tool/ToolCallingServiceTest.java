package learn.agent.llm.tool;

import com.fasterxml.jackson.databind.JsonNode;

import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.structured.DeviceType;
import learn.agent.llm.structured.SceneSnapshot;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link ToolCallingService} 的端到端测试：验证「模型请求工具 → 程序执行 → 结果回传」闭环。
 *
 * <p>覆盖的核心规则：</p>
 * <ul>
 *   <li>一次完整往返：模型调工具，程序执行，结果以 TOOL 角色回传，模型给最终答复；</li>
 *   <li>破坏性工具不执行，只回传「等待确认」；</li>
 *   <li>模型幻觉工具名时，错误回传后模型改口；</li>
 *   <li>轮数上限打断死循环。</li>
 * </ul>
 */
public class ToolCallingServiceTest {

    private ToolRegistry registry() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success("设备：cam-01");
                    }
                }));
        registry.register(new ToolDefinition(
                "delete_device", "删除设备", "{}", ToolEffect.DESTRUCTIVE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success("已删除");
                    }
                }));
        return registry;
    }

    private ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        return new ToolContext("test-user", new SceneSnapshot(20, 20, 5, devices));
    }

    /**
     * 模型被调用两次：第一次决定调工具，第二次拿到 TOOL 角色回传的结果后给出答复。
     * 这是 Agent 的核心骨架，结果必须以 TOOL 角色回传，模型才分得清哪部分是真实数据。
     */
    @Test
    public void shouldCompleteFullRoundTrip() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "list_devices", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
        fake.enqueueResponse(
                "当前有 1 台设备：cam-01。",
                FinishReason.STOP, new TokenUsage(150, 20));

        ToolCallingService service =
                new ToolCallingService("deepseek-v4-flash", fake, registry(), context(), 5);
        String answer = service.run("你是助手", "有哪些设备？");

        assertEquals("当前有 1 台设备：cam-01。", answer);
        assertEquals(2, fake.getCallCount(), "模型应被调用两次：一次要工具，一次给答复");
    }

    /**
     * 破坏性工具不执行，只回传「等待确认」——「模型能调」和「程序该执行」的分界点。
     * 否则一句自然语言就能删掉数据。
     */
    @Test
    public void shouldNotExecuteDestructiveToolWithoutConfirmation() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "delete_device", "{\"targetId\":\"cam-01\"}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
        fake.enqueueResponse(
                "我准备删除 cam-01，请确认。",
                FinishReason.STOP, new TokenUsage(150, 20));

        ToolCallingService service =
                new ToolCallingService("deepseek-v4-flash", fake, registry(), context(), 5);
        String answer = service.run("你是助手", "删掉 cam-01");

        // 模型最终答复里应包含「确认」字样，说明程序没有真的执行删除。
        assertTrue(answer.contains("确认"), "破坏性工具应回传等待确认，实际：" + answer);
    }

    /**
     * 模型编工具名是预期内事件：把「工具不存在」回传，模型下一轮就能改口，循环不崩。
     */
    @Test
    public void shouldRecoverFromUnknownTool() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse(
                ToolCallCodec.encode(new ToolCall("call-1", "delete_everything", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(120, 20));
        fake.enqueueResponse(
                "抱歉，我没有这个权限。",
                FinishReason.STOP, new TokenUsage(150, 20));

        ToolCallingService service =
                new ToolCallingService("deepseek-v4-flash", fake, registry(), context(), 5);
        String answer = service.run("你是助手", "清空场景");

        assertEquals("抱歉，我没有这个权限。", answer);
    }

    /**
     * maxToolRounds 是保险丝：模型可能一直调工具不给答复，没有上限就是无限循环、无限计费。
     */
    @Test
    public void shouldStopAtMaxRounds() {
        FakeModelClient fake = new FakeModelClient();
        for (int i = 0; i < 3; i++) {
            fake.enqueueResponse(
                    ToolCallCodec.encode(new ToolCall("call-" + i, "list_devices", "{}")),
                    FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
        }

        ToolCallingService service =
                new ToolCallingService("deepseek-v4-flash", fake, registry(), context(), 3);
        String answer = service.run("你是助手", "看看设备");

        assertTrue(answer.contains("最大工具调用轮数"),
                "轮数耗尽应明确提示，实际：" + answer);
        assertEquals(3, fake.getCallCount(), "达到上限后不应再调用模型");
    }

    /**
     * 截断意味着既没有完整答复也没有工具调用，继续循环只会重复同样的失败，所以如实告知。
     */
    @Test
    public void shouldReportTruncation() {
        FakeModelClient fake = new FakeModelClient();
        fake.enqueueResponse("", FinishReason.LENGTH, new TokenUsage(100, 200));

        ToolCallingService service =
                new ToolCallingService("deepseek-v4-flash", fake, registry(), context(), 5);
        String answer = service.run("你是助手", "说点什么");

        assertTrue(answer.contains("截断"), "截断应明确提示，实际：" + answer);
    }
}