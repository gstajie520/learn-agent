# Java 后端转 Agent 开发工程师：完整学习路线

> 制定日期：2026-08-25
>
> 目标：从 Java/Spring Boot 后端，转成能够设计、实现、上线和解释 Agent 应用的工程师。
>
> 进度档案：[agent-learning-plan.md](agent-learning-plan.md)。两份文档使用**同一套阶段编号**，修改其中一份必须同步另一份。

## 一、先定义岗位

Agent 开发工程师不是只会调用一个大模型 API，也不是只会背 LangChain 或 LangGraph API。实际工作通常包含四类职责：

1. **LLM 应用层**：消息、Prompt、Tool Calling、Structured Output、Token、Streaming、Embedding、RAG。
2. **Agent 运行时层**：Agent Loop、工具注册、权限、Hook、上下文压缩、记忆、状态、暂停恢复、重试。
3. **后端工程层**：Spring Boot、数据库、MQ、Redis、异步任务、幂等、权限、超时、可观测性。
4. **生产质量层**：安全边界、评估集、成本、延迟、日志、Trace、故障恢复和项目表达。

模型本身是不确定的，业务系统必须在模型外面建立确定性边界：

```text
用户请求
  -> 模型理解
  -> 结构化命令
  -> Schema 校验
  -> 业务校验
  -> 权限/确认
  -> 异步执行
  -> 幂等/重试/恢复
  -> 结果和审计
```

## 二、主教材：本仓库的 20 章 Harness 教程

**本仓库自身就是这条路线的主教材，不是参考资料。**

`learn-agent` 已经包含一套 20 章 Agent Harness 教程：文章在仓库根目录，TypeScript 实现在 `code/chapters/ch01/` 到 `ch20/`，Python 实现在 `python/ch01_agent/` 到 `ch20_agent/`，每章都有累计行为测试。这套教程按「一章只增加一个能力、后章保留前章行为」组织，正好覆盖 Agent 运行时层的绝大部分内容。

学习时优先读这里的代码和测试，而不是先去读外部仓库。章节与阶段的对应关系见第四节。

三类材料的分工：

| 材料 | 定位 | 怎么用 |
|---|---|---|
| 本仓库 20 章（`code/`、`python/`） | **主教材** | 按阶段读源码、跑测试、改一个分支看测试怎么红 |
| `learning/agent-java-learning/` | **Java 侧练习工程** | Java 基础、Spring Boot、Redis、MQ 的自写代码 |
| `fw` 智能场景项目 | **后半程综合参考** | 阶段 13 之后按模块拆解，不作前期教材 |

本仓库教程没有覆盖的两块，需要单独补课程：**Structured Output / JSON Schema 校验**（阶段 6）和 **RAG / Embedding / 检索**（阶段 10）。这两块要自己写 lesson，不要指望从章节代码里找到。

## 三、学习优先级

对于已有 Java 后端经验的人，建议按这个顺序投入时间：

| 能力 | 优先级 | 学习目标 |
|---|---:|---|
| LLM API 与结构化输出 | 最高 | 能稳定拿到可校验的模型结果 |
| Tool Calling 与 Agent Loop | 最高 | 能解释模型何时决定调用工具、程序如何执行工具 |
| 权限、Hook 与安全边界 | 最高 | 能在工具执行前拦住危险操作，并留下审计 |
| 上下文工程 | 高 | 能处理产物落盘、上下文压缩、跨会话记忆和 token 预算 |
| RAG | 高 | 能做有来源、可追踪的知识查询 |
| 状态与工作流 | 高 | 能处理分支、暂停、恢复、人工确认 |
| API 韧性与任务系统 | 高 | 能处理截断、限流、重试、任务依赖和后台作业 |
| Java/Spring AI | 高 | 能把 Agent 接入 Java 后端 |
| LangGraph | 高 | 重点理解 State、Node、Edge、Checkpoint，不先死记 API |
| MQ、Redis、数据库 | 高 | 支撑异步任务、状态、幂等和恢复 |
| MCP、Skills、连接器 | 中高 | 扩展工具边界和动态能力 |
| 多 Agent | 中 | 先掌握单 Agent，确有协作需求再学 |
| 模型训练、微调、分布式推理 | 低 | 除非岗位明确要求，否则不作为转型主线 |

## 四、阶段主路线

共 16 个阶段。阶段 1-4 是 Java 后端补强（已基本完成），阶段 5-11 是 Agent 核心机制，阶段 12-15 是生产化和集成，阶段 16 收尾。

