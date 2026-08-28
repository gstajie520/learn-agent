# 第 1 课：模型调用边界与 Fake 客户端

## 为什么学习

前四个阶段的输入都是确定的：HTTP 参数、Redis 值、线程池任务。模型调用是第一个**不确定**的依赖：同样的输入可能返回不同结果，可能超时，可能限流，可能话没说完就被截断。

如果直接在 Service 里 `new OpenAiClient()` 然后读 `response.content`，会出现四类线上问题：

- 没有密钥就无法写测试，业务逻辑只能靠手工点；
- 换模型厂商要改所有业务代码；
- 输出被 `maxOutputTokens` 截断，`content` 看起来是正常文本，实际是残句，下游解析 JSON 时才炸；
- 限流（429）和密钥错误（401）被同一个 `catch` 处理，前者该重试，后者重试一万次结果一样。

本课解决前面四条。**本课暂时不解决**：真实 HTTP 调用、Streaming、Tool Calling、结构化输出校验、退避等待。这些分别在第 2 课和阶段 6、11 展开。

## 核心设计：业务只依赖接口

```java
public interface ModelClient {
    ChatResponse chat(ChatRequest request) throws ModelException;
}
```

只有一个方法。模型调用的本质就是「发一组消息，拿一段回复」，不要在这一层设计出十几个方法。

业务类 `SceneSummaryService` 只依赖这个接口，不依赖任何 SDK。带来三个好处：

- **可测试**：测试注入 `FakeModelClient`，不要密钥、不花钱、不受网络影响，还能精确构造「前两次限流、第三次成功」这种真实环境很难复现的场景；
- **可替换**：换厂商只改实现类；
- **可加横切逻辑**：重试、限流、日志、Token 统计都能做成包装实现，不污染业务代码。

## 一次调用到底传了什么

```text
ChatRequest
  ├─ model            模型名，决定价格和上下文窗口
  ├─ messages         有序列表，模型按顺序理解对话历史
  ├─ temperature      0 尽量确定，越大越随机；要结构化输出就调低
  └─ maxOutputTokens  输出上限，控制成本，也是截断的来源
```

消息有四种角色，它们决定模型如何理解每段文本：

| 角色 | 含义 | 注意 |
|---|---|---|
| `SYSTEM` | 开发者设定的规则 | 绝不拼接用户输入，否则等于让用户改写系统规则 |
| `USER` | 终端用户输入 | 属于不可信数据 |
| `ASSISTANT` | 模型上一轮回复 | 用于保持多轮上下文 |
| `TOOL` | 工具执行结果 | 阶段 6 展开 |

模型 API 是**无状态**的：它不记得上一次请求。所谓"多轮对话"，是程序每次把完整消息列表重新发过去。这也意味着输入 Token 随对话轮次线性增长，长会话的成本不是恒定的。

## 返回结果里最容易被忽略的字段

```text
ChatResponse
  ├─ content        正文；被截断时这里是残句
  ├─ finishReason   模型为什么停止  ← 拿到响应第一件事是看它
  ├─ usage          Token 消耗，输入输出分开记
  └─ requestId      出问题时唯一能和模型服务方对上的凭证
```

`finishReason` 的四种值决定程序下一步做什么：

- `STOP`：自然说完，唯一可以放心使用 `content` 的情况；
- `LENGTH`：达到输出上限被截断，`content` 不完整；
- `TOOL_CALLS`：模型要调工具，`content` 通常为空；
- `CONTENT_FILTER`：被安全策略拦截，不要重试同样的输入。

所以业务代码的正确顺序是**先判断结束原因，再读 content**，而不是直接 `getContent()`。

## 哪些错误该重试

「这次失败该不该重试」是模型调用的关键区分。把判断放进异常本身，调用方就不用靠解析错误文本来猜：

| 错误分类 | 可重试 | 原因 |
|---|:---:|---|
| `RATE_LIMIT` | 是 | 等一会儿就好 |
| `SERVER_ERROR` | 是 | 服务端 5xx |
| `TIMEOUT` | 是 | 但上一次可能已在服务端执行并计费 |
| `INVALID_REQUEST` | 否 | 参数错了重试还是错 |
| `AUTHENTICATION` | 否 | 需要人工改配置 |
| `CONTEXT_LENGTH_EXCEEDED` | 否 | 必须先压缩上下文 |
| `CONTENT_FILTERED` | 否 | 重试无意义 |

## 代码与测试

主代码：

- `ChatRole.java` / `ChatMessage.java` — 消息角色和不可变消息
- `ChatRequest.java` — 请求契约，构造时校验并复制消息列表
- `ChatResponse.java` / `FinishReason.java` / `TokenUsage.java` — 响应契约
- `ModelClient.java` — 模型调用边界（本课最重要的一个文件）
- `ModelException.java` — 带可重试分类的异常
- `FakeModelClient.java` — 测试替身，按 FIFO 取出预设结果
- `SceneSummaryService.java` — 业务主角，演示生产调用必做的四件事
- `SceneSummaryDemo.java` — 可运行教学入口

