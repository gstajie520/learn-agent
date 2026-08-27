# 第 2 课：真实 HTTP 调用、超时与退避重试

## 为什么学习

第 1 课用 `FakeModelClient` 把业务规则测清楚了，但一次真实的网络请求都没发过。这一课换成真的调用模型服务。

**最值得注意的一点**：第 1 课写的 `SceneSummaryService` 这一课**一行都不用改**。它只依赖 `ModelClient` 接口，把注入的实现从 Fake 换成 HTTP 就直接对接了真实模型。这就是第 1 课那层接口的回报。

本课解决四类真实故障：

- 不设超时，服务端卡住时调用线程永久挂起，最终拖垢整个线程池；
- 读错了流，失败时拿不到服务端给的错误原因，只剩一个状态码；
- 服务端返回畸形 JSON，代码直接空指针，堆栈里看不出真正原因；
- 限流后立即重试，让本已过载的服务端更忙，偶发限流变成持续故障。

**本课暂时不解决**：Streaming、Tool Calling、结构化输出校验、连接池复用。这些在阶段 6 和阶段 11 展开。

## 三个配置项

和 `python/.env` 完全一致，这样同一份配置可以同时给 Python 和 Java 使用。写在 `learning/agent-java-learning/.env`，**后面所有 Java 模块共用这一份**：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-你的密钥
OPENAI_MODEL=deepseek-v4-flash
```

### Java 读不到 `.env`，这是个必须自己补的坑

Python 侧写完 `.env` 就能用，Java 侧写完却读不到。原因是 `System.getenv()` **只读操作系统的进程环境变量，根本不读文件**。Python 能直接用 `.env`，靠的是 `python-dotenv` 先把文件读出来塞进 `os.environ` —— Java 没有这一层。

所以本课加了 `EnvFile`，把这一层补上：

```java
Map<String, String> values = EnvFile.load();   // 从当前目录逐级向上找 .env
```

为什么要**逐级向上**找，而不是写死一个相对路径：Maven 多模块构建时，Surefire 的工作目录是**各子模块目录**，不是工程根目录。写死路径的话，在根目录跑 `mvn test` 读得到，在子模块里跑就读不到，表现为「同样的配置有时生效有时不生效」，极难排查。

读取入口是 `ModelSettings.fromEnvironmentOrDotEnv()`。它合并两个来源，**操作系统环境变量覆盖 `.env`**：

```java
ModelSettings settings = ModelSettings.fromEnvironmentOrDotEnv();
```

这个方向不能反，和 `python-dotenv` 的 `load_dotenv()` 默认行为一致。反了的后果不是报错，而是**静默用错配置**：线上容器靠环境变量注入生产密钥，如果镜像里不小心打进了一个开发用的 `.env`，反向优先级会让生产流量一直走开发密钥 —— 服务正常返回、日志毫无异常，只有账单和调用来源对不上。等发现时已经跑了很久，而且从代码里看不出问题，因为「读到了配置」这件事本身是成功的。

还有一个容易踩的细节：**值为空白的环境变量视为「没配」**，不允许它盖掉 `.env` 里的真实值。否则一个手滑设成空串的变量（`$env:OPENAI_API_KEY = ''` 想清除却没清干净、CI 里配了变量名但秘密注入失败）会让配置凭空消失，程序报「未配置」，而文件里明明写着。排查时几乎没人会想到去查一个空的环境变量。

这两条规则都由 `EnvFileTest` 钉住 —— 它们写反了不会报错，只会在某天悄悄用错密钥，所以必须有测试兜住，不能只写在注释里。

### 密钥绝不进代码库

**密钥只从 `.env` 或环境变量读取**，绝不硬编码、不写进日志、不提交 Git。`ModelSettings.toString()` 特意只打印密钥长度：

```text
ModelSettings{baseUrl=https://api.deepseek.com, model=deepseek-v4-flash, apiKeyLength=20}
```

日志经常直接打印配置对象，而日志通常还会被收集到第三方平台。密钥进了日志就等于泄露。

`.env` 已被 `learning/agent-java-learning/.gitignore` 忽略（`.env` 与 `**/.env` 两条规则），同时用 `!**/.env.example` 放行 `.env.example` —— 后者不含真实值，作用是记录「需要配哪几项」，方便换机器时照着填。

### base_url 是根地址，不是端点

`ModelSettings` 会拒绝以 `/chat/completions` 结尾的 base_url。这不是洁癖，是个真实的坑：不拦住的话会拼成 `.../chat/completions/chat/completions`，服务端返回 404，但错误信息看起来像"模型不存在"，排查方向会完全跑偏。

还有一个容易忽略的细节：拼接端点时只追加 `/chat/completions`，**不追加 `/v1`**。因为 OpenAI SDK 收到 `base_url=https://api.deepseek.com` 时，实际请求的就是 `https://api.deepseek.com/chat/completions`。如果 Java 这边多加一个 `/v1`，同一份 `.env` 在 Python 能跑通、在 Java 却 404。需要 `/v1` 的服务商应当把它写进 `OPENAI_BASE_URL` 本身。

### 配置错误要一次全报出来

```text
缺少或填写错误的必要配置：OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL
```

三个变量都没配时，逐个报错要改三次、重启三次。一次全报出来，改一遍就能起来。

配置错误还必须在**启动阶段**暴露，而不是等第一个用户请求进来才发现。这也是为什么单独定义 `ConfigurationException` 而不用 `IllegalArgumentException`——两者的处置方式完全不同。

## 一次调用真正发出去的 JSON

```json
{"model":"deepseek-v4-flash","temperature":0.2,"max_tokens":200,
 "messages":[{"role":"system","content":"你是场景描述助手。"},
             {"role":"user","content":"在北侧生成一台雷达。"}]}
```

所谓"调用大模型"，本质就是 POST 这样一段 JSON。

两个字段名容易写错：协议里是下划线的 `max_tokens`，不是 Java 的驼峰；角色是小写的 `system`/`user`，直接用 `enum.name()` 会发出 `SYSTEM`，服务端不认。这就是 `ChatRole.getWireValue()` 存在的原因。

## 两个必须显式设置的超时

```java
connection.setConnectTimeout(10000);  // 建立连接
connection.setReadTimeout(60000);     // 等待响应
```

**两者默认都是 0，也就是永不超时。** 这是本课最重要的生产要点。

不设置的话，服务端卡住时调用线程会一直挂着。如果这是个固定大小的线程池，几十个这样的请求就能把池占满，整个服务对外表现为完全无响应——而模型服务其实只是慢，并没有挂。所以 `HttpModelClient` 直接拒绝 0 值配置。

读超时要比普通接口大得多。模型响应通常是秒级，慢的时候几十秒，按 HTTP 接口的习惯设 3 秒会导致大量误判超时。

## 失败时响应体在 errorStream

```java
if (statusCode >= 200 && statusCode < 300) {
    String body = readAll(connection.getInputStream());
    return codec.parseResponse(body, requestId);
}
// 失败时在 errorStream，不在 inputStream
String errorBody = readAll(connection.getErrorStream());
throw codec.toException(statusCode, errorBody, requestId);
```

这是 `HttpURLConnection` 的一个坑：失败时读 `getInputStream()` 会抛 `IOException`，于是服务端返回的错误原因就丢了，只剩一个状态码。而错误原因往往正是解决问题的关键。

## 状态码到「能否重试」的映射

| HTTP | 分类 | 可重试 |
|---|---|:---:|
| 401 / 403 | `AUTHENTICATION` | 否 |
| 408 | `TIMEOUT` | 是 |
| 429 | `RATE_LIMIT` | 是 |
| 5xx | `SERVER_ERROR` | 是 |
| 400 | `INVALID_REQUEST` | 否 |
| 400 + `code=context_length_exceeded` | `CONTEXT_LENGTH_EXCEEDED` | 否 |

最后两行是重点：**同样是 400，处理方式完全不同**。上下文超长要压缩上下文后重发，参数写错要改代码。只看状态码会把这两种情况混为一谈。所以状态码是主依据，`error.code` 用来细分。

## 回来的 JSON 里，模型只写了一个字段

这是初学时最容易搞错的一件事：`readAll(connection.getInputStream())` 拿到的那一大段 JSON，**不是模型的输出**。它是服务端拼好的信封，模型的输出只是信封里的一张纸。

```json
{
  "id": "c6f70e7e-…",                        ← 服务端生成
  "object": "chat.completion",               ← 服务端写死
  "created": 1756...,                        ← 服务端取时间
  "model": "deepseek-v4-flash",              ← 服务端回显
  "choices": [{
    "index": 0,                              ← 服务端编号
    "message": {
      "role": "assistant",                   ← 服务端写死
      "content": "…",                        ← ★ 模型生成
      "reasoning_content": "…"               ← ★ 模型生成
    },
    "finish_reason": "length",               ← 服务端记录
    "logprobs": null                         ← 服务端
  }],
  "usage": { … },                            ← 服务端统计
  "system_fingerprint": "fp_…"               ← 服务端
}
```

带 ★ 的两个字段才是模型产出的，其余全部由服务端填写。**模型自己不会输出 JSON**，它只会一个个吐 token；把这些 token 装进信封是服务端的工作。

### `finish_reason` 是收据，不是模型的表达

搞清了上面这条，`finish_reason` 就不神秘了。服务端的生成循环大致是：

```
循环 {
    模型吐一个 token
    如果 token 是 EOS（结束符）      → 跳出，记 "stop"
    如果 已生成数量 == max_tokens    → 跳出，记 "length"
    如果 命中调用方传的 stop 字符串   → 跳出，记 "stop"
    如果 模型决定调工具              → 跳出，记 "tool_calls"
    如果 触发安全策略                → 跳出，记 "content_filter"
}
```

所以它记录的是**服务端从哪个分支跳出了循环**。你没有在请求里约束过任何东西，它照样会有值——因为这不是模型在回答你，是服务端在报告它自己干了什么。

顺带说清一个协议上的歧义：`stop` 既是 `finish_reason` 的取值，也是请求参数的名字，而且「模型自然说完」和「撞上你给的分隔符」都记成 `stop`，协议区分不了这两种情况。

### `max_tokens` 是在别人的机器上生效的

`max_tokens` 离开你的进程只有一个地方：

```java
// ChatJsonCodec.java:48
root.put("max_tokens", request.getMaxOutputTokens());
```

之后它就是 HTTP 请求体里的一个数字。**截断发生在服务端**，你的代码里永远看不到「截断」这个动作——就像 Redis 的 `setex`，没有任何本地代码去删那个 key。你手里只有两个动作：请求时提要求（`max_tokens`），响应时看收据（`finish_reason`）。

把 `max_tokens` 改成 10 跑一次，会得到这样的结果：

```json
"content": "",
"reasoning_content": "我们根据用户指令，给出中文场景描述即可",
"finish_reason": "length",
"completion_tokens": 10,
"completion_tokens_details": { "reasoning_tokens": 10 }
```

`content` 是空的，但模型并没有拒绝回答。**推理 token 算在 `completion_tokens` 里，而且先于正文生成**：10 个额度全花在思考上，一个字都没轮到正文。连那句思考本身都是被切断的——句末没有标点。

这条对写测试很关键。`shouldCallRealModelWhenConfigured` 早期用 `max_tokens=100` 却断言 `isUsable()`（要求 `STOP`），实际就是在断言「模型这次刚好没超 100 token」，偶发失败过一次。给推理留出余量、并接受 `STOP` 和 `LENGTH` 两种收据，测的才是传输与解析链路本身，而不是模型的话多话少。

## 从 11 个字段里挑 4 个

`ChatResponse` 只有 4 个字段，所以 `decodeResponse` 的工作就是挑走 4 样，其余全部丢掉：

| 原始 JSON | 代码 | 变成 |
|---|---|---|
| `message.content` | `optText(…, "content", "")` | `content` |
| `finish_reason` | `parseFinishReason(…)` | `FinishReason` |
| `usage` 的两个数 | `parseUsage(…)` | `TokenUsage` |
| `id`（缺失时退回 HTTP 头） | `optText(root, "id", headerRequestId)` | `requestId` |
| **`reasoning_content`** | 没读 | **丢弃** |
| `object` `created` `model` `system_fingerprint` `logprobs` `index` | 没读 | **丢弃** |

`reasoning_content` 这一行值得留意：上面那段推理内容只在**原始 JSON** 里看得到，它从未进入 `ChatResponse`。原始响应比领域对象丰富得多，`decodeResponse` 就是在这里划线——**只留业务要的，把供应商的协议细节挡在外面**。以后换供应商，改动只落在这个 codec 里，业务代码看到的还是同样 4 个字段。

## 响应是不可信边界

这是本课的核心立场，和 Python 版一致：服务端响应和 Controller 收到的外部请求性质一样，不能因为文档写了某个字段就假定它一定存在。网关故障、版本升级、限流页面都会破坏契约。

`ChatJsonCodec` 的防御策略：

| 情况 | 处理 | 为什么 |
|---|---|---|
| 缺少 `choices` | 抛 `SERVER_ERROR` | 不校验就直接空指针，堆栈里看不出真正原因 |
| 响应不是 JSON | 抛 `SERVER_ERROR`，带原文 | 通常说明被中间网关拦住了，原文是关键线索 |
| `content` 是 null | 转成空字符串 | 模型调工具时就没有正文，留 null 会让空指针传到业务层 |
| 未知 `finish_reason` | 归为 `UNKNOWN` | 服务商随时可能新增值；但绝不能当成 `STOP` |
| 缺少 `usage` | 记 0，不失败 | 拿不到用量是可观测性问题，不该让成功的调用变失败 |

注意"未知 `finish_reason`"这一条的权衡：抛异常会让服务商新增枚举值时整个调用挂掉，代价过大；当成 `STOP` 则会把异常结束误判成正常完成。归为 `UNKNOWN` 并判定不可用是两者之间的正解。

### 翻译和校验是两回事

上面那张表里混了两种性质完全不同的处理，值得单独拆开——它们恰好写在同一个方法里，对比很清楚。

**校验**是「检查合不合法，不合法就拒绝」：

```java
if (messageNode == null || !messageNode.isObject()) {
    throw new ModelException(SERVER_ERROR, "响应缺少 message 对象", …);
}
```

**翻译**是「换成本地类型，认不出来就兜底」，它从不拒绝任何东西：

```java
private static FinishReason parseFinishReason(String value) {
    if ("stop".equals(value)) { return FinishReason.STOP; }
    …
    return FinishReason.UNKNOWN;   // 永不抛异常
}
```

判断标准是**协议违约还是协议演进**。结构缺失说明对方根本没按契约回话，必须炸；结束原因不认识只说明对方比你新，要容忍。

这里还要澄清一个说法：JSON 协议里**没有枚举这种类型**，服务端发来的 `"length"` 就是个普通字符串。`FinishReason` 完全是本地的 Java 类型，DeepSeek 不知道它存在，只是我们刻意让取值对齐了协议里那几个字符串。想验证的话，把 `parseFinishReason` 里的 `"stop"` 改成 `"stop1"`：服务端的响应一个字节都不会变，但本地解析出来会全是 `UNKNOWN`——**对齐关系是我们自己维护的约定，不是协议强制的**。

真正的「这个响应能不能用」判断在更后面，`parseFinishReason` 不管：

```java
// ChatResponse.java:74
public boolean isUsable() {
    return finishReason == FinishReason.STOP && !content.trim().isEmpty();
}
```

`SceneSummaryService.extractSummary()` 再往前一步，对 `LENGTH` 直接抛 `INVALID_REQUEST`。**转换、可用性判断、业务决策分在三层**，各自只做一件事。

## 指数退避与抖动

`RetryingModelClient` 兑现了第 1 课说的"重试是横切逻辑，可以做成包装实现"：

```java
ModelClient client = new RetryingModelClient(
        new HttpModelClient(settings), 3, 500, 8000);
// SceneSummaryService 完全不知道自己被包了一层重试
```

实际退避序列（base=500ms，上限 8000ms）：

```text
第 1 次失败后等待约 431ms
第 2 次失败后等待约 841ms
第 3 次失败后等待约 1308ms
第 4 次失败后等待约 2554ms
第 5 次失败后等待约 6662ms
```

**为什么第 1 课的立即重试不够用**：限流意味着服务端已经处理不过来了，立刻重试只会让它更忙。

**为什么要抖动**：如果 100 个客户端在同一秒被限流，没有抖动的话它们会在同一时刻同时重试，形成新的请求尖峰，服务端再次限流，如此循环。这个现象叫「惊群」。抖动把重试时间打散来避免它。

两个容易漏掉的细节：

- **不可重试错误一次都不等**。对着必然失败的请求做退避，只是让用户白等几秒；
- **最后一次失败后不再等待**。反正不会再尝试了，再等纯属浪费。

## 为什么给「睡一会儿」定义接口

```java
public interface Sleeper {
    void sleep(long millis) throws InterruptedException;
}
```

退避重试的正确性体现在**等了多久**，不只是最终结果对不对。如果直接调 `Thread.sleep()`，测试验证退避序列就必须真的等好几秒。测试一慢就没人跑，没人跑的测试等于不存在。

注入 `Sleeper` 后，测试用的实现只记录时长、不真正睡眠，于是既能断言退避序列，又是毫秒级完成。这和第 1 课用 `FakeModelClient` 替换真实模型是同一个思路：**把不确定或慢的部分抽象成接口，测试注入可控实现**。

## 代码与测试

主代码：

- `ConfigurationException.java` — 配置错误，启动阶段就要暴露
- `ModelSettings.java` — 配置读取与校验，`toString()` 不泄露密钥
- `ChatJsonCodec.java` — JSON 编解码与错误映射（可完全离线测试）
- `HttpModelClient.java` — 真实 HTTP 实现，含两个超时
- `Sleeper.java` / `RetryingModelClient.java` — 指数退避与抖动
- `RealModelCallDemo.java` — 教学入口，无密钥也能跑完前五个场景

测试：

- `ModelSettingsTest.java`（11 个）— 配置校验、端点拼接、密钥不泄露
- `ChatJsonCodecTest.java`（18 个）— 序列化、响应解析、畸形响应、错误映射
- `RetryingModelClientTest.java`（9 个）— 退避序列、抖动、不重试边界
- `HttpModelClientTest.java`（6 个，3 个需密钥）— 超时校验、网络故障分类、真实调用

## 运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 05-llm-client -am test
```

不配密钥时，离线测试全部执行，3 个真实调用测试**明确跳过**。跳过不等于通过——这和阶段 4 真实 Redis 测试的策略一致。

运行教学入口：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
mvn -o -pl 05-llm-client -am package -DskipTests
java "-Dfile.encoding=UTF-8" -cp '05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.lesson02.RealModelCallDemo
```

前五个场景（配置校验、请求 JSON、响应解析、错误映射、退避序列）不需要密钥。只有第六个场景需要，未配置时会明确说明如何配置。

## 常见面试题

### 1. 为什么 HTTP 客户端必须显式设置超时？

**参考答案：**`HttpURLConnection` 的连接超时和读超时默认都是 0，含义是永不超时。不设置的话，服务端卡住时调用线程会一直挂着。如果调用发生在固定大小的线程池里，几十个这样的请求就能把线程池占满，整个服务对外表现为完全无响应，而下游其实只是慢、并没有挂。

**项目解决方案：**`HttpModelClient` 要求显式传入两个超时，并在构造时拒绝 0 值；默认连接 10 秒、读取 60 秒。读超时明显大于普通接口，因为模型响应本来就是秒级到几十秒。

**风险边界：**超时只保护调用方，不能减轻服务端负载。而且超时不代表服务端没执行——请求可能已经完成并计费，只是响应没按时回来。所以非幂等操作重试前需要配合请求去重。

### 2. 为什么限流后不能立即重试？

**参考答案：**限流意味着服务端已经处理不过来了，立即重试只会让它更忙。更严重的是，如果多个客户端同时被限流又同时立即重试，会形成同步的请求尖峰，服务端再次限流，把偶发问题变成持续故障，这叫惊群。

**项目解决方案：**`RetryingModelClient` 使用指数退避（500ms → 1s → 2s → 4s，封顶 8s），并对每次等待乘一个 `[0.5, 1.0)` 的随机系数做抖动，把多个客户端的重试时间打散。

**风险边界：**退避会拉长用户感知的响应时间，对延迟敏感的在线请求要限制重试次数，甚至配置 `maxAttempts=1` 直接失败。更彻底的方案是熔断和客户端限流，在明知会被拒绝时根本不发请求。

### 3. 为什么服务端响应要当成不可信数据校验？

**参考答案：**响应和 Controller 收到的外部请求性质相同。文档写了字段一定存在，不等于运行时真的存在——网关故障可能返回 HTML 错误页，版本升级可能新增枚举值，限流可能返回残缺结构。不校验就直接取字段，会得到一个空指针异常，而堆栈里完全看不出真正原因是"服务端返回不对"。

**项目解决方案：**`ChatJsonCodec` 对 `choices`、`message` 缺失显式抛 `SERVER_ERROR`；`content` 为 null 时转空字符串；未知 `finish_reason` 归为 `UNKNOWN` 而不是当成 `STOP`；缺 `usage` 时记 0 但不让调用失败。所有这些都能离线测试。

**风险边界：**结构校验只能保证字段存在和类型正确，不能保证内容正确。语义合法性需要阶段 6 的 Schema 校验加业务校验。另外把未知值归为 `UNKNOWN` 是权衡的结果，需要配合监控，否则服务商新增行为可能长期无人发现。

### 4. 换成真实 HTTP 客户端后，为什么业务代码不用改？

**参考答案：**因为业务代码从一开始就只依赖 `ModelClient` 接口，不依赖任何具体实现。第 1 课注入的是 `FakeModelClient`，这一课注入 `HttpModelClient`，中间还能再套一层 `RetryingModelClient`，业务类对这些完全不知情。这是依赖倒置的直接收益。

**项目解决方案：**`SceneSummaryService` 是第 1 课写的类，本课一行未改，只是构造时传入不同实现；`HttpModelClientTest.shouldWorkWithLesson01ServiceUnchanged` 专门验证了这一点。

**风险边界：**接口只能抽象共性。Streaming 是回调或流式返回，Tool Calling 有厂商特定的参数结构，这两类都无法塞进现在这个单方法接口，需要扩展而不是硬套。另外真实网络行为（连接池、TLS、DNS）无法被 Fake 覆盖，仍需要集成测试。

### 5. 为什么给「等待」也定义一个接口？

**参考答案：**因为退避重试的正确性在于等了多久，不只是最终结果。如果直接调 `Thread.sleep()`，要验证"第一次等 500ms、第二次等 1000ms"就得真的等一秒半，几个这样的测试能让整个套件慢到没人愿意跑。

**项目解决方案：**定义 `Sleeper` 接口，生产用 `Sleeper.REAL` 调 `Thread.sleep()`，测试注入只记录时长的 `RecordingSleeper`。于是 9 个退避测试全部在毫秒级完成，同时能断言退避序列、抖动范围和"不可重试错误一次都不等"。

**风险边界：**这只让等待逻辑可测，不能验证真实并发下的行为。多线程同时重试、线程池耗尽、中断传播这些需要专门的并发测试。另外要注意 `InterruptedException` 必须恢复中断标志，否则上层线程池无法正常关闭。

### 6. `finish_reason` 是谁写的？为什么它不能当成模型的输出？

**参考答案：**响应 JSON 是服务端拼的信封，模型只贡献 `content` 和 `reasoning_content` 两个字段——模型本身不输出 JSON，它只逐个吐 token。`finish_reason` 记录的是服务端的生成循环从哪个分支跳出：遇到 EOS 记 `stop`，达到 `max_tokens` 记 `length`，模型决定调工具记 `tool_calls`，触发安全策略记 `content_filter`。所以即使请求里什么约束都没给，它照样有值，因为这是服务端在报告自己的行为，不是模型在回答。

**项目解决方案：**`max_tokens` 离开进程只有 `ChatJsonCodec.java:48` 一处，截断动作完全发生在服务端，本地代码里看不到。调用方只有两个动作：请求时提要求，响应时读收据。`parseFinishReason` 把这个字符串翻译成本地的 `FinishReason`，可用性判断则留给 `ChatResponse.isUsable()`，业务决策再留给 `SceneSummaryService.extractSummary()`——三层各做一件事。

**风险边界：**`stop` 这个取值有歧义，「模型自然说完」和「命中调用方传的 stop 字符串」都记成 `stop`，协议区分不了。另外推理 token 计入 `completion_tokens` 且先于正文生成，`max_tokens` 太小会出现 `content` 为空但 `finish_reason=length` 的情况，看起来像模型拒答，实际是额度被思考用完了。据此写断言的测试会偶发失败。