「预计周数」只用于估算投入，不作为完成标准。**每个阶段的完成标准比学习时间更重要**，每周都要有代码产出。

| 阶段 | 主题 | 预计周数 | 主要语言 | 本仓库对应章节 |
|---:|---|---:|---|---|
| 1 | Java 基础与测试 | 2 | Java | — |
| 2 | Java 并发与线程池 | 2 | Java | — |
| 3 | Spring Boot 后端基础 | 2 | Java | — |
| 4 | Redis：状态、缓存、幂等 | 2 | Java | — |
| 5 | LLM 调用基础 | 2 | **Python 先**，Java 复写 | ch01 的模型客户端部分 |
| 6 | Structured Output 与 Tool Calling | 2 | Python + Java | ch02（Structured Output 需自写） |
| 7 | 手写 Agent Loop 与工具边界 | 2 | Python/TypeScript | ch01、ch02 |
| 8 | 权限、Hook 与安全边界 | 2 | Python/TypeScript | ch03、ch04 |
| 9 | 上下文工程：计划、压缩、记忆 | 3 | Python/TypeScript | ch05、ch06、ch08、ch09、ch10 |
| 10 | RAG 与 Skill 按需加载 | 2 | Python | ch07（RAG 需自写） |
| 11 | API 韧性与任务系统 | 2 | Python/TypeScript | ch11、ch12、ch13、ch14 |
| 12 | LangGraph 状态与工作流 | 3 | Python | — |
| 13 | Java Agent 集成 | 2 | Java | — |
| 14 | 分布式 Agent 后端 | 2 | Java | — |
| 15 | MCP、动态工具池与多 Agent | 2 | Python/Java | ch15、ch16、ch17、ch18、ch19 |
| 16 | 综合项目、评估与求职 | 2 | Java + Python | ch20 + `fw` |

合计约 34 周。阶段 1-4 已占前 8 周，剩余约 26 周。

### 贯穿项：不要放到最后才做

以下三项**从阶段 6 开始就要动手，每个阶段增量维护**，不是收尾工作：

- **最小评估集**：拿到第一个 Structured Output 就建。输入、期望工具、期望结构、期望业务结果各一列。每个新阶段往里加 3-5 个用例，改完代码先跑评估。没有基线的话，中间十几个阶段的所有改动都无法判断是变好还是变坏。
- **Trace 与结构化日志**：从阶段 7 手写 Loop 起就打 trace id、轮次、工具名、耗时、token。阶段 16 只是把它们汇总成报表，不是从零开始加埋点。
- **面试表达**：每个阶段结束回答 3-5 道本阶段常见面试题，按「业务含义 → 实现方式 → 一个生产风险」组织。

## 阶段 1：Java 基础与测试

Java 集合、异常、接口、泛型、IO、枚举、不可变对象和 JUnit 行为测试。用状态机作为载体。

不需要深挖 JVM 源码或复杂设计模式。目标是能读懂和修改 Agent 后端，而不是成为 JVM 专家。

**完成标准：**能写一个带合法迁移、非法迁移和终态保护的状态机，并有可运行测试；能解释为什么不同进程的内存状态彼此不可见。

## 阶段 2：Java 并发与线程池

`ExecutorService`、`Callable`、`Future`、超时、取消、异常传播、线程池大小、有界队列和拒绝策略。

**完成标准：**能解释「线程池管并发度、有界队列限 JVM 内存、MQ 保存未确认消息」三者的边界，并说明为什么不能把 MQ 积压全部搬进 JVM。

## 阶段 3：Spring Boot 后端基础

Controller/Service/Repository 分层、DTO、`@Valid` 参数校验、`@RestControllerAdvice` 统一异常、日志和配置。

**完成标准：**一个异步命令 API，能提交命令、查询状态、拒绝非法请求并返回统一错误 JSON。

## 阶段 4：Redis：状态、缓存、幂等

`SETNX + TTL` 幂等抢占、Hash 命令状态、`StringRedisTemplate`、Lua 条件更新、缓存读写与穿透/击穿/雪崩。

**完成标准：**能区分 claim key、state key、cache key 各自解决什么问题；能说明 Redis、数据库、MQ 的职责边界；有可运行测试。

## 阶段 5：LLM 调用基础

要掌握的概念：

- System、User、Assistant、Tool 消息；
- Prompt 和业务规则的区别；
- Token、上下文窗口、输入输出成本；
- Temperature、超时、重试、限流；
- Streaming 与普通请求；
- 模型错误、空结果、格式错误和服务不可用。

