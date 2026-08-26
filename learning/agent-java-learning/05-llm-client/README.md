# LLM 调用基础学习目录

阶段 5。第一次引入**不确定的依赖**：模型可能超时、限流、返回空内容，或者话没说完就被截断。本阶段的目标不是学会某个 SDK，而是搞清楚「一次模型调用到底传了什么、返回了什么、哪里会出错」。

和阶段 4 一样：每课有独立文档、Java 子包和测试子包。学习时只打开当前课。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | 模型调用边界、消息角色、Token、错误分类、Fake 客户端 | [01-model-client.md](lessons/01-model-client.md) | `learn.agent.llm.lesson01` | `learn.agent.llm.lesson01` |
| 2 | 真实 HTTP 调用、配置校验、超时、指数退避与抖动 | [02-real-http-call.md](lessons/02-real-http-call.md) | `learn.agent.llm.lesson02` | `learn.agent.llm.lesson02` |
| 3 | Structured Output：JSON 提取、两层校验、预览而非执行 | [03-structured-output.md](lessons/03-structured-output.md) | `learn.agent.llm.lesson03` | `learn.agent.llm.lesson03` |

后续课次（尚未生成）：Tool Calling、Streaming 流式输出、连接池复用。

三课之间的关系是本阶段的主线：

- 第 1 课用 Fake 客户端把业务规则测清楚；
- 第 2 课换成真实 HTTP，而**业务代码一行都没改** —— 这是第 1 课那层 `ModelClient` 接口的回报；
- 第 3 课让模型输出**结构化数据而不是文本**，程序因此可以直接执行它 —— 但必须先过两层校验。

第 3 课是从「聊天机器人」转向「Agent 应用」的分界线。前两课的模型输出是给人看的文本，
第 3 课开始，模型输出的是给**程序**执行的数据，所以校验从"可选"变成"必须"。

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 05-llm-client -am test
```

本阶段第 1 课和第 3 课**全部测试都不需要密钥和网络**，使用 `FakeModelClient` 注入预设结果。这是刻意的设计：如果测试必须有真实密钥才能跑，业务逻辑就只能靠手工点。

第 3 课尤其明显 —— 校验规则是纯逻辑，用 Fake 客户端可以精确构造「模型输出了不存在的设备 id」这类场景，
而这在真实模型上很难稳定复现。

第 2 课的配置校验、JSON 解析和退避重试同样离线可测；只有 3 个真实调用测试需要配置，未配置时**明确跳过**：

```powershell
$env:OPENAI_BASE_URL = 'https://api.deepseek.com'
$env:OPENAI_API_KEY  = '你的密钥'
$env:OPENAI_MODEL    = 'deepseek-v4-flash'
```

环境变量名和 `python/ch01_agent` 一致，同一份配置两边通用。**密钥只从环境变量读取**，不要写进代码或创建 `.env` 文件提交。

控制台运行 `main()` 前先设置 UTF-8，否则 PowerShell 默认 GBK 代码页会把中文输出显示成乱码：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 本课代码怎么找

```text
lessons/01-model-client.md
src/main/java/learn/agent/llm/lesson01/
src/test/java/learn/agent/llm/lesson01/
```

先读文档的「为什么学习」和核心设计，再打开 `SceneSummaryDemo` 看业务执行顺序，最后看测试在证明哪条规则。

## 和前四个阶段的关系

- 阶段 2 线程池：模型调用是秒级甚至几十秒的慢操作，绝不能在 Web 请求线程里同步执行；
- 阶段 3 Spring Boot：Controller 收到请求后应立即返回 commandId，而不是等模型；
- 阶段 4 Redis：模型任务的状态、幂等 claim 和结果缓存都落在 Redis；
- 阶段 14 会把这三条串起来，把模型调用移到 MQ 消费者里执行。

## 边界说明

- `ModelClient` 是业务与模型厂商之间的唯一接缝，业务代码不允许出现任何 SDK 类型；
- `finishReason` 决定响应能否使用，`content` 不是第一个该读的字段；
- 「能否重试」由错误分类决定，不靠解析错误文本猜；
- **结构正确不代表业务合法** —— 第 3 课正式处理这一条，它是从「聊天机器人」转向「Agent 应用」的分界；
- 模型输出只生成**预览**，不直接修改数据。真正执行需要用户确认，属于下一阶段。

## 第 3 课的四层链路

```text
自然语言指令
  ↓ 调模型（temperature=0）
  ↓ 解析      OperationJsonParser        JSON 合法吗、字段类型对吗
  ↓ 结构校验  OperationSchemaValidator   字段搭配对吗（纯函数，不查状态）
  ↓ 业务校验  SceneBusinessValidator     真实场景下能做吗（依赖场景快照）
预览（尚未执行）
```

分层的判断标准只有一条：**这条规则需要查运行时状态吗**。不需要的放 Schema 层，需要的放业务层。
