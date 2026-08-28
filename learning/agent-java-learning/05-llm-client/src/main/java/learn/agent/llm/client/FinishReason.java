package learn.agent.llm.client;

/**
 * 模型这一轮为什么停止输出。
 *
 * <p>这个字段常被忽略，但它决定了程序下一步该做什么。
 * 最容易出错的是 {@code LENGTH}：模型话没说完就被截断了，
 * 此时 {@code content} 看起来是正常文本，实际是残缺的。
 * 如果直接把它当完整结果解析 JSON，就会在生产环境拿到解析失败。</p>
 */
public enum FinishReason {

    /** 模型自然说完了，这是唯一可以放心使用 content 的情况。 */
    STOP,

    /**
     * 达到 maxOutputTokens 上限被截断。
     *
     * <p>content 不完整。要么调大上限重试，要么让模型分段输出。</p>
     */
    LENGTH,

    /** 模型决定调用工具，content 通常为空，真正的意图在 toolCalls 里（阶段 6 展开）。 */
    TOOL_CALLS,

    /** 被内容安全策略拦截，不应重试同样的输入。 */
    CONTENT_FILTER,

    /** 服务端返回了本地未识别的值，保留原样以便排查。 */
    UNKNOWN
}
