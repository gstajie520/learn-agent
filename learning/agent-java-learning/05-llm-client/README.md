# LLM 调用基础学习目录

阶段 5。第一次引入**不确定的依赖**：模型可能超时、限流、返回空内容，或者话没说完就被截断。本阶段的目标不是学会某个 SDK，而是搞清楚「一次模型调用到底传了什么、返回了什么、哪里会出错」。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | 模型调用边界、消息角色、Token、错误分类、Fake 客户端 | [01-model-client.md](lessons/01-model-client.md) | `learn.agent.llm.client` | `learn.agent.llm.client` |
| 2 | 真实 HTTP 调用、配置校验、超时、指数退避与抖动 | [02-real-http-call.md](lessons/02-real-http-call.md) | `learn.agent.llm.client` | `learn.agent.llm.client` |

两课共用一个 `learn.agent.llm.client` 包，因为第 2 课是**第 1 课接口的第二个实现**，不是新主题：

- 第 1 课用 `FakeModelClient` 把业务规则测清楚；
- 第 2 课换成真实 HTTP，而**业务代码一行都没改** —— 这就是第 1 课那层 `ModelClient` 接口的回报。

后续课次（尚未生成，均不阻塞后续阶段）：Streaming 流式输出、连接池复用。

## 下游模块

本模块是全部 LLM 相关阶段的地基，`ChatMessage`、`ModelClient`、`TokenUsage`、`FakeModelClient` 都由这里定义：

| 模块 | 阶段 | 主题 |
|---|---|---|
| [06-structured-output](../06-structured-output/README.md) | 6 前半 | 模型输出结构化数据，两层校验 |
| [07-tool-calling](../07-tool-calling/README.md) | 6 后半 | 模型主动选工具 |
| [08-agent-loop](../08-agent-loop/README.md) | 7 | 多轮循环与四道工具边界 |
| [09-agent-guardrails](../09-agent-guardrails/README.md) | 8 | 权限裁决与 Hook 生命周期 |

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 05-llm-client test
```

80 个测试。除第 2 课的 3 个真实调用测试外，**全部测试都不需要密钥和网络**，使用 `FakeModelClient` 注入预设结果。这是刻意的设计：如果测试必须有真实密钥才能跑，业务逻辑就只能靠手工点。

第 2 课的配置校验、JSON 解析和退避重试同样离线可测；只有 3 个真实调用测试需要配置，未配置时**明确跳过**。

## 配置（后面所有 Java 模块共用这一份）

配置写在 `learning/agent-java-learning/.env`：

```dotenv
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-你的密钥
OPENAI_MODEL=deepseek-v4-flash
```

模板见 `learning/agent-java-learning/.env.example`（`Copy-Item .env.example .env` 后填真实值）。

变量名和 `python/.env` 完全一致，同一份配置两边通用。注意一个 Java 特有的坑：**`System.getenv()` 只读进程环境变量，不读 `.env` 文件** —— Python 能直接用 `.env` 是因为 `python-dotenv` 帮它读了文件。所以 Java 侧要自己补一个加载器，就是 `EnvFile`；读取入口是 `ModelSettings.fromEnvironmentOrDotEnv()`。它从当前目录逐级向上找 `.env`，所以在工程根目录和在子模块目录里跑都能找到同一份。

优先级是**操作系统环境变量覆盖 `.env`**，和 `python-dotenv` 的 `load_dotenv()` 默认行为一致。所以想临时换个模型跑一次，不用改文件：

```powershell
$env:OPENAI_MODEL = 'deepseek-v4-flash'
```

**密钥只从 `.env` 或环境变量读取**，绝不写进代码、日志或提交 Git。`.env` 已被 `learning/agent-java-learning/.gitignore` 忽略（`.env` 与 `**/.env` 两条规则），`.env.example` 则用 `!**/.env.example` 放行，因为它不含真实值。

控制台运行 `main()` 前先设置 UTF-8，否则 PowerShell 默认 GBK 代码页会把中文输出显示成乱码：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## 本课代码怎么找

```text
lessons/01-model-client.md
src/main/java/learn/agent/llm/client/
src/test/java/learn/agent/llm/client/
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
- `TokenUsage` 分别保留输入和输出、总数算出来而非存进来 —— 两者单价不同，只记总数就只知道「用量涨了」，不知道该优化哪里。
