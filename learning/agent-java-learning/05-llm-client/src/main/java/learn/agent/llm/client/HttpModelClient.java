package learn.agent.llm.client;


import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.Charset;

/**
 * {@link ModelClient} 的真实 HTTP 实现。
 *
 * <p>第 1 课用 {@code FakeModelClient} 把业务逻辑测清楚了，这一课换成真的发网络请求。
 * 关键在于：<b>业务代码一行都不用改</b>。{@code SceneSummaryService} 只依赖
 * {@code ModelClient} 接口，把 Fake 换成这个类就直接对接了真实模型 ——
 * 这就是第 1 课那层接口的回报。</p>
 *
 * <p>使用 {@link HttpURLConnection} 而不是 Java 11 的 {@code HttpClient}，
 * 因为本模块编译目标是 Java 8。它写起来啰嗦，但能看清 HTTP 调用的每一步：
 * 设超时、写请求体、读状态码、按状态码分流。</p>
 *
 * <p><b>两个必须显式设置的超时</b>，这是本课最容易被忽略的生产要点：</p>
 * <ul>
 *   <li>{@code connectTimeout}：建立 TCP 连接的上限；</li>
 *   <li>{@code readTimeout}：等待响应数据的上限。</li>
 * </ul>
 *
 * <p>两者默认都是 0，也就是<b>永不超时</b>。不设置的话，服务端卡住时调用线程
 * 会一直挂着；如果这是个固定大小的线程池，几十个这样的请求就能把池占满，
 * 整个服务对外表现为完全无响应 —— 而模型服务其实只是慢，并没有挂。</p>
 */
public class HttpModelClient implements ModelClient {

    private static final Charset UTF8 = Charset.forName("UTF-8");

    private final ModelSettings settings;

    private final ChatJsonCodec codec;

    /** 建立连接的超时时间，毫秒。 */
    private final int connectTimeoutMillis;

    /** 等待响应的超时时间，毫秒。模型是慢操作，这个值要比普通接口大得多。 */
    private final int readTimeoutMillis;

    /** 使用默认超时：连接 10 秒，读取 60 秒。 */
    public HttpModelClient(ModelSettings settings) {
        this(settings, 10000, 60000);
    }

    public HttpModelClient(ModelSettings settings, int connectTimeoutMillis, int readTimeoutMillis) {
        if (settings == null) {
            throw new IllegalArgumentException("settings 不能为空");
        }
        if (connectTimeoutMillis <= 0 || readTimeoutMillis <= 0) {
            // 0 在 HttpURLConnection 里表示永不超时，必须显式拒绝这个配置。
            throw new IllegalArgumentException("超时时间必须大于 0，0 表示永不超时，不允许使用");
        }
        this.settings = settings;
        this.codec = new ChatJsonCodec();
        this.connectTimeoutMillis = connectTimeoutMillis;
        this.readTimeoutMillis = readTimeoutMillis;
    }

    @Override
    public ChatResponse chat(ChatRequest request) throws ModelException {
        if (request == null) {
            throw new IllegalArgumentException("request 不能为空");
        }

        String payload = codec.toRequestJson(request);
        HttpURLConnection connection = null;
        try {
            connection = openConnection();
            writeRequestBody(connection, payload);

            // getResponseCode() 会真正触发请求发送并等待响应。
            int statusCode = connection.getResponseCode();
            // 服务商通常用这个头返回请求 id，出问题时是唯一能和对方对上的凭证。
            String requestId = connection.getHeaderField("x-request-id");

            if (statusCode >= 200 && statusCode < 300) {
                String body = readAll(connection.getInputStream());
                return codec.parseResponse(body, requestId);
            }

            // 失败时响应体在 errorStream，不在 inputStream。
            // 读错了流就会丢掉服务端给的错误原因，只剩一个状态码，排查会非常痛苦。
            String errorBody = readAll(connection.getErrorStream());
            throw codec.toException(statusCode, errorBody, requestId);

        } catch (SocketTimeoutException e) {
            // 单独捕获超时并归类为可重试。注意：超时不代表服务端没执行，
            // 请求可能已经完成并计费，只是响应没能按时回来。
            throw new ModelException(
                    ModelException.ErrorType.TIMEOUT,
                    "模型调用超时（连接 " + connectTimeoutMillis + "ms / 读取 " + readTimeoutMillis + "ms）",
                    null,
                    e);
        } catch (IOException e) {
            // DNS 解析失败、连接被拒、TLS 握手失败等都落在这里，属于暂时性故障。
            throw new ModelException(
                    ModelException.ErrorType.SERVER_ERROR,
                    "模型调用网络异常：" + e.getMessage(),
                    null,
                    e);
        } finally {
            if (connection != null) {
                // 必须断开，否则连接可能被一直占用。
                connection.disconnect();
            }
        }
    }

    /** 创建并配置连接，包括鉴权头和两个超时。 */
    private HttpURLConnection openConnection() throws IOException {
        URL url = new URL(settings.getChatCompletionsUrl());
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        // 密钥放在 Authorization 头，绝不能拼进 URL query ——
        // URL 会出现在访问日志、代理日志和浏览器历史里，等于泄露密钥。
        connection.setRequestProperty("Authorization", "Bearer " + settings.getApiKey());
        connection.setConnectTimeout(connectTimeoutMillis);
        connection.setReadTimeout(readTimeoutMillis);
        // 允许写请求体；POST 必须打开。
        connection.setDoOutput(true);
        return connection;
    }

    /** 写入 JSON 请求体，显式使用 UTF-8。 */
    private void writeRequestBody(HttpURLConnection connection, String payload) throws IOException {
        OutputStream out = connection.getOutputStream();
        try {
            // 显式指定 UTF-8。依赖平台默认编码时，中文提示词在
            // Windows（GBK）和 Linux（UTF-8）上会发出不同字节，是典型的"本地能跑线上乱码"。
            out.write(payload.getBytes(UTF8));
            out.flush();
        } finally {
            out.close();
        }
    }

    /** 读完整个流并转成字符串；流为 null 时返回空串。 */
    private String readAll(InputStream in) throws IOException {
        if (in == null) {
            return "";
        }
        try {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            byte[] chunk = new byte[4096];
            int read;
            while ((read = in.read(chunk)) != -1) {
                buffer.write(chunk, 0, read);
            }
            return new String(buffer.toByteArray(), UTF8);
        } finally {
            in.close();
        }
    }
}
