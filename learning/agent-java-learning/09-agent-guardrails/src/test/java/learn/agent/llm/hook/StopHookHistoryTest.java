package learn.agent.llm.hook;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import learn.agent.llm.client.ChatMessage;
import learn.agent.llm.client.ChatRole;
import learn.agent.llm.client.FakeModelClient;
import learn.agent.llm.client.FinishReason;
import learn.agent.llm.client.TokenUsage;
import learn.agent.llm.loop.TraceIdGenerator;
import learn.agent.llm.permission.GuardedTrace;
import learn.agent.llm.structured.DeviceType;
import learn.agent.llm.structured.SceneSnapshot;
import learn.agent.llm.tool.ToolContext;
import learn.agent.llm.tool.ToolRegistry;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 取证用探针：Stop Hook 强制续写时，模型自己那条答复有没有进历史。
 *
 * <p>现有的 {@code HookedAgentLoopTest#shouldAllowExactlyOneForcedContinuation}
 * 只断言轮数和 finalAnswer，而 {@link FakeModelClient} 不读历史，所以测不出
 * 「第二轮模型看不见自己第一轮说了什么」这件事。这里直接检查第二次请求的
 * messages 内容。</p>
 */
public class StopHookHistoryTest {

    /**
     * Stop Hook 续写后，第二次请求的历史里必须有第一轮那条 assistant 答复。
     *
     * <p>这是「其实还没完，接着做」语义成立的前提：模型得先看见自己上一轮的
     * 结论，才能在同一条思路上往下续。看不见的话，续写请求对它来说是一次
     * 无来由的重问。</p>
     */
    @Test
    public void shouldKeepModelAnswerInHistoryWhenStopHookForcesContinuation() {
        HookRegistry hooks = new HookRegistry();
        hooks.register(HookEvent.STOP, new HookCallback() {
            @Override
            public HookResult handle(HookContext context) {
                return HookResult.builder()
                        .forceContinue(ChatMessage.user("再检查一遍"))
                        .build();
            }
        });

        FakeModelClient client = new FakeModelClient();
        client.enqueueResponse("第一次答复：北区 2 台设备", FinishReason.STOP, new TokenUsage(10, 5));
        client.enqueueResponse("第二次答复", FinishReason.STOP, new TokenUsage(10, 5));

        GuardedTrace trace = run(client, hooks);
        assertEquals(2, trace.getRoundCount(), "前提：确实续写了一轮");

        List<ChatMessage> second = client.getRequest(1).getMessages();
        List<String> assistantContents = new ArrayList<String>();
        for (ChatMessage message : second) {
            if (message.getRole() == ChatRole.ASSISTANT) {
                assistantContents.add(message.getContent());
            }
        }

        assertTrue(assistantContents.contains("第一次答复：北区 2 台设备"),
                "第二次请求的历史里应当有第一轮那条 assistant 答复；实际收到的整条历史："
                        + second);
    }

    private static GuardedTrace run(FakeModelClient client, HookRegistry hooks) {
        HookedAgentLoop loop = new HookedAgentLoop("fake-model", client, new ToolRegistry(),
                context(), 5, 2000L, TraceIdGenerator.fixed("trace-probe-a"), null, hooks);
        try {
            return loop.run("你是设备助手", "检查设备");
        } finally {
            loop.shutdown();
        }
    }

    private static ToolContext context() {
        Map<String, DeviceType> devices = new LinkedHashMap<String, DeviceType>();
        devices.put("cam-01", DeviceType.CAMERA);
        return new ToolContext("operator-1", new SceneSnapshot(20, 20, 10, devices));
    }
}
