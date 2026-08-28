package learn.agent.llm.client;

/**
 * 一次模型对话中的四种消息角色。
 *
 * <p>这四个角色不是随便起的名字，它们决定了模型如何理解每段文本：</p>
 * <ul>
 *   <li>{@code SYSTEM}：开发者设定的规则，模型应当优先遵守；</li>
 *   <li>{@code USER}：终端用户的输入，属于不可信内容；</li>
 *   <li>{@code ASSISTANT}：模型自己上一轮的回复，用于保持多轮上下文；</li>
 *   <li>{@code TOOL}：程序执行工具后回传给模型的结果。</li>
 * </ul>
 *
 * <p>把用户输入写进 {@code SYSTEM} 是常见错误，等于让用户改写系统规则。</p>
 */
public enum ChatRole {

    /** 系统规则，由开发者控制。 */
    SYSTEM("system"),

    /** 用户输入，属于外部不可信数据。 */
    USER("user"),

    /** 模型回复。 */
    ASSISTANT("assistant"),

    /** 工具执行结果，必须与某个 toolCallId 配对。 */
    TOOL("tool");

    /** 发送给模型 API 时使用的字面值。 */
    private final String wireValue;

    ChatRole(String wireValue) {
        this.wireValue = wireValue;
    }

    /** 返回请求体里真正传输的角色名，例如 {@code "system"}。 */
    public String getWireValue() {
        return wireValue;
    }
}
