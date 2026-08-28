package learn.agent.llm.client;

/**
 * 一次模型请求的返回结果。
 *
 * <p>真实 API 返回的 JSON 比这里复杂，但后端业务真正需要的就是这四项：
 * 正文、结束原因、Token 消耗和请求 id。</p>
 *
 * <p>特别注意 {@link #finishReason}：很多线上问题不是模型"答错了"，
 * 而是输出被 {@code maxOutputTokens} 截断，程序却当成完整结果继续解析。
 * 所以拿到响应后第一件事是检查结束原因，而不是直接读 content。</p>
 */
public class ChatResponse {

    /** 模型输出的正文；被截断时这里是不完整的内容。 */
    private final String content;

    /** 模型为什么停止输出。 */
    private final FinishReason finishReason;

    /** 本次请求的 Token 消耗。 */
    private final TokenUsage usage;

    /**
     * 服务端请求 id。
     *
     * <p>排查问题时要把它写进日志：出现异常输出时，
     * 这是唯一能和模型服务方对上的凭证。</p>
     */
    private final String requestId;

    public ChatResponse(String content,
                        FinishReason finishReason,
                        TokenUsage usage,
                        String requestId) {
        if (content == null) {
            throw new IllegalArgumentException("content 不能为 null；模型没有输出时应传空字符串");
        }
        if (finishReason == null) {
            throw new IllegalArgumentException("finishReason 不能为空");
        }
        if (usage == null) {
            throw new IllegalArgumentException("usage 不能为空；无法统计成本的响应不应进入业务层");
        }
        this.content = content;
        this.finishReason = finishReason;
        this.usage = usage;
        // requestId 允许为空：部分兼容网关不返回这个头，此时统一记为 unknown。
        this.requestId = (requestId == null || requestId.trim().isEmpty()) ? "unknown" : requestId;
    }

    public String getContent() {
        return content;
    }

    public FinishReason getFinishReason() {
        return finishReason;
    }

    public TokenUsage getUsage() {
        return usage;
    }

    public String getRequestId() {
        return requestId;
    }

    /**
     * 判断这个响应能否交给下游业务使用。
     *
     * <p>只有正常结束才算可用。截断、内容过滤和其他异常结束都必须先处理，
     * 不能直接把 content 拿去做 JSON 解析或写库。</p>
     */
    public boolean isUsable() {
        return finishReason == FinishReason.STOP && !content.trim().isEmpty();
    }

    @Override
    public String toString() {
        return "ChatResponse{finishReason=" + finishReason
                + ", contentLength=" + content.length()
                + ", " + usage
                + ", requestId=" + requestId
                + "}";
    }
}
