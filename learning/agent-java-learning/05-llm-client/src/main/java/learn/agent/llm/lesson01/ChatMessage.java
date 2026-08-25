package learn.agent.llm.lesson01;

/**
 * 一条对话消息。
 *
 * <p>模型 API 是无状态的：它不记得上一次请求。所谓"多轮对话"，
 * 是程序每次把完整消息列表重新发过去。这个类就是列表里的一个元素。</p>
 *
 * <p>对象创建后不允许修改，避免请求组装到一半被别处改掉。</p>
 */
public class ChatMessage {

    /** 消息角色。 */
    private final ChatRole role;

    /** 消息正文。 */
    private final String content;

    public ChatMessage(ChatRole role, String content) {
        if (role == null) {
            throw new IllegalArgumentException("role 不能为空");
        }
        if (content == null) {
            throw new IllegalArgumentException("content 不能为 null");
        }
        this.role = role;
        this.content = content;
    }

    /** 创建系统规则消息，通常放在消息列表第一条。 */
    public static ChatMessage system(String content) {
        return new ChatMessage(ChatRole.SYSTEM, content);
    }

    /** 创建用户消息，内容来自终端用户，属于不可信数据。 */
    public static ChatMessage user(String content) {
        return new ChatMessage(ChatRole.USER, content);
    }

    /** 创建模型回复消息，用于把上一轮结果放回下一次请求。 */
    public static ChatMessage assistant(String content) {
        return new ChatMessage(ChatRole.ASSISTANT, content);
    }

    public ChatRole getRole() {
        return role;
    }

    public String getContent() {
        return content;
    }

    @Override
    public String toString() {
        return "[" + role.getWireValue() + "] " + content;
    }
}
