package learn.agent.llm.client;

import java.util.ArrayList;
import java.util.LinkedList;
import java.util.List;
import java.util.Queue;

/**
 * 测试专用的假模型客户端。
 *
 * <p>为什么必须有这个类：真实模型有三个特性让它无法用于单元测试 ——
 * 需要密钥、需要网络、同样的输入可能返回不同结果。
 * 但我们要测的其实是<b>自己的业务代码</b>：截断了会不会被发现、
 * 限流了会不会重试、Token 有没有累加。这些都不需要真实模型。</p>
 *
 * <p>用法是预先排好这次要返回什么，然后让业务代码去调用：</p>
 *
 * <pre>{@code
 * FakeModelClient fake = new FakeModelClient();
 * fake.enqueueResponse("北侧新增一台雷达");          // 第一次调用返回这个
 * fake.enqueueError(ErrorType.RATE_LIMIT, "429");  // 第二次调用抛这个
 * }</pre>
 *
 * <p>这种"按顺序取出预设结果"的做法，能精确构造出真实环境里
 * 很难复现的场景，例如"前两次限流、第三次成功"。</p>
 */
public class FakeModelClient implements ModelClient {

    /** 预设结果队列，按 FIFO 顺序取出。 */
    private final Queue<Object> scriptedResults = new LinkedList<Object>();

    /** 记录每一次实际收到的请求，供测试断言"到底发了什么"。 */
    private final List<ChatRequest> receivedRequests = new ArrayList<ChatRequest>();

    /** 队列耗尽后返回的兜底内容。 */
    private String defaultContent = "fake-response";

    /** 预设一次成功响应，只关心正文时使用。 */
    public FakeModelClient enqueueResponse(String content) {
        return enqueueResponse(content, FinishReason.STOP, new TokenUsage(10, 5));
    }

    /** 预设一次成功响应，可指定结束原因和 Token，用于构造截断等场景。 */
    public FakeModelClient enqueueResponse(String content, FinishReason finishReason, TokenUsage usage) {
        scriptedResults.add(new ChatResponse(content, finishReason, usage, "fake-req-" + (scriptedResults.size() + 1)));
        return this;
    }

    /** 预设一次失败，用于测试重试和错误分类分支。 */
    public FakeModelClient enqueueError(ModelException.ErrorType errorType, String message) {
        scriptedResults.add(new ModelException(errorType, message));
        return this;
    }

    /** 设置队列耗尽后的兜底正文。 */
    public FakeModelClient withDefaultContent(String content) {
        this.defaultContent = content;
        return this;
    }

    @Override
    public ChatResponse chat(ChatRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("request 不能为空");
        }
        // 先记录请求，即使这次注定要抛异常也要记，测试才能验证请求内容。
        receivedRequests.add(request);

        Object next = scriptedResults.poll();
        if (next == null) {
            // 队列空了不报错，返回兜底响应：多数测试只关心前几次调用。
            return new ChatResponse(defaultContent, FinishReason.STOP, new TokenUsage(1, 1), "fake-default");
        }
        if (next instanceof ModelException) {
            throw (ModelException) next;
        }
        return (ChatResponse) next;
    }

    /** 被调用了几次；验证重试次数和缓存是否生效时使用。 */
    public int getCallCount() {
        return receivedRequests.size();
    }

    /** 取出第 n 次请求（从 0 开始），用于断言实际发送的消息列表。 */
    public ChatRequest getRequest(int index) {
        if (index < 0 || index >= receivedRequests.size()) {
            throw new IndexOutOfBoundsException(
                    "只收到 " + receivedRequests.size() + " 次请求，无法取第 " + index + " 次");
        }
        return receivedRequests.get(index);
    }

    /** 取出最后一次请求，这是最常用的断言入口。 */
    public ChatRequest getLastRequest() {
        if (receivedRequests.isEmpty()) {
            throw new IllegalStateException("还没有收到任何请求");
        }
        return receivedRequests.get(receivedRequests.size() - 1);
    }
}