**语言顺序：先 Python，再 Java 复写。** 一手文档、SDK 更新和社区示例都是 Python 优先，先用 Python 把「一次请求到底传了什么、返回了什么」看透，再用 Java 重写同一个调用会快得多。可以直接读 `python/ch01_agent/` 的模型客户端部分作为参照。

**代码产出：**Python 完成一次最小模型调用并打印完整请求/响应结构；Java 把模型客户端封装成接口，测试使用 Fake 客户端，不依赖真实密钥。

**不要急着学：**多 Agent、复杂 Prompt 模板、自动规划。

## 阶段 6：Structured Output 与 Tool Calling

这是从「聊天机器人」转到「Agent 应用」的关键阶段。

学习顺序：

1. 让模型输出 JSON；
2. 用 JSON Schema 校验格式；
3. 再做业务校验，例如对象是否存在、版本是否匹配、坐标是否越界；
4. 学习 Tool Calling 的名称、参数、调用 id 和工具结果；
5. 规定工具失败时模型是否重试，哪些错误必须直接返回用户。

Tool Calling 部分参照 `code/chapters/ch02/`（`tool_registry`、Zod 输入校验）。Structured Output 和 JSON Schema 校验这一块本仓库教程没有独立章节，需要自写 lesson。

**核心原则：**结构正确不代表业务合法。模型生成的 `{"action":"delete"}` 即使 JSON 正确，也必须经过权限、对象存在性和危险操作校验。

**代码产出：**自然语言「在北侧生成雷达」转换成 `SceneOperation`，经过 Schema 校验和业务校验后只生成预览，不直接修改真实数据。

**本阶段必须建立最小评估集**，见「贯穿项」。

## 阶段 7：手写 Agent Loop 与工具边界

先不用 LangGraph，手写最小循环，理解框架到底替你做了什么：

```text
messages = [system, user]
for round in 1..N:
    response = model(messages, tools)
    if 没有 tool_calls:
        return response
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        messages.add(tool_result)
return 超过最大轮次
```

必须实现：

- 最大轮次；
- 工具白名单；
- 工具参数校验；
- 工具超时；
- 工具异常回传；
- 重复 tool call 的幂等；
- 每轮日志和 trace id。

**主教材：**`code/chapters/ch01/`（最小循环）和 `ch02/`（工具注册表、workspace 安全路径）。先自己写一遍，再对照章节实现找差异，最后跑 `npm run test:ch01`、`npm run test:ch02` 看测试在证明哪条规则。

**完成标准：**你能回答「谁决定调用工具、谁真正执行工具、工具结果如何回到模型、什么时候结束」。

## 阶段 8：权限、Hook 与安全边界

Agent 能执行工具之后，第一件事不是加更多工具，而是把危险操作拦住。

要掌握的内容：

- 权限四态决定（允许、拒绝、需审批、需确认）与统一工具错误边界；
- 审批流程和审计记录；
- Hook 生命周期：UserPromptSubmit、PreToolUse、PostToolUse、Stop；
- 为什么这些横切逻辑不能塞回 Loop 内部；
- Prompt Injection 与工具越权的基本防线。

**主教材：**`code/chapters/ch03/`（`policy`）和 `ch04/`（`hooks`）。

**完成标准：**能在不修改 Loop 主体的前提下，为某个工具加一条「必须人工确认」的策略，并留下审计记录。

## 阶段 9：上下文工程：计划、压缩、记忆

长任务失败通常不是模型不够聪明，而是上下文管理失控。这一阶段解决「Agent 工作时间怎么变长」。

学习顺序：

1. **会话计划**（ch05）：TODO 完整快照、状态校验、陈旧计划提醒，避免长任务漂移；
2. **子 Agent**（ch06）：隔离历史、共享运行边界、禁止递归委派、限制轮数；
3. **产物落盘与上下文压缩**（ch08）：结果写文件、分层裁剪、摘要恢复 token 预算；
4. **文件记忆**（ch09）：从 canonical history 提取、整理并跨会话检索；
5. **动态 Prompt 组装**（ch10）：Provider 按固定顺序生成运行态系统提示，避免复制 Loop。

**这一阶段不能省。** 它是当前 Agent 岗位面试问得最细的部分，也是 RAG 之外另一条独立能力线：RAG 是「去外部找知识」，压缩和记忆是「管好已经在手里的上下文」，两者不能互相替代。

