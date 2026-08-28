package learn.agent.llm.loop;

import java.util.LinkedHashMap;
import java.util.Map;

import learn.agent.llm.tool.ToolCall;
import learn.agent.llm.tool.ToolExecutionResult;

/**
 * 同一轮会话里，相同的工具调用只真正执行一次，后续命中缓存。
 *
 * <p>为什么需要：模型会重复请求同一个工具。常见有两种原因 ——
 * 一是它没「看懂」上一轮回传的结果，于是又问一遍；二是温度不为 0 时
 * 本身就有随机性。如果每次都真执行，只读工具浪费钱和时间，
 * <b>写工具会产生重复副作用</b>：连着调两次 create_device，场景里多两台设备。</p>
 *
 * <p>幂等键取「工具名 + 原始参数字符串」，<b>不含 tool_call_id</b>：
 * id 每次都不一样，把它算进键里就永远不会命中，等于没做。</p>
 *
 * <p>两段之间用 ASCII 单元分隔符（0x1F）连接，而不是冒号或空格。
 * 因为参数里完全可能出现冒号和空格，用它们分隔会让两个不同的调用
 * 算出同一个键；0x1F 不会出现在正常 JSON 文本里。</p>
 *
 * <p><b>边界（本课刻意不做，但你要知道）：</b></p>
 * <ul>
 *   <li>缓存只活在一次 {@code run} 里，不跨会话。跨会话幂等要落 Redis，
 *       就是阶段 4 学的 {@code SETNX + TTL}。</li>
 *   <li>参数字符串比较是<b>字面量</b>比较：{@code {"a":1,"b":2}} 和
 *       {@code {"b":2,"a":1}} 语义相同但键不同，会各执行一次。
 *       要真正规范化得把 JSON 键排序后再序列化。</li>
 *   <li>失败结果<b>不缓存</b>：工具报错往往是暂时的（超时、限流），
 *       缓存失败会让模型连重试的机会都没有。</li>
 * </ul>
 */
public class ToolCallMemo {

    /**
     * 幂等键的分隔符：ASCII 单元分隔符 0x1F。
     *
     * <p>用 {@code (char) 0x1F} 而不是直接把这个不可见字符敲进源码，
     * 是因为源码里的隐形字节会被各种编辑器和编码转换悄悄改掉。</p>
     */
    private static final String SEPARATOR = String.valueOf((char) 0x1F);

    /** LinkedHashMap 保留插入顺序，方便调试时看清模型重复调了什么。 */
    private final Map<String, ToolExecutionResult> cache =
            new LinkedHashMap<String, ToolExecutionResult>();

    /** 命中次数，用于测试和日志。 */
    private int hitCount = 0;

    /**
     * 算一次调用的幂等键。
     *
     * <p>刻意排除 {@link ToolCall#getId()}：id 每次调用都不同，
     * 算进去就永远不会命中。</p>
     */
    public static String keyOf(ToolCall call) {
        String raw = call.getRawArguments();
        String normalized = (raw == null || raw.trim().isEmpty()) ? "{}" : raw.trim();
        return call.getName() + SEPARATOR + normalized;
    }

    /**
     * 查缓存。
     *
     * @return 之前的成功结果；没有则返回 null
     */
    public ToolExecutionResult lookup(ToolCall call) {
        ToolExecutionResult cached = cache.get(keyOf(call));
        if (cached != null) {
            hitCount++;
        }
        return cached;
    }

    /**
     * 记录一次执行结果。
     *
     * <p><b>只缓存成功。</b>失败常常是暂时的（超时、限流、下游抖动），
     * 缓存失败等于把一次偶发故障变成这轮会话里的永久故障。</p>
     */
    public void remember(ToolCall call, ToolExecutionResult result) {
        if (result == null || result.isError()) {
            return;
        }
        cache.put(keyOf(call), result);
    }

    /** @return 缓存命中的次数 */
    public int getHitCount() {
        return hitCount;
    }

    /** @return 缓存里有多少条不同的调用 */
    public int size() {
        return cache.size();
    }
}