测试：

- `SceneSummaryServiceTest.java` — 业务规则：截断拦截、重试边界、Token 累加
- `ChatRequestTest.java` — 请求契约：参数校验、不可变、日志不泄露正文
- `ChatResponseTest.java` — 响应契约与错误分类

## 运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 05-llm-client -am test
```

运行教学入口：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
mvn -o -pl 05-llm-client -am package -DskipTests
java -cp '05-llm-client/target/classes' learn.agent.llm.client.SceneSummaryDemo
```

第一行设置控制台 UTF-8。PowerShell 默认代码页是 GBK，不设置的话中文输出会显示成乱码 —— 这是控制台显示问题，不是程序错误。

`SceneSummaryDemo` 按业务顺序打印四个场景：正常调用、输出被截断、限流后重试成功、鉴权失败立即放弃。全程使用 `FakeModelClient`，不需要密钥也不需要网络。

## 常见面试题

### 1. 为什么业务代码不直接调用模型 SDK，而要加一层接口？

**参考答案：**模型调用有三个特性让它不适合被业务代码直接依赖 —— 需要密钥、需要网络、同样输入可能返回不同结果。加一层接口后，业务逻辑可以用 Fake 实现完整测试，换厂商只改实现类，重试和日志这些横切逻辑也能做成包装实现。

**项目解决方案：**`ModelClient` 只声明一个 `chat` 方法；`SceneSummaryService` 只依赖它；测试注入 `FakeModelClient` 预设「前两次限流、第三次成功」这类场景。

**风险边界：**接口只能抽象共性。不同厂商的 Tool Calling 参数格式、Streaming 协议和多模态输入差异较大，抽象过度会导致接口臃肿或丢失厂商特性；真实网络行为（连接池、超时、TLS）仍需要集成测试覆盖。

### 2. 拿到模型响应后，为什么不能直接读 content？

**参考答案：**要先看 `finishReason`。输出可能因为达到 `maxOutputTokens` 而被截断，此时 `content` 看起来是正常文本，实际是残句。直接拿去解析 JSON 或写库，会产生很难排查的脏数据。

**项目解决方案：**`ChatResponse.isUsable()` 只在 `STOP` 且内容非空时返回 true；`SceneSummaryService.extractSummary()` 显式区分 `LENGTH`、`CONTENT_FILTER` 和空内容三种情况，分别抛出带分类的异常。

**风险边界：**`finishReason` 只能说明输出是否完整，不能说明内容是否正确。语义正确性需要阶段 6 的 Schema 校验加业务校验，以及贯穿项里的评估集。

### 3. 哪些模型调用错误该重试，哪些不该？

**参考答案：**限流、服务端 5xx 和超时属于暂时性故障，等一会儿重试通常能成功。参数非法、密钥错误、上下文超长和内容被拦截属于确定性失败，原样重试结果一样，只是浪费时间和钱。

**项目解决方案：**`ModelException.ErrorType` 把 `retryable` 作为枚举自带属性，调用方直接问 `isRetryable()`，不需要解析错误文本；`SceneSummaryService` 遇到不可重试错误立即抛出，不消耗剩余重试次数。

**风险边界：**本课重试是立即重试，生产必须加指数退避和抖动，否则限流时的密集重试会让情况更糟。另外超时重试要注意上一次请求可能已在服务端执行并计费，非幂等操作需要配合请求去重。

### 4. 为什么 Token 要分输入和输出统计？

**参考答案：**输入和输出单价不同，输出通常更贵，只记总数无法准确核算成本。输入 Token 还会随对话历史线性增长，所以长会话的单次成本不是恒定的，这也是上下文压缩的动机。

**项目解决方案：**`TokenUsage` 分开保存 `promptTokens` 和 `completionTokens`；`SceneSummaryService` 在每次调用后累加，包括**失败的那次** —— 失败请求同样计费。

**风险边界：**Token 统计只反映成本，不反映业务价值。还需要按用户、会话和功能维度归集，才能定位是谁在烧钱；重试次数也要单独监控，否则会把重试放大的成本误读成正常用量。

### 5. 为什么不能把用户输入拼进 System 消息？

**参考答案：**`SYSTEM` 是开发者设定的规则，模型会优先遵守。把用户输入拼进去，等于允许用户改写系统规则，用户可以直接写「忽略上面的指令」来绕过业务约束。

**项目解决方案：**`SYSTEM_RULE` 是 `SceneSummaryService` 里的 `static final` 常量，用户输入始终作为独立的 `USER` 消息；`ChatRequestTest` 断言两条消息角色分离，没有拼成一段文本。

**风险边界：**角色分离能降低风险，但不能完全防止提示注入。模型仍可能被 `USER` 消息里的诱导语影响，所以真正的安全边界必须放在程序侧：阶段 6 的业务校验、阶段 8 的权限控制，以及「模型输出只生成预览、不直接执行危险操作」这条原则。