**完成标准：**能说明四级压缩分别丢弃什么、保留什么；能解释 token 预算耗尽时系统按什么顺序裁剪；能演示一次跨会话记忆检索。

## 阶段 10：RAG 与 Skill 按需加载

RAG 的目标不是「把一堆文本塞给模型」，而是让模型基于可追踪的外部知识回答。

学习顺序：

1. 文档清洗和切分；
2. Embedding 和向量相似度；
3. Top-K 检索和 Metadata 过滤；
4. 关键词检索与向量检索的区别；
5. 混合检索、重排和引用来源；
6. 召回失败、知识过期和权限过滤。

同时读 `code/chapters/ch07/`（`skills`）：先扫描摘要，再按名称加载正文。Skill 是「知识按需进入上下文」的另一种实现，和向量检索是两条不同的路径，值得对比。

RAG 本身本仓库教程没有独立章节，需要自写 lesson。

**代码产出：**知识库问答服务，答案必须返回引用文档 id；先用内存向量或本地向量库学习，再接真实向量数据库。

**不应混淆：**RAG 是知识检索，不等于 Agent；Agent 可以调用检索工具，但 RAG 本身不负责复杂流程编排。

## 阶段 11：API 韧性与任务系统

把「Demo 能跑」变成「线上能跑」。

- **API 恢复**（ch11）：截断、超长输入、429/529、Retry-After、fallback、取消和总时限；
- **任务 DAG**（ch12）：任务依赖、原子 JSON 持久化、DAG 校验、owner 防伪造；
- **后台任务**（ch13）：先落盘再启动 worker，用占位结果和完成事件连接异步作业；
- **Cron 调度**（ch14）：时区计算、UTC 持久化、durable/session-only 生命周期、outbox 触发。

**完成标准：**能列出至少五种模型侧故障及各自处理策略，并说明哪些该重试、哪些该直接返回用户。

## 阶段 12：LangGraph 状态与工作流

LangGraph 的学习顺序：

- State：节点之间传递什么数据；
- Node：一个节点只做一个清晰动作；
- Edge：固定流转和条件分支；
- Loop：工具调用后回到模型；
- Checkpoint：保存 Agent 会话状态；
- Interrupt/Resume：人工确认后继续；
- Retry/Timeout：节点失败如何恢复；
- Thread ID：如何区分会话和任务。

**推荐语言：**Python。LangGraph 生态、资料和实际项目采用率目前明显高于 Java 图编排方案。Java 后端通过 HTTP/MQ 调用 Python Agent 服务，不代表 Java 能力降低，而是按生态边界分工。

**为什么放在阶段 7-11 之后：**前面已经手写过 Loop、权限、压缩和恢复，这时看 LangGraph 才能准确回答「它替我管了什么、代价是什么」。反过来先学框架，就只会背 API。

**完成标准：**实现一个「生成预览 → 人工确认 → 应用修改」的小图，并能从 checkpoint 恢复；能说明图的 checkpoint 与业务命令状态分别保存什么。

## 阶段 13：Java Agent 集成

Java 侧只选一个主框架：

- **Spring AI：**如果目标岗位是 Spring Boot 企业应用，优先学习；配置、模型客户端、Tool、结构化输出、向量存储与 Spring 生态更自然。
- **LangChain4j：**适合了解 Java Agent/RAG 的另一种抽象，面试中知道边界即可，除非岗位明确使用。
- **Koog：**JetBrains 的 Kotlin/JVM Agent 框架，可作为 JVM 生态观察对象，不作为当前主线。
- **Agents-Flex：**Java Agent 开源项目，适合阅读其 RAG、MCP、Skill、Sub-agent 设计，不建议在基础阶段直接依赖。

不要同时深入 Spring AI、LangChain4j、Koog、Agents-Flex。先用阶段 7 的手写 Loop 理解机制，再用 Spring AI 完成一个 Java 项目。

## 阶段 14：分布式 Agent 后端

把 Agent 当成一个不稳定、耗时、可能重试的外部服务：

```text
Java API
  -> 写入命令状态
  -> MQ 投递 Agent 任务
  -> Python Agent / LangGraph
  -> MQ 返回结构化结果
  -> Java 校验、持久化、通知前端
```

必须掌握：

- MQ ACK/NACK、重试、死信和消费幂等；
- Redis 命令状态、claim key、TTL、checkpoint 边界；
- 数据库事务和乐观锁；
- WebSocket/SSE 状态通知；
- 超时、取消、重试和补偿；
- 多实例部署下不能依赖 JVM 内存。

