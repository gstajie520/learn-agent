package learn.agent.llm.hook;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRequest;
import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.loop.StopReason;
import learn.agent.llm.loop.ToolRoundObserver;
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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * {@link ToolRoundObserver} 接进 {@link HookedAgentLoop} 之后的行为。
 *
 * <h3>这个测试类要证明的那一件事</h3>
 * <p><b>观察器的请求级指导不进消息历史。</b>这是它和 Hook 的分界线，也是
 * 这个扩展点存在的全部理由 —— 如果它进了历史，那它就只是 Hook 的
 * {@code additionalContext} 换了个名字，没有任何必要新增一个扩展点。</p>
 *
 * <h3>一段需要如实记下的背景</h3>
 * <p>本项目此前把「陈旧提醒」接在 {@code PostToolUse} 上（{@code PlanReminderHook}），
 * 并在笔记里把由此产生的落差写成了「Hook 表达不了请求级临时上下文，要等后面的
 * 课引入 Provider 才能解决」。<b>那个结论是错的。</b>教材在讲会话计划的那一章
 * 就已经给了这个扩展点（{@code toolRoundObserver}）：每次请求前调一次
 * {@code beforeModel()}，把结果拼进本次请求、<b>不写进历史</b>。</p>
 *
 * <p>换句话说，落差不是「Hook 的设计缺陷」，而是<b>我们的循环少抄了一个扩展点</b>。
 * 顺带纠正另一处：Provider 管的是「整个系统提示怎么组装」，和「这一次请求要不要
 * 多带一句提醒」是两件不同的事，教材里也是两个不同的扩展点。</p>
 *
 * <p>之所以把这段写在测试里而不只是提交信息里：<b>结论错过一次，就该在代码里
 * 留下防止再错的东西。</b>下面每条断言都是那个错误结论的反证。</p>
 */
public class ToolRoundObserverTest {

