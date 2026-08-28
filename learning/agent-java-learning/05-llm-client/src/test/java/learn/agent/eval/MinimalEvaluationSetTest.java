package learn.agent.eval;

import learn.agent.llm.lesson03.DeviceType;
import learn.agent.llm.lesson03.OperationPreview;
import learn.agent.llm.lesson03.SceneSnapshot;
import learn.agent.llm.lesson03.SceneOperationService;
import learn.agent.llm.lesson03.ValidationResult;

import learn.agent.llm.lesson04.ToolCall;
import learn.agent.llm.lesson04.ToolCallCodec;
import learn.agent.llm.lesson04.ToolCallingService;
import learn.agent.llm.lesson04.ToolContext;
import learn.agent.llm.lesson04.ToolDefinition;
import learn.agent.llm.lesson04.ToolEffect;
import learn.agent.llm.lesson04.ToolExecutionResult;
import learn.agent.llm.lesson04.ToolHandler;
import learn.agent.llm.lesson04.ToolRegistry;

import learn.agent.llm.lesson05.AgentLoop;
import learn.agent.llm.lesson05.AgentTrace;
import learn.agent.llm.lesson05.StopReason;
import learn.agent.llm.lesson05.TraceIdGenerator;

import learn.agent.llm.lesson05.AgentLoop;
import learn.agent.llm.lesson05.AgentTrace;
import learn.agent.llm.lesson05.RoundTrace;
import learn.agent.llm.lesson05.StopReason;
import learn.agent.llm.lesson05.TraceIdGenerator;

import learn.agent.llm.lesson01.FakeModelClient;
import learn.agent.llm.lesson01.FinishReason;
import learn.agent.llm.lesson01.TokenUsage;

import com.fasterxml.jackson.databind.JsonNode;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.Collections;

import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 最小评估集：跨第 3 课（Structured Output）、第 4 课（Tool Calling）
 * 和第 5 课（Agent Loop）的回归基线。
 *
 * <p>贯穿项要求「拿到第一个 Structured Output 就建」，本套件把各条链路的
 * 典型输入与期望结果做成一张可运行的表。每次改动业务代码后跑一遍，
 * 用结论判断改动是变好还是变坏。每进入一个新阶段往里加 3-5 行覆盖新能力。</p>
 *
 * <p>为什么用 JUnit 而不是一张静态表格：静态表只能被人脑对照，改完代码
 * 没有强制抓手。这套件把每一行变成可执行断言，结论不再是口头判断，而是
 * 测试结果 —— 这才是「改完代码先跑评估」里「先跑」二字的实现。</p>
 */
public class MinimalEvaluationSetTest {

    /** 断言函数返回的失败原因；通过时为 null。 */
    private interface Check {
        String run() throws Exception;
    }

    /** 评估集的一行。 */
    private static final class Row {
        final String label;
        final String code;   // 人类可读的期望结论
        final Check check;

        Row(String label, String code, Check check) {
            this.label = label;
            this.code = code;
            this.check = check;
        }
    }