推荐状态迁移：`pending → running → preview/clarification → applied/failed/timeout/cancelled`。

这部分复用阶段 2-4 的 Java 能力，但它应该服务于 Agent 链路，而不是独立成为学习终点。

## 阶段 15：MCP、动态工具池与多 Agent

学习重点不是协议名，而是工具边界和协作边界。

单 Agent 扩展（优先）：

- **MCP 动态工具池**（ch19）：allowlist、连接、发布工具、命名隔离、策略分类、Registry Snapshot；
- 工具发现和注册、参数 Schema、权限与资源范围、超时、审计、限流；
- 外部 MCP 服务断开和恢复。

多 Agent 协作（按需）：

- **Teammate 与 Mailbox**（ch15）：持久队友、FIFO 消息、恢复、坏消息隔离；
- **协作协议**（ch16）：先登记再发送、完整匹配响应、计划审批、确定性 shutdown；
- **SQLite 认领**（ch17）：事务内原子认领、租约、角色工具裁剪；
- **Worktree 隔离**（ch18）：预留、绑定、执行上下文、`needs_review` 清理边界。

**完成标准：**实现一个只能读取指定目录、只能调用白名单 API 的 MCP/Tool 服务，并能记录每次调用；能说明远程工具的名称、描述和 schema 都属于外部数据，不能直接信任。

## 阶段 16：综合项目、评估与求职

先把贯穿项收拢成完整体系：

- 评估集：输入、期望工具、期望结构、业务结果；
- 质量指标：任务成功率、工具调用正确率、Schema 通过率、引用准确率；
- 成本指标：Token、模型费用、平均轮次；
- 性能指标：首 token 延迟、总延迟、工具耗时、队列积压；
- 安全：Prompt Injection、越权工具、敏感数据、危险操作确认；
- 观测：trace id、conversation id、command id、model request id。

再读 `code/chapters/ch20/`：同一个 `AgentRunner` 如何统一前 19 章的执行顺序、Registry Snapshot、tool result 配对、权限边界和资源关闭。这是「能力如何总装」的样板。

最终项目建议做一个「智能场景命令系统」或「智能任务执行系统」，必须包含：

- Java Spring Boot API；
- Python Agent/LangGraph；
- Structured Output + Schema/业务双重校验；
- 权限策略和危险操作确认；
- MQ 异步任务和结果；
- Redis 状态、幂等、缓存；
- 数据库最终结果；
- WebSocket/SSE 通知；
- 人工确认和可恢复 checkpoint；
- 测试、评估集、日志、架构图和故障复盘。

求职表达使用：

```text
问题 -> 设计 -> 权衡 -> 故障 -> 验证
```

不要说「我调用了 LangGraph API」，要说「模型输出存在不确定性，我在 Java/Python 边界增加了 Schema、业务校验、幂等、版本控制和人工确认」。

项目描述模板：

> 面向 X 场景，使用 Y 让用户通过自然语言生成结构化领域操作；以 Z 校验、幂等和确认机制隔离模型不确定性；通过 MQ/Redis/状态机实现异步执行和恢复；用测试/评估验证成功率、延迟和失败分支。

## 五、本仓库教程怎么读

从 `code/` 执行验证命令（PowerShell）：

```powershell
Set-Location '.\code'
npm ci
npm run test:ch01
npm run typecheck
```

Python 版共用一个虚拟环境，见 `python/README.md`：

```powershell
Set-Location '.\python'
& .\.venv\Scripts\python.exe -m pytest '.\ch01_agent\tests'
```

离线测试会注入模型边界，不需要真实密钥。没有凭据时优先跑测试、类型检查和构建。

每章推荐读法：

1. 先读文章的「验收结果 / 问题本质」，明确本章要证明什么；
2. 再看 `code/chapters/chNN/src/` 的组合根、核心类型和工具 handler；
3. 运行该章测试，观察状态、事件、权限、文件和错误分支；
4. **故意改坏一处，看哪个测试变红** —— 这一步比读代码有效；
5. 用下一章对比上一章：只找新增能力，以及新增能力为什么不能塞回旧模块。

不要把「文件存在」或「能导入」当作章节完成证明。

## 六、fw 项目是否适合学习

结论：**适合做阶段 13 之后的综合参考，不适合做前半程教材。**

原因是它同时包含 Java 控制面、Python LangGraph、MQ、Redis、WebSocket、前端三维渲染、语音和视频，支线会遮住 Agent 主链路。

