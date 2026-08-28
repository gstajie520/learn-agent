package learn.agent.llm.lesson04;

/**
 * 模型发起的一次工具调用请求。
 *
 * <p>这是本课的核心数据结构，也是和第 3 课最大的区别所在。</p>
 *
 * <p>第 3 课是<b>我们</b>要求模型填一张固定的表单（输出 {@code SceneOperation}
 * 的 JSON）。本课是<b>模型自己决定</b>要不要调工具、调哪个、传什么参数。
 * 决策权从程序转移到了模型手上 —— 这正是「聊天机器人」和「Agent」的分界线。</p>
 *
 * <h2>三个字段各自的坑</h2>
 *
 * <p><b>{@code id}</b>：服务端生成的调用标识。工具结果回传时必须带上同一个 id，
 * 否则模型不知道这份结果对应哪次调用。<b>这个字段绝不能自己造</b> ——
 * 详见 {@link AgentMessage#toolResult}。</p>
 *
 * <p><b>{@code name}</b>：模型选择的工具名。它是<b>不可信数据</b>：
 * 模型完全可能输出一个不存在的工具名（幻觉），也可能输出
 * {@code ../../etc/passwd} 这种试探性内容。所以必须在注册表里做白名单查找，
 * 而不是拿它去反射或拼路径。</p>
 *
 * <p><b>{@code rawArguments}</b>：参数。注意它的类型是 {@code String} 而不是
 * 对象或 Map —— 这不是本课的简化，而是<b>协议本身就是这样定的</b>：
 * OpenAI 兼容协议里 {@code function.arguments} 是一个「装着 JSON 的字符串」。</p>
 *
 * <pre>{@code
 * "function": { "name": "create_device", "arguments": "{\"deviceType\":\"radar\"}" }
 *                                                     ^ 整个 JSON 被塞进字符串里
 * }</pre>
 *
 * <p>为什么协议这么设计：流式输出时参数是一个 token 一个 token 吐出来的，
 * 中途并不是合法 JSON，用字符串承载才能边生成边传。代价是<b>它可能根本不是
 * 合法 JSON</b>，解析失败是预期内的情况，必须当成正常分支处理。</p>
 */
public class ToolCall {

    /** 服务端生成的调用 id，回传结果时必须原样带回。 */
    private final String id;

    /** 模型选择的工具名，属于不可信数据。 */
    private final String name;

    /** 未解析的参数文本；协议规定它是「装着 JSON 的字符串」。 */
    private final String rawArguments;

    public ToolCall(String id, String name, String rawArguments) {
        // id 为空会导致后面无法配对，这属于协议违约，必须立刻炸而不是拖到下游。
        if (id == null || id.trim().isEmpty()) {
            throw new IllegalArgumentException("toolCallId 不能为空，工具结果无法配对");
        }
        if (name == null || name.trim().isEmpty()) {
            throw new IllegalArgumentException("工具名不能为空");
        }
        this.id = id.trim();
        this.name = name.trim();
        // 参数允许缺失：无参工具的 arguments 常常是 "" 或 "{}"。
        // 这里统一成 "{}"，让下游只需要处理一种情况。
        this.rawArguments = (rawArguments == null || rawArguments.trim().isEmpty())
                ? "{}"
                : rawArguments.trim();
    }

    public String getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public String getRawArguments() {
        return rawArguments;
    }

    @Override
    public String toString() {
        return "ToolCall{id=" + id + ", name=" + name + ", arguments=" + rawArguments + "}";
    }
}
