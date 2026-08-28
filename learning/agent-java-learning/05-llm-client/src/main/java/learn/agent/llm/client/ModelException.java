package learn.agent.llm.client;

/**
 * 模型调用失败时抛出的异常。
 *
 * <p>为什么不用一个笼统的 {@code RuntimeException}：调用模型有一类关键区分 ——
 * <b>这次失败该不该重试</b>。参数写错了重试一万次还是错，
 * 限流和服务不可用则等一会儿就能成功。把这个判断放进异常本身，
 * 调用方就不需要靠解析错误文本来猜。</p>
 */
public class ModelException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    /** 失败分类。 */
    private final ErrorType errorType;

    /** 服务端请求 id，可能为 null。 */
    private final String requestId;

    public ModelException(ErrorType errorType, String message, String requestId, Throwable cause) {
        super(message, cause);
        if (errorType == null) {
            throw new IllegalArgumentException("errorType 不能为空");
        }
        this.errorType = errorType;
        this.requestId = requestId;
    }

    public ModelException(ErrorType errorType, String message) {
        this(errorType, message, null, null);
    }

    public ErrorType getErrorType() {
        return errorType;
    }

    public String getRequestId() {
        return requestId;
    }

    /** 是否值得重试；由错误分类决定，调用方不需要自己判断。 */
    public boolean isRetryable() {
        return errorType.isRetryable();
    }

    /**
     * 模型调用的失败分类。
     *
     * <p>这套分类是后续阶段 11「API 韧性」的基础。现在只需要记住
     * 哪几类能重试、哪几类必须直接失败。</p>
     */
    public enum ErrorType {

        /** 请求参数非法，例如温度越界、消息为空。重试无意义。 */
        INVALID_REQUEST(false),

        /** 密钥错误或过期。重试无意义，需要人工修配置。 */
        AUTHENTICATION(false),

        /** 触发限流（HTTP 429）。等待后重试通常会成功。 */
        RATE_LIMIT(true),

        /** 模型服务端错误（HTTP 5xx）。可以重试。 */
        SERVER_ERROR(true),

        /** 请求超时。可以重试，但要注意上一次可能已经在服务端执行并计费。 */
        TIMEOUT(true),

        /** 输入超过上下文窗口。必须先压缩上下文，原样重试仍会失败。 */
        CONTEXT_LENGTH_EXCEEDED(false),

        /** 内容被安全策略拦截。重试无意义。 */
        CONTENT_FILTERED(false);

        private final boolean retryable;

        ErrorType(boolean retryable) {
            this.retryable = retryable;
        }

        public boolean isRetryable() {
            return retryable;
        }
    }
}