### fw 已经包含的能力

| fw 部分 | 对应 Agent 能力 | 对应阶段 |
|---|---|---|
| `agent_service/agent/` | LangGraph State、Node、Tool Loop | 阶段 12 |
| `agent_service/services/skill_rag.py` | Skill 检索和 RAG | 阶段 10 |
| `agent_service/services/smart_scene.py` | Agent 结果提取、结构化协议 | 阶段 6、12 |
| `agent_service/skills/smart_scene/tools/` | 工具实现和业务校验 | 阶段 6、15 |
| `agent_control_app` | Java Spring Boot 控制面 | 阶段 3、13、14 |
| `RabbitMQConfig`、消息消费者 | 异步任务和服务边界 | 阶段 14 |
| `RedisConfig`、命令总线 | 状态、幂等、多实例 | 阶段 4、14 |
| WebSocket | 前端实时通知 | 阶段 14 |
| `智能场景Graph说明.md` | 项目执行图和消息时序 | 总结复习 |

### 阅读顺序

1. 只读 `智能场景Graph说明.md`，画出 Java → MQ → Python → MQ → Java；
2. 读 `agent_service/agent/node_state.py`，理解 Graph State；
3. 读 `agent_service/agent/__init__.py`，理解节点和边；
4. 读 `agent_service/agent/agent_node.py` 与 `tool_node.py`，理解模型和工具的边界；
5. 读 `smart_scene_contract.py` 与 `skills/smart_scene/tools/scene_operations.py`，理解结构校验；
6. 再读 Java `SmartSceneCommandController`、命令 Service、RabbitMQ 和 Redis；
7. 最后看 WebSocket、前端应用和完整日志。

### 现在不要先看的内容

- 语音、视频、轨迹、TTS、ONNX 等旁支能力；
- 前端三维渲染细节；
- 所有数据库表和管理后台；
- 完整部署脚本和历史兼容代码。

## 七、外部 GitHub 项目怎么用

**这些是对照材料，不是主教材。** 主教材是本仓库 20 章（第二节）。外部项目用于比较能力覆盖和工程做法，不要求全部照着学：

| 仓库 | 适合借鉴什么 |
|---|---|
| [NirDiamant/agents-towards-production](https://github.com/NirDiamant/agents-towards-production) | 从 Agent 基础到生产化、RAG、评估和部署的案例 |
| [Prompthon-IO/agent-systems-handbook](https://github.com/Prompthon-IO/agent-systems-handbook) | Agent 系统设计和生产工程视角 |
| [Haozhe-Xing/agent_learning](https://github.com/Haozhe-Xing/agent_learning) | Agent、RAG、工具、记忆、MCP 的系统化学习目录 |
| [Annyfee/agent-craft](https://github.com/Annyfee/agent-craft) | LangChain、RAG、LangGraph、MCP 的入门实战组织方式 |
| [JetBrains/koog](https://github.com/JetBrains/koog) | JVM/Kotlin Agent 框架和企业级 Agent 抽象 |
| [agents-flex/agents-flex](https://github.com/agents-flex/agents-flex) | Java Agent、RAG、MCP、Skills、Sub-agent 的 JVM 生态参考 |

参考原则：先看目录和架构，再挑一个主题和本仓库对应章节做对比；不要因为 star 高就同时学习所有框架。

## 八、当前学习路线调整

已完成或正在完成：

- 阶段 1-3：Java 状态机、线程池、Spring Boot API（DONE）；
- 阶段 4：Redis 幂等、真实客户端、Hash 状态、Spring 条件更新、缓存基础（收尾中）。

接下来不再继续无限扩展 Redis。执行顺序：

1. 阶段 4 做一次串联验收；
2. 进入阶段 5 LLM 调用基础（Python 先，Java 复写）；
3. 阶段 6 Structured Output 和 Tool Calling，同时建立最小评估集；
4. 阶段 7-9 用本仓库 ch01-ch10 打通 Loop、权限、Hook 和上下文工程；
5. 阶段 10-11 补 RAG 和 API 韧性、任务系统；
6. 阶段 12 再进入 LangGraph；
7. 阶段 13-14 回到 Java，把 Agent 接入 Spring AI、MQ 和 Redis；
8. 阶段 15-16 MCP、多 Agent、评估收拢和综合项目。

主线是「先理解 Agent 运行时，再用后端工程把它生产化」，而不是「先学完所有中间件才开始 Agent」。