    /** 场景：20x20，上限 5，cam-01 受保护。 */
    private static SceneSnapshot scene() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("radar-01", DeviceType.RADAR);
        devices.put("cam-01", DeviceType.CAMERA);
        return new SceneSnapshot(20, 20, 5, devices, Collections.singleton("cam-01"));
    }

    private static ToolContext context() {
        return new ToolContext("observer-user", scene());
    }

    /** 一个可编排的观察器：指导内容按队列发出，记账全部记下来。 */
    private static final class FakeObserver implements ToolRoundObserver {
        final List<List<String>> recorded = new ArrayList<List<String>>();
        final List<String> guidanceQueue = new ArrayList<String>();
        int beforeModelCalls;

        /** 让第 n 次 beforeModel 发出一句指导；用 null 表示这一次什么都不发。 */
        FakeObserver enqueueGuidance(String text) {
            guidanceQueue.add(text);
            return this;
        }

        @Override
        public List<ChatMessage> beforeModel() {
            int index = beforeModelCalls;
            beforeModelCalls++;
            if (index >= guidanceQueue.size()) {
                return Collections.emptyList();
            }
            String text = guidanceQueue.get(index);
            if (text == null) {
                return Collections.emptyList();
            }
            return Collections.singletonList(ChatMessage.system(text));
        }

        @Override
        public void recordToolRound(List<String> toolNames) {
            recorded.add(new ArrayList<String>(toolNames));
        }
    }

    /**
     * 规则：{@code beforeModel()} 的指导只进这一次请求，<b>不进消息历史</b>。
     *
     * <p>这是本类的头号命题。做法是只在第一轮发一句指导，然后检查第二轮的请求 ——
     * 如果它进了历史，第二轮会再看到同一句话。</p>
     *
     * <p>违反会怎样：跑三十轮就攒下十条一模一样的提醒，每一轮都要为它付 token；
     * 更糟的是这段历史被存档或用于微调时，里面混着<b>从来没有人说过的话</b>。</p>
     */
    @Test
    @DisplayName("beforeModel 的指导只进当次请求，不进历史")
    void shouldNotLeakGuidanceIntoHistory() {
        FakeObserver observer = new FakeObserver();
        observer.enqueueGuidance("请保持计划更新");

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(ToolCallCodec.encode(new ToolCall("c1", "inspect", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(10, 5));
        client.enqueueResponse("radar-01 在线。", FinishReason.STOP, new TokenUsage(10, 5));

        run(client, observer);

        // 第一轮：指导确实被送进了模型请求。
        List<ChatMessage> first = client.getRequest(0).getMessages();
        assertTrue(containsContent(first, "请保持计划更新"),
                "第一轮请求应当带上这次的指导");

        // 第二轮：同一句话不该再出现 —— 它没有被写进历史。
        List<ChatMessage> second = client.getRequest(1).getMessages();
        assertFalse(containsContent(second, "请保持计划更新"),
                "指导进了消息历史：第二轮又看到了同一句话，这正是走 Hook 那条路的代价");
    }

    /**
     * 规则：每轮请求前<b>只调一次</b> {@code beforeModel()}。
     *
     * <p>为什么这条重要：{@code beforeModel()} 允许有副作用（{@code TodoTracker}
     * 就是「读取即清零」）。同一轮里调第二次会把本该发出的提醒<b>悄悄吞掉</b> ——
     * 计数已经清零，而那句话没有进任何一次请求。</p>
     */
    @Test
    @DisplayName("每轮只调一次 beforeModel，不重复消费其副作用")
    void shouldCallBeforeModelExactlyOncePerRound() {
        FakeObserver observer = new FakeObserver();

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(ToolCallCodec.encode(new ToolCall("c1", "inspect", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(10, 5));
        client.enqueueResponse("radar-01 在线。", FinishReason.STOP, new TokenUsage(10, 5));

        run(client, observer);

        // 两轮模型请求，两次 beforeModel，一次不多一次不少。
        assertEquals(2, client.getCallCount(), "本剧本应当发两次模型请求");
        assertEquals(2, observer.beforeModelCalls,
                "beforeModel 的调用次数必须和模型请求次数一致");
    }

    /**
     * 规则：{@code recordToolRound} 在工具结果<b>已经进历史之后</b>才触发，
     * 且拿到的是这一轮真实调用的工具名。
     *
     * <p>顺序为什么重要：观察器可能在下一次 {@code beforeModel()} 里读自己的状态
     * 做判断。提前记账会让它在一个 assistant 消息已入、tool 结果未入的
     * <b>半成品历史</b>上做决定，而那一刻的消息序列是不配对的。</p>
     */
    @Test
    @DisplayName("recordToolRound 在结果落进历史后触发，并带上本轮工具名")
    void shouldRecordToolRoundAfterResultLandsInHistory() {
        FakeObserver observer = new FakeObserver();

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(ToolCallCodec.encode(new ToolCall("c1", "inspect", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(10, 5));
        client.enqueueResponse("radar-01 在线。", FinishReason.STOP, new TokenUsage(10, 5));

        run(client, observer);

        assertEquals(1, observer.recorded.size(), "一个工具轮应当记账一次");
        assertEquals(Collections.singletonList("inspect"), observer.recorded.get(0),
                "记账应当带上这一轮实际调用的工具名");

        // 记账发生时结果已在历史里：第二轮请求能看到那条工具结果。
        List<ChatMessage> second = client.getRequest(1).getMessages();
        assertTrue(containsContent(second, "radar-01 在线"),
                "第二轮请求里应当已经有上一轮的工具结果");
    }

    /**
     * 规则：没有工具调用的那一轮<b>不记账</b>。
     *
     * <p>「陈旧」的语义是「一直在调别的工具、就是不更新计划」。模型直接回答
     * 不算一轮工具活动，把它算进去会让提醒提前发出。</p>
     */
    @Test
    @DisplayName("模型直接回答的轮次不记账")
    void shouldNotRecordRoundWithoutToolCall() {
        FakeObserver observer = new FakeObserver();

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse("不需要查设备，直接回答你。", FinishReason.STOP, new TokenUsage(10, 5));

        GuardedTrace trace = run(client, observer);

        assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
        assertTrue(observer.recorded.isEmpty(), "没有工具调用的轮次不该记账");
        // 但 beforeModel 仍然被问过一次 —— 每次请求前都要问。
        assertEquals(1, observer.beforeModelCalls);
    }

    /**
     * 规则：观察器为 null 时行为和以前<b>完全一致</b>。
     *
     * <p>这条守的是兼容性：新增扩展点不能改变既有调用点的行为。九参数构造器
     * 仍然可用，且不会因为多了一个字段而出现空指针。</p>
     */
    @Test
    @DisplayName("不传观察器时循环行为不变")
    void shouldWorkWithoutObserver() {
        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse(ToolCallCodec.encode(new ToolCall("c1", "inspect", "{}")),
                FinishReason.TOOL_CALLS, new TokenUsage(10, 5));
        client.enqueueResponse("radar-01 在线。", FinishReason.STOP, new TokenUsage(10, 5));

        HookedAgentLoop loop = new HookedAgentLoop("m", client, registry(), context(),
                5, 2000L, TraceIdGenerator.fixed("observer"), null, new HookRegistry());
        try {
            GuardedTrace trace = loop.run("你是助手", "看一下设备");
            assertEquals(StopReason.FINAL_ANSWER, trace.getStopReason());
            assertEquals("radar-01 在线。", trace.getFinalAnswer());
        } finally {
            loop.shutdown();
        }
    }

    /**
     * 规则：指导为空列表时，<b>请求内容和没有观察器时一样</b>。
     *
     * <p>也就是说「有观察器但这轮没话说」不该在请求里留下任何痕迹 ——
     * 比如一条空的 system 消息。空消息会白占 token，还可能被模型当成信号。</p>
     */
    @Test
    @DisplayName("指导为空时不往请求里塞任何多余消息")
    void shouldAddNothingWhenGuidanceIsEmpty() {
        FakeObserver observer = new FakeObserver();
        // 队列为空 => 每次 beforeModel 都返回空列表。

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse("直接回答。", FinishReason.STOP, new TokenUsage(10, 5));
        run(client, observer);
        int withObserver = client.getRequest(0).getMessages().size();

        FakeModelClient bare = new FakeModelClient();
        bare.enqueueResponse("直接回答。", FinishReason.STOP, new TokenUsage(10, 5));
        HookedAgentLoop loop = new HookedAgentLoop("m", bare, registry(), context(),
                5, 2000L, TraceIdGenerator.fixed("observer"), null, new HookRegistry());
        try {
            loop.run("你是助手", "看一下设备");
        } finally {
            loop.shutdown();
        }
        int withoutObserver = bare.getRequest(0).getMessages().size();

        assertEquals(withoutObserver, withObserver,
                "空指导不该让请求多出任何一条消息");
    }

    // ---------- 脚手架 ----------

    /** 跑一次带观察器的循环，用完即关。 */
    private static GuardedTrace run(FakeModelClient client, ToolRoundObserver observer) {
        HookedAgentLoop loop = new HookedAgentLoop("m", client, registry(), context(),
                5, 2000L, TraceIdGenerator.fixed("observer"), null, new HookRegistry(), observer);
        try {
            return loop.run("你是助手", "看一下设备");
        } finally {
            loop.shutdown();
        }
    }

    private static ToolRegistry registry() {
        ToolRegistry registry = new ToolRegistry();
        registry.register(new ToolDefinition("inspect", "查看设备",
                "{\"type\":\"object\"}", ToolEffect.READ,
                new ToolHandler() {
                    @Override
                    public ToolExecutionResult execute(JsonNode arguments, ToolContext context) {
                        return ToolExecutionResult.success("radar-01 在线");
                    }
                }));
        return registry;
    }

    /** 消息列表里有没有哪条的内容包含这段文本。 */
    private static boolean containsContent(List<ChatMessage> messages, String fragment) {
        for (ChatMessage message : messages) {
            if (message.getContent() != null && message.getContent().contains(fragment)) {
                return true;
            }
        }
        return false;
    }
}
