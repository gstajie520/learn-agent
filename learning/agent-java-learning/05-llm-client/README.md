# LLM 调用基础学习目录

阶段 5。第一次引入**不确定的依赖**：模型可能超时、限流、返回空内容，或者话没说完就被截断。本阶段的目标不是学会某个 SDK，而是搞清楚「一次模型调用到底传了什么、返回了什么、哪里会出错」。

和阶段 4 一样：每课有独立文档、Java 子包和测试子包。学习时只打开当前课。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | 模型调用边界、消息角色、Token、错误分类、Fake 客户端 | [01-model-client.md](lessons/01-model-client.md) | `learn.agent.llm.lesson01` | `learn.agent.llm.lesson01` |
| 2 | 真实 HTTP 调用、配置校验、超时、指数退避与抖动 | [02-real-http-call.md](lessons/02-real-http-call.md) | `learn.agent.llm.lesson02` | `learn.agent.llm.lesson02` |
| 3 | Structured Output：JSON 提取、两层校验、预览而非执行 | [03-structured-output.md](lessons/03-structured-output.md) | `learn.agent.llm.lesson03` | `learn.agent.llm.lesson03` |
| 4 | Tool Calling：模型主动选工具、prepare/invoke 分离、破坏性确认 | [04-tool-calling.md](lessons/04-tool-calling.md) | `learn.agent.llm.lesson04` | `learn.agent.llm.lesson04` |
| 5 | Agent Loop：四道工具边界、超时、幂等、Trace 与停止原因 | [05-agent-loop.md](lessons/05-agent-loop.md) | `learn.agent.llm.lesson05` | `learn.agent.llm.lesson05` |
| 6 | 权限策略：四态归约、人工确认、硬边界、审计闸门 | [06-permissions.md](lessons/06-permissions.md) | `learn.agent.llm.lesson06` | `learn.agent.llm.lesson06` |

第 6 课属于**阶段 8（权限、Hook 与安全边界）**，不属于阶段 5。它放在本模块只是因为要直接复用第 4、5 课的
`ToolRegistry` 和循环骨架，另起模块得把两课的代码搬一遍。阶段 8 的另一半（Hook 生命周期）是第 7 课。

后续课次（尚未生成，均不阻塞后续阶段）：Streaming 流式输出、连接池复用。

前五课之间的关系是阶段 5 的主线：

- 第 1 课用 Fake 客户端把业务规则测清楚；
- 第 2 课换成真实 HTTP，而**业务代码一行都没改** —— 这是第 1 课那层 `ModelClient` 接口的回报；
- 第 3 课让模型输出**结构化数据而不是文本**，程序因此可以直接执行它 —— 但必须先过两层校验；
- 第 4 课把发起权交给模型：**模型自己决定**调哪个工具、传什么参数，程序负责执行和把关；
- 第 5 课给这个循环加上完整边界（超时、幂等）和可观测性（Trace），并把「为什么停」变成枚举。

第 6 课换了一个问题：前五课问的是「这次调用能不能跑通」，第 6 课问的是「**这次调用该不该被允许**」。
它不改第 5 课的 `AgentLoop` 一行代码，靠注入一个 `PermissionPolicy` 把「必须人工确认」加进去。

第 3 课是从「聊天机器人」转向「Agent 应用」的分界线。前两课的模型输出是给人看的文本，
第 3 课开始，模型输出的是给**程序**执行的数据，所以校验从"可选"变成"必须"。

第 4 课是第二条分界线：前三课都是**程序要求模型输出点什么**，第 4 课起是**模型决定程序做什么**。
第 5 课不引入新能力，只把这个循环变成可以放心跑的东西 —— 有上限、有超时、有去重、出问题能归因。

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 05-llm-client -am test
```

除第 2 课的 3 个真实调用测试外，本阶段**全部测试都不需要密钥和网络**，使用 `FakeModelClient` 注入预设结果。这是刻意的设计：如果测试必须有真实密钥才能跑，业务逻辑就只能靠手工点。

第 3 课尤其明显 —— 校验规则是纯逻辑，用 Fake 客户端可以精确构造「模型输出了不存在的设备 id」这类场景，
而这在真实模型上很难稳定复现。

第 2 课的配置校验、JSON 解析和退避重试同样离线可测；只有 3 个真实调用测试需要配置，未配置时**明确跳过**。

配置写在 `learning/agent-java-learning/.env`，**后面所有 Java 模块共用这一份**：

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
- 模型输出只生成**预览**，不直接修改数据。真正执行需要用户确认，属于下一阶段；
- 模型「能调」不等于程序「该执行」—— 副作用等级由**程序侧枚举**声明，不写进 prompt，模型无法覆盖；
- 工具失败是**返回值**，不是异常。它要回传给模型，让模型自己换参数重试；
- 循环的结局是**枚举**（`StopReason`），不是一句话。调用方靠字段判断，不靠正则匹配模型说的话；
- 权限只有 `allow` 和 `deny` 两种结果能离开策略。`ask` 和 `passthrough` 是中间态，必须在策略内部收敛掉；
- **审计是闸门不是日志**：审计写失败时操作不执行。「副作用发生了却没有记录」比「操作失败」严重得多。

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

## 第 5 课的四道工具边界

```text
模型请求一次工具调用
  ↓ 1. prepare        查白名单 + 解析参数 + 校验      零副作用
  ↓ 2. 破坏性闸门      不可逆操作不执行，回传等待确认   排在缓存之前
  ↓ 3. 幂等缓存        同样的调用命中缓存，不重复执行   键不含 tool_call_id
  ↓ 4. 超时执行        唯一真正调 handler 的地方       结束等待，不保证结束执行
写入这一轮的 RoundTrace
```

顺序是设计的一部分：破坏性闸门在幂等缓存**之前**，因为「这次没有执行」不需要缓存。

每轮的处置写进 trace，六个 outcome 标签是完整分类：`rejected`、`blocked_destructive`、
`deduplicated`、`executed`、`failed`、`protocol_violation`。测试断言标签，不断言文案。

## 第 6 课把裁决插在哪里

```text
模型请求一次工具调用
  ↓ 1. prepare          和第 5 课一样，零副作用
  ↓ 2. 权限裁决          候选收集 → 三轮归约 → 审批收敛 → 审计   替换第 5 课的破坏性闸门
  ↓ 3. 幂等缓存          排在裁决之后
  ↓ 4. 超时执行
写入 GuardedTrace（轨迹 + 裁决记录分开存）
```

裁决**必须排在幂等缓存之前**：反过来的话，一次批准过的调用会绕开后续所有裁决，权限就只在第一次生效了。

第 6 课替换而不是叠加第 5 课的破坏性闸门 —— 同一件事有两个真相来源，迟早会对不上。