    /** 场景：20x20，上限 5，cam-01 受保护。 */
    private static SceneSnapshot scene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-01", DeviceType.RADAR);
        devices.put("cam-01", DeviceType.CAMERA);
        devices.put("fence-main", DeviceType.FENCE);
        return new SceneSnapshot(20, 20, 5, devices,
                Collections.singleton("cam-01"));
    }

    /** 一个会统计 list 调用次数、且 delete 永不真正执行的注册表。 */
    private static ToolRegistry registryWith(AtomicInteger listCalls) {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition(
                "list_devices", "列出设备", "{}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        listCalls.incrementAndGet();
                        return ToolExecutionResult.success("设备：radar-01, cam-01, fence-main");
                    }
                }));
        // 破坏性工具：handler 存在但不应被调用（服务层会拦）。
        registry.register(new ToolDefinition(
                "delete_device", "删除设备（不可逆）", "{}", ToolEffect.DESTRUCTIVE,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success("已删除"); // 不应被执行
                    }
                }));
        return registry;
    }

    /**
     * 规则：11 条基线用例全部通过，任何一条挂了都要指出是哪一条。
     *
     * <p>这几条链路后面还会反复改（加权限、加日志、换实现）。没有基线，
     * 改完只能靠人工看一遍，改错误码或改 TOOL 回传前缀这类小改动很容易漏掉。</p>
     */
    @Test
    @DisplayName("最小评估集：Structured Output + Tool Calling + Agent Loop 回归基线")
    public void entireEvaluationSetMustPass() throws Exception {
        List<Row> rows = rows();
        List<String> failures = new ArrayList<String>();

        // 逐行跑并收集全部失败，不遇错即停 —— 和校验层「一次报全错」同理。
        for (Row row : rows) {
            String failure = null;
            try {
                failure = row.check.run();
            } catch (Exception e) {
                failure = "抛异常：" + e.getClass().getSimpleName() + ": " + e.getMessage();
            }
            if (failure != null) {
                failures.add(row.label + "（期望 " + row.code + "）：" + failure);
            }
        }

        // 无论成败都打印每一行的结论，便于人工核对当前基线。
        System.out.println("===== 最小评估集执行结果 =====");
        for (Row row : rows) {
            System.out.println("  [ " + row.code + " ] " + row.label);
        }

        assertTrue(failures.isEmpty(),
                "评估集存在失败行：\n" + String.join("\n", failures));
    }

    /** 组装评估集各行。 */
    private static List<Row> rows() throws Exception {
        List<Row> rows = new ArrayList<Row>();

        // ---------- 第 3 课：Structured Output ----------
        rows.add(new Row("合法 create 通过", "radar 预览",
                () -> {
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            "{\"operation\":\"create\",\"deviceType\":\"radar\",\"x\":5,\"y\":8,"
                                    + "\"reason\":\"用户要北侧加雷达\"}",
                            FinishReason.STOP, new TokenUsage(180, 40));
                    ValidationResult<OperationPreview> r =
                            new SceneOperationService(fake, "deepseek-v4-flash").propose("在北侧加雷达", scene());
                    if (!r.isValid()) {
                        return "期望合法，实际：" + r.getErrorMessage();
                    }
                    if (r.getValue().getOperation().getDeviceType() != DeviceType.RADAR) {
                        return "期望 radar，实际：" + r.getValue().getOperation().getDeviceType();
                    }
                    return null;
                }));

        rows.add(new Row("不存在的设备被拦", "isValid=false 且含真实清单",
                () -> {
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            "{\"operation\":\"move\",\"targetId\":\"radar-99\",\"x\":10,\"y\":10,"
                                    + "\"reason\":\"把雷达往东移\"}",
                            FinishReason.STOP, new TokenUsage(180, 30));
                    ValidationResult<OperationPreview> r =
                            new SceneOperationService(fake, "deepseek-v4-flash").propose("把雷达移到中间", scene());
                    if (r.isValid()) {
                        return "不存在的设备必须被拦下";
                    }
                    if (!r.getErrorMessage().contains("radar-01")) {
                        return "错误应列出真实设备清单，实际：" + r.getErrorMessage();
                    }
                    return null;
                }));

        rows.add(new Row("受保护设备禁止删除", "isValid=false",
                () -> {
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            "{\"operation\":\"delete\",\"targetId\":\"cam-01\","
                                    + "\"reason\":\"用户要删这台\"}",
                            FinishReason.STOP, new TokenUsage(150, 20));
                    ValidationResult<OperationPreview> r =
                            new SceneOperationService(fake, "deepseek-v4-flash").propose("把 cam-01 删了", scene());
                    if (r.isValid()) {
                        return "受保护设备删除必须被拦下";
                    }
                    return null;
                }));

        // ---------- 第 4 课：Tool Calling ----------
        rows.add(new Row("一次完整往返", "tool 执行一次后给最终答复",
                () -> {
                    AtomicInteger listCalls = new AtomicInteger();
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            ToolCallCodec.encode(new ToolCall("c1", "list_devices", "{}")),
                            FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
                    fake.enqueueResponse("当前有 3 台设备。", FinishReason.STOP, new TokenUsage(150, 20));
                    String answer = new ToolCallingService("m", fake, registryWith(listCalls),
                            new ToolContext("eval", scene()), 5).run("你是助手", "有哪些设备？");
                    if (!"当前有 3 台设备。".equals(answer)) {
                        return "期望最终答复，实际：" + answer;
                    }
                    if (listCalls.get() != 1) {
                        return "list_devices 应恰好执行一次，实际：" + listCalls.get();
                    }
                    return null;
                }));

        rows.add(new Row("破坏性工具不执行", "delete 不产生副作用",
                () -> {
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            ToolCallCodec.encode(new ToolCall("c1", "delete_device", "{\"targetId\":\"cam-01\"}")),
                            FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
                    fake.enqueueResponse("我准备删除 cam-01，请确认。", FinishReason.STOP, new TokenUsage(150, 20));
                    String answer = new ToolCallingService("m", fake, registryWith(new AtomicInteger()),
                            new ToolContext("eval", scene()), 5).run("你是助手", "删掉 cam-01");
                    if (!answer.contains("确认")) {
                        return "破坏性工具应回传等待确认，实际：" + answer;
                    }
                    return null;
                }));

        rows.add(new Row("模型幻觉未知工具", "tool_not_found 后恢复",
                () -> {
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            ToolCallCodec.encode(new ToolCall("c1", "delete_everything", "{}")),
                            FinishReason.TOOL_CALLS, new TokenUsage(120, 20));
                    fake.enqueueResponse("抱歉，我没有这个权限。", FinishReason.STOP, new TokenUsage(150, 20));
                    String answer = new ToolCallingService("m", fake, registryWith(new AtomicInteger()),
                            new ToolContext("eval", scene()), 5).run("你是助手", "清空场景");
                    if (!"抱歉，我没有这个权限。".equals(answer)) {
                        return "模型应恢复并给出答复，实际：" + answer;
                    }
                    return null;
                }));

        rows.add(new Row("轮数上限打断死循环", "达到上限即停",
                () -> {
                    FakeModelClient fake = new FakeModelClient();
                    for (int i = 0; i < 3; i++) {
                        fake.enqueueResponse(
                                ToolCallCodec.encode(new ToolCall("loop" + i, "list_devices", "{}")),
                                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
                    }
                    String answer = new ToolCallingService("m", fake, registryWith(new AtomicInteger()),
                            new ToolContext("eval", scene()), 3).run("你是助手", "看看");
                    if (!answer.contains("最大工具调用轮数")) {
                        return "达到上限应停止，实际：" + answer;
                    }
                    return null;
                }));

        // ---------- 第 5 课：Agent Loop ----------
        rows.add(new Row("停止原因是枚举而非文本", "stop=final_answer",
                () -> {
                    AtomicInteger listCalls = new AtomicInteger();
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            ToolCallCodec.encode(new ToolCall("c1", "list_devices", "{}")),
                            FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
                    fake.enqueueResponse("当前有 3 台设备。", FinishReason.STOP, new TokenUsage(150, 20));
                    AgentTrace trace = new AgentLoop("m", fake, registryWith(listCalls),
                            new ToolContext("eval", scene()), 5, 1000L,
                            TraceIdGenerator.fixed("eval-1")).run("你是助手", "有哪些设备？");
                    if (trace.getStopReason() != StopReason.FINAL_ANSWER) {
                        return "期望 FINAL_ANSWER，实际：" + trace.getStopReason();
                    }
                    if (trace.getRoundCount() != 2) {
                        return "期望 2 轮，实际：" + trace.getRoundCount();
                    }
                    if (!"eval-1".equals(trace.getTraceId())) {
                        return "trace id 应可注入，实际：" + trace.getTraceId();
                    }
                    return null;
                }));

        rows.add(new Row("轮数耗尽可被程序识别", "stop=max_rounds",
                () -> {
                    FakeModelClient fake = new FakeModelClient();
                    for (int i = 0; i < 3; i++) {
                        fake.enqueueResponse(
                                ToolCallCodec.encode(new ToolCall("loop" + i, "list_devices", "{}")),
                                FinishReason.TOOL_CALLS, new TokenUsage(100, 20));
                    }
                    AgentTrace trace = new AgentLoop("m", fake, registryWith(new AtomicInteger()),
                            new ToolContext("eval", scene()), 3, 1000L,
                            TraceIdGenerator.fixed("eval-2")).run("你是助手", "看看");
                    if (trace.getStopReason() != StopReason.MAX_ROUNDS) {
                        return "期望 MAX_ROUNDS，实际：" + trace.getStopReason();
                    }
                    if (!trace.getStopReason().isAbnormal()) {
                        return "轮数耗尽属于异常收尾";
                    }
                    return null;
                }));

        rows.add(new Row("重复调用只执行一次", "outcome=deduplicated",
                () -> {
                    AtomicInteger listCalls = new AtomicInteger();
                    FakeModelClient fake = new FakeModelClient();
                    // 同名同参数连发两次，第二次应命中幂等缓存。
                    fake.enqueueResponse(
                            ToolCallCodec.encode(new ToolCall("c1", "list_devices", "{}")),
                            FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
                    fake.enqueueResponse(
                            ToolCallCodec.encode(new ToolCall("c2", "list_devices", "{}")),
                            FinishReason.TOOL_CALLS, new TokenUsage(140, 30));
                    fake.enqueueResponse("当前有 3 台设备。", FinishReason.STOP, new TokenUsage(160, 20));
                    AgentTrace trace = new AgentLoop("m", fake, registryWith(listCalls),
                            new ToolContext("eval", scene()), 5, 1000L,
                            TraceIdGenerator.fixed("eval-3")).run("你是助手", "有哪些设备？");
                    if (listCalls.get() != 1) {
                        return "handler 应只真正执行一次，实际：" + listCalls.get();
                    }
                    if (!"deduplicated".equals(trace.getRounds().get(1).getToolOutcome())) {
                        return "第 2 轮应命中缓存，实际：" + trace.getRounds().get(1).getToolOutcome();
                    }
                    return null;
                }));

        rows.add(new Row("每轮 trace 能归因", "含工具名与 tool_call_id",
                () -> {
                    AtomicInteger listCalls = new AtomicInteger();
                    FakeModelClient fake = new FakeModelClient();
                    fake.enqueueResponse(
                            ToolCallCodec.encode(new ToolCall("call-x", "list_devices", "{}")),
                            FinishReason.TOOL_CALLS, new TokenUsage(120, 30));
                    fake.enqueueResponse("好了。", FinishReason.STOP, new TokenUsage(150, 20));
                    AgentTrace trace = new AgentLoop("m", fake, registryWith(listCalls),
                            new ToolContext("eval", scene()), 5, 1000L,
                            TraceIdGenerator.fixed("eval-4")).run("你是助手", "有哪些设备？");
                    RoundTrace first = trace.getRounds().get(0);
                    if (!"list_devices".equals(first.getToolName())) {
                        return "第 1 轮应记下工具名，实际：" + first.getToolName();
                    }
                    if (!"call-x".equals(first.getToolCallId())) {
                        return "应原样记下 tool_call_id，实际：" + first.getToolCallId();
                    }
                    if (trace.getTotalTokens() != 320) {
                        return "token 应累加为 320，实际：" + trace.getTotalTokens();
                    }
                    return null;
                }));

        return rows;
    }
}