package learn.agent.llm.client;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 一次模型请求要传的全部内容。
 *
 * <p>这个类的目的是让你看清「一次模型调用到底发了什么」。
 * 真实 HTTP 请求体里就是这几项：模型名、消息列表、温度、最大输出 token。</p>
 *
 * <p>请求对象创建后不可修改：消息列表在构造时复制一份并包装成只读视图。
 * 这样做的原因是请求会被重试、被日志记录、可能被多个线程读取，
 * 如果调用方后续还能改动列表，日志里记的就不是真正发出去的内容。</p>
 */
public class ChatRequest {

    /** 模型名称，例如 {@code "gpt-4o-mini"}；不同模型的价格和上下文窗口不同。 */
    private final String model;

    /** 消息列表，顺序有意义：模型按顺序理解对话历史。 */
    private final List<ChatMessage> messages;

    /**
     * 采样温度。0 表示尽量确定，越大越随机。
     *
     * <p>需要结构化输出时应当调低，闲聊类场景才需要较高温度。</p>
     */
    private final double temperature;

    /** 允许模型输出的最大 token 数，用于控制成本和防止无限输出。 */
    private final int maxOutputTokens;

    public ChatRequest(String model,
                       List<ChatMessage> messages,
                       double temperature,
                       int maxOutputTokens) {
        if (model == null || model.trim().isEmpty()) {
            throw new IllegalArgumentException("model 不能为空");
        }
        if (messages == null || messages.isEmpty()) {
            throw new IllegalArgumentException("messages 不能为空，至少要有一条用户消息");
        }
        // 温度超出 [0, 2] 的请求会被服务端拒绝，在本地先挡掉，省一次网络往返。
        if (temperature < 0.0 || temperature > 2.0) {
            throw new IllegalArgumentException("temperature 必须在 0 到 2 之间，当前值：" + temperature);
        }
        if (maxOutputTokens <= 0) {
            throw new IllegalArgumentException("maxOutputTokens 必须大于 0");
        }
        this.model = model;
        // 先复制再包装：防止调用方持有的原列表被修改后影响已创建的请求。
        this.messages = Collections.unmodifiableList(new ArrayList<ChatMessage>(messages));
        this.temperature = temperature;
        this.maxOutputTokens = maxOutputTokens;
    }

    public String getModel() {
        return model;
    }

    /** 返回只读消息列表；尝试修改会抛 {@link UnsupportedOperationException}。 */
    public List<ChatMessage> getMessages() {
        return messages;
    }

    public double getTemperature() {
        return temperature;
    }

    public int getMaxOutputTokens() {
        return maxOutputTokens;
    }

    @Override
    public String toString() {
        // 只打印结构信息，不打印消息正文：正文可能很长，也可能含用户敏感数据。
        return "ChatRequest{model=" + model
                + ", messageCount=" + messages.size()
                + ", temperature=" + temperature
                + ", maxOutputTokens=" + maxOutputTokens
                + "}";
    }
}
