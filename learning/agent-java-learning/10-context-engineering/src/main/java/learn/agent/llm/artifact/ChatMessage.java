package learn.agent.llm.artifact;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 对话消息的基类。
 * 与 OpenAI Chat Completions API 对齐的最小会话消息模型。
 */
public abstract class ChatMessage {
    private final Role role;

    protected ChatMessage(Role role) {
        if (role == null) {
            throw new MessageContractException("role must not be null");
        }
        this.role = role;
    }

    public Role getRole() {
        return role;
    }

    /**
     * 系统消息：定义模型行为规则。
     */
    public static class SystemMessage extends ChatMessage {
        private final String content;

        public SystemMessage(String content) {
            super(Role.SYSTEM);
            if (content == null) {
                throw new MessageContractException("system content must not be null");
            }
            this.content = content;
        }

        public String getContent() {
            return content;
        }
    }

    /**
     * 用户消息：来自终端用户的输入。
     */
    public static class UserMessage extends ChatMessage {
        private final String content;

        public UserMessage(String content) {
            super(Role.USER);
            if (content == null) {
                throw new MessageContractException("user content must not be null");
            }
            this.content = content;
        }

        public String getContent() {
            return content;
        }
    }

    /**
     * 助手消息：模型的回复。
     * 可能包含文本回复、工具调用或两者都有。
     */
    public static class AssistantMessage extends ChatMessage {
        private final String content;  // 可以为 null
        private final List<ToolCall> toolCalls;

        public AssistantMessage(String content, List<ToolCall> toolCalls) {
            super(Role.ASSISTANT);
            if (toolCalls == null) {
                throw new MessageContractException("toolCalls must not be null (use empty list)");
            }
            // 检查 tool call ID 唯一性
            List<String> ids = new ArrayList<>();
            for (ToolCall call : toolCalls) {
                String id = call.getId();
                if (ids.contains(id)) {
                    throw new MessageContractException("assistant tool call ids must be unique");
                }
                ids.add(id);
            }
            this.content = content;
            this.toolCalls = Collections.unmodifiableList(new ArrayList<>(toolCalls));
        }

        /**
         * 文本回复，可能为 null（纯工具调用时）。
         */
        public String getContent() {
            return content;
        }

        /**
         * 工具调用列表，不可变。
         */
        public List<ToolCall> getToolCalls() {
            return toolCalls;
        }
    }

    /**
     * 工具消息：工具执行结果。
     * 必须对应前面 assistant 消息中的某个 tool call。
     */
    public static class ToolMessage extends ChatMessage {
        private final String content;
        private final String toolCallId;

        public ToolMessage(String content, String toolCallId) {
            super(Role.TOOL);
            if (content == null) {
                throw new MessageContractException("tool content must not be null");
            }
            if (toolCallId == null || toolCallId.isEmpty()) {
                throw new MessageContractException("tool_call_id must not be empty");
            }
            this.content = content;
            this.toolCallId = toolCallId;
        }

        public String getContent() {
            return content;
        }

        /**
         * 对应 assistant 消息中的 tool call ID。
         */
        public String getToolCallId() {
            return toolCallId;
        }
    }

    // 工厂方法

    public static SystemMessage system(String content) {
        return new SystemMessage(content);
    }

    public static UserMessage user(String content) {
        return new UserMessage(content);
    }

    public static AssistantMessage assistant(String content) {
        return new AssistantMessage(content, Collections.emptyList());
    }

    public static AssistantMessage assistant(String content, List<ToolCall> toolCalls) {
        return new AssistantMessage(content, toolCalls);
    }

    public static ToolMessage tool(String content, String toolCallId) {
        return new ToolMessage(content, toolCallId);
    }
}
