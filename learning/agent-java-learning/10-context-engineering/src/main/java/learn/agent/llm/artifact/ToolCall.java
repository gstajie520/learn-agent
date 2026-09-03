package learn.agent.llm.artifact;

/**
 * 工具调用：模型请求执行某个工具。
 * 参数保留 JSON 字符串，具体解析和 schema 校验属于工具注册表。
 */
public final class ToolCall {
    private final String id;
    private final String name;
    private final String arguments;

    public ToolCall(String id, String name, String arguments) {
        if (id == null || id.isEmpty()) {
            throw new MessageContractException("tool call id must not be empty");
        }
        if (name == null || name.isEmpty()) {
            throw new MessageContractException("tool call name must not be empty");
        }
        if (arguments == null) {
            throw new MessageContractException("tool call arguments must not be null");
        }
        this.id = id;
        this.name = name;
        this.arguments = arguments;
    }

    /**
     * 工具调用 ID，模型生成，后续 tool 消息用它配对。
     */
    public String getId() {
        return id;
    }

    /**
     * 工具名称，必须在注册表中。
     */
    public String getName() {
        return name;
    }

    /**
     * 工具参数的 JSON 字符串表示。
     */
    public String getArguments() {
        return arguments;
    }
}
