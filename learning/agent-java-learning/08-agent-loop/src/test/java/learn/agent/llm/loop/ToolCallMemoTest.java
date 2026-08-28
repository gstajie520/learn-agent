package learn.agent.llm.loop;

import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolExecutionResult;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;

/**
 * {@link ToolCallMemo} 的测试：幂等键怎么算，什么该缓存、什么不该。
 */
public class ToolCallMemoTest {

    /** 幂等键不含 tool_call_id：id 每次都不同，算进去就永远不会命中。 */
    @Test
    public void keyShouldIgnoreToolCallId() {
        String first = ToolCallMemo.keyOf(new ToolCall("call-1", "list_devices", "{}"));
        String second = ToolCallMemo.keyOf(new ToolCall("call-2", "list_devices", "{}"));

        assertEquals(first, second);
    }

    /** 工具名相同但参数不同，是两次不同的调用，不能互相命中。 */
    @Test
    public void keyShouldDistinguishDifferentArguments() {
        String radar = ToolCallMemo.keyOf(
                new ToolCall("call-1", "create_device", "{\"type\":\"radar\"}"));
        String camera = ToolCallMemo.keyOf(
                new ToolCall("call-2", "create_device", "{\"type\":\"camera\"}"));

        assertNotEquals(radar, camera);
    }

    /** 空参数和 "{}" 归一成同一个键，避免模型两种写法各执行一次。 */
    @Test
    public void keyShouldNormalizeEmptyArguments() {
        String empty = ToolCallMemo.keyOf(new ToolCall("call-1", "list_devices", ""));
        String braces = ToolCallMemo.keyOf(new ToolCall("call-2", "list_devices", "{}"));

        assertEquals(empty, braces);
    }

    /** 成功结果被缓存，第二次同样的调用直接拿到同一个对象。 */
    @Test
    public void shouldCacheSuccessResult() {
        ToolCallMemo memo = new ToolCallMemo();
        ToolCall call = new ToolCall("call-1", "list_devices", "{}");
        ToolExecutionResult result = ToolExecutionResult.success("cam-01");

        memo.remember(call, result);

        assertSame(result, memo.lookup(new ToolCall("call-9", "list_devices", "{}")));
        assertEquals(1, memo.getHitCount());
    }

    /** 失败结果不缓存：超时、限流往往是暂时的，缓存失败会掐掉重试机会。 */
    @Test
    public void shouldNotCacheErrorResult() {
        ToolCallMemo memo = new ToolCallMemo();
        ToolCall call = new ToolCall("call-1", "list_devices", "{}");

        memo.remember(call, ToolExecutionResult.error("tool_timeout", "超时"));

        assertNull(memo.lookup(call), "失败不该被缓存");
        assertEquals(0, memo.size());
    }
}
