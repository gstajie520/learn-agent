package learn.agent.llm.client;

import java.util.ArrayList;
import java.util.List;

/**
 * 场景描述总结服务：阶段 5 的业务主角。
 *
 * <p>它做的事很小 —— 把一段场景描述交给模型总结成一句话。
 * 但它演示了<b>任何</b>生产模型调用都必须做的四件事：</p>
 *
 * <ol>
 *   <li>把系统规则和用户输入分开放（不要拼进同一段文本）；</li>
 *   <li>拿到响应先检查 {@code finishReason}，不要直接读 content；</li>
 *   <li>只对可重试的错误重试，参数错和鉴权错立即失败；</li>
 *   <li>累加 Token，让成本可观测。</li>
 * </ol>
 *
 * <p>这个类<b>不</b>依赖任何具体模型厂商，只依赖 {@link ModelClient} 接口。
 * 所以它的全部行为都能用 {@link FakeModelClient} 测出来，不需要密钥。</p>
 */
public class SceneSummaryService {

    /** 系统规则由开发者固定，绝不拼接用户输入。 */
    private static final String SYSTEM_RULE =
            "你是场景描述助手。用一句中文总结用户提供的场景，不要提问，不要输出多余解释。";

    private final ModelClient modelClient;

    /** 使用的模型名。 */
    private final String model;

    /** 最大尝试次数（含第一次），用于限制重试。 */
    private final int maxAttempts;

    /** 累计输入 Token，跨多次调用统计。 */
    private int totalPromptTokens;

    /** 累计输出 Token。 */
    private int totalCompletionTokens;

    public SceneSummaryService(ModelClient modelClient, String model, int maxAttempts) {
        if (modelClient == null) {
            throw new IllegalArgumentException("modelClient 不能为空");
        }
        if (model == null || model.trim().isEmpty()) {
            throw new IllegalArgumentException("model 不能为空");
        }
        if (maxAttempts < 1) {
            throw new IllegalArgumentException("maxAttempts 至少为 1");
        }
        this.modelClient = modelClient;
        this.model = model;
        this.maxAttempts = maxAttempts;
    }

    /**
     * 总结一段场景描述。
     *
     * @param sceneDescription 用户输入的场景描述
     * @return 模型给出的一句话总结
     * @throws ModelException 重试用尽仍失败，或响应不可用
     */
    public String summarize(String sceneDescription) {
        if (sceneDescription == null || sceneDescription.trim().isEmpty()) {
            // 空输入不必发请求：省一次费用，也避免模型自由发挥。
            throw new IllegalArgumentException("场景描述不能为空");
        }

        ChatRequest request = buildRequest(sceneDescription);
        ModelException lastError = null;

        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                ChatResponse response = modelClient.chat(request);
                // 无论成功失败都要记 Token：失败的那次请求同样计费。
                recordUsage(response.getUsage());
                return extractSummary(response);
            } catch (ModelException e) {
                lastError = e;
                if (!e.isRetryable()) {
                    // 参数错误、鉴权失败、上下文超长：重试只是浪费时间和钱。
                    throw e;
                }
                // 可重试错误：继续下一次尝试。真实项目这里要加退避等待，见阶段 11。
            }
        }

        throw new ModelException(
                lastError.getErrorType(),
                "重试 " + maxAttempts + " 次后仍然失败：" + lastError.getMessage(),
                lastError.getRequestId(),
                lastError);
    }

    /** 组装请求：系统规则第一条，用户输入第二条。 */
    private ChatRequest buildRequest(String sceneDescription) {
        List<ChatMessage> messages = new ArrayList<ChatMessage>();
        messages.add(ChatMessage.system(SYSTEM_RULE));
        messages.add(ChatMessage.user(sceneDescription));
        // 总结任务要稳定，温度调到 0.2；一句话总结给 200 token 足够。
        return new ChatRequest(model, messages, 0.2, 200);
    }

    /**
     * 从响应中取出可用的总结。
     *
     * <p>这里是最容易被略过、也最容易在生产出事的一步。</p>
     */
    private String extractSummary(ChatResponse response) {
        if (response.getFinishReason() == FinishReason.LENGTH) {
            // 被截断的内容是残句，交给下游会产生难查的脏数据。
            throw new ModelException(
                    ModelException.ErrorType.INVALID_REQUEST,
                    "模型输出被截断，需要调大 maxOutputTokens 或缩短输入",
                    response.getRequestId(),
                    null);
        }
        if (response.getFinishReason() == FinishReason.CONTENT_FILTER) {
            throw new ModelException(
                    ModelException.ErrorType.CONTENT_FILTERED,
                    "输出被内容安全策略拦截",
                    response.getRequestId(),
                    null);
        }
        if (!response.isUsable()) {
            // 模型返回空字符串是真实存在的情况，必须显式处理而不是返回 null。
            throw new ModelException(
                    ModelException.ErrorType.SERVER_ERROR,
                    "模型返回空内容，finishReason=" + response.getFinishReason(),
                    response.getRequestId(),
                    null);
        }
        return response.getContent().trim();
    }

    /** 累加 Token 消耗。 */
    private void recordUsage(TokenUsage usage) {
        totalPromptTokens += usage.getPromptTokens();
        totalCompletionTokens += usage.getCompletionTokens();
    }

    public int getTotalPromptTokens() {
        return totalPromptTokens;
    }

    public int getTotalCompletionTokens() {
        return totalCompletionTokens;
    }

    /** 累计总 Token，用于对账和成本监控。 */
    public int getTotalTokens() {
        return totalPromptTokens + totalCompletionTokens;
    }
}
