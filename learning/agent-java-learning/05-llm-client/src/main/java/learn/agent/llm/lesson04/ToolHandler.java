package learn.agent.llm.lesson04;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * 工具的真正执行逻辑。
 *
 * <p>只有一个方法，职责边界很窄：<b>拿到已经解析好的参数，干活，返回结果</b>。</p>
 *
 * <p>handler 里<b>不需要</b>做这些事，它们已经在 {@link ToolRegistry#prepare} 里做完了：</p>
 * <ul>
 *   <li>判断工具名对不对 —— 能进到 handler 说明已经查到了定义；</li>
 *   <li>把 {@code arguments} 字符串解析成 JSON —— 传进来的已经是 {@link JsonNode}；</li>
 *   <li>判断参数是不是一个 JSON 对象 —— 已经确认过。</li>
 * </ul>
 *
 * <p>这么切分的原因是<b>「检查」和「产生副作用」必须能分开测</b>。
 * 参数校验的测试不应该真的去删数据。</p>
 *
 * <p>但 handler <b>仍然要做</b>业务校验：设备是否存在、坐标是否越界、
 * 设备是否受保护。这正是第 3 课的结论 ——「结构正确不代表业务合法」 ——
 * 在工具调用上的复用：JSON Schema 只能保证 {@code targetId} 是个字符串，
 * 保证不了这个 id 真的存在。</p>
 *
 * <p>注意签名里没有 {@code throws}。handler 当然可以抛运行时异常，
 * 但那属于<b>意外</b>；预期内的失败应当返回 {@link ToolExecutionResult#error}。
 * 真抛出来的异常由 {@link ToolRegistry#invoke} 在边界上兜住。</p>
 */
public interface ToolHandler {

    /**
     * 执行工具。
     *
     * @param arguments 已解析且确认为 JSON 对象的参数；无参调用时是空对象
     * @param context   程序提供的受控运行环境
     * @return 执行结果；失败时返回 {@link ToolExecutionResult#error} 而不是抛异常
     */
    ToolExecutionResult execute(JsonNode arguments, ToolContext context);
}
