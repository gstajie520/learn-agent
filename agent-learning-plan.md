# Agent 学习进度档案

> 当前路线：Java 后端 → Agent/LLM 应用后端。每次学习开始前读取，结束后更新。
>
> 完整路线见：[agent-engineer-roadmap.md](agent-engineer-roadmap.md)。两份文档使用**同一套阶段编号**，修改其中一份必须同步另一份。

## 学习者画像

- 目标岗位：Java Agent/LLM 应用后端工程师
- 当前优势：已有 Java 后端背景
- 当前短板：Java 基础、MQ、Redis
- 主教材：本仓库 20 章 Agent Harness 教程（`code/chapters/ch01`–`ch20`、`python/ch01_agent`–`ch20_agent`）
- 参考项目：`E:\cj\study\fw` 智能场景项目（阶段 13 之后的综合参考，不作为前期教材）

## 总体路线

16 阶段约 37 周：Java 补强（1-4）→ Agent 核心机制（5-11）→ 生产化与集成（12-15）→ 综合收尾（16）。周数于 2026-09-01 按文章体量重新标定过（阶段 9 从 3 周改 4 周、阶段 15 从 2 周改 4 周），依据见路线图「周数是怎么估的」。

主线是「先理解 Agent 运行时，再用后端工程把它生产化」。阶段 7-11 和 15 直接以本仓库章节代码为教材；`fw` 作为后半程综合参考。

| 阶段 | 主题 | 对应章节 | 状态 | 完成证据 |
|---:|---|---|---|---|
| 1 | Java 基础与测试 | — | DONE | 状态机完整项目；8 个 JUnit 测试通过；已理解跨实例幂等边界 |
| 2 | Java 并发与线程池 | — | DONE | 6 个测试通过；已理解线程池、队列、拒绝策略、MQ ACK 和幂等边界 |
| 3 | Spring Boot 后端基础 | — | DONE | 3 个 API 测试通过；已掌握 Controller、Service、DTO、参数校验和统一异常 |
| 4 | Redis：状态、缓存、幂等 | — | IN_PROGRESS | 已完成 Lettuce、Redis Hash、Spring StringRedisTemplate、Lua 条件更新和缓存读写示例；待完成阶段串联验收 |
| 5 | LLM 调用基础 | ch01 | DONE | `05-llm-client`：`ModelClient` 接口、Fake 客户端、真实 HTTP 调用、超时与指数退避；80 个测试（3 个真实调用待配密钥） |
| 6 | Structured Output 与 Tool Calling | ch02 | DONE | `06-structured-output` 52 个测试（两层校验、只出预览）+ `07-tool-calling` 17 个测试（`prepare`/`invoke` 分离、破坏性工具人工确认、TOOL 角色结果回传） |
| 7 | 手写 Agent Loop 与工具边界 | ch01、ch02 | DONE | `08-agent-loop`：`run` 返回 `AgentTrace` 而非字符串、工具超时、重复调用幂等、每轮 trace；15 个测试 |
| 8 | 权限、Hook 与安全边界 | ch03、ch04 | DONE | `09-agent-guardrails`：权限四态归约 36 个测试 + Hook 四事件与三道锁 33 个测试，共 69 个 |
| 9 | 上下文工程：计划、压缩、记忆、按需加载 | ch05、ch06、ch07、ch08、ch09、ch10 | IN_PROGRESS | 第 1 课会话计划 + 第 2 课子 Agent 已完成：`10-context-engineering` 的 `plan` 包，53 个离线测试（tracker 25 + 桥接 10 + 子 Agent 13 + 严格字段 5）；余四课待做 |
| 10 | RAG 与向量检索 | —（自写 lesson） | NOT_STARTED |  |
| 11 | API 韧性与任务系统 | ch11–ch14 | NOT_STARTED |  |
| 12 | LangGraph 状态与工作流 | — | NOT_STARTED |  |
| 13 | Java Agent 集成 | — | NOT_STARTED |  |
| 14 | 分布式 Agent 后端 | — | NOT_STARTED |  |
| 15 | MCP、动态工具池与多 Agent | ch15–ch19 | NOT_STARTED |  |
| 16 | 综合项目、评估与求职 | ch20 + `fw` | NOT_STARTED |  |

### 贯穿项进度

从阶段 6 起每阶段增量维护，不留到阶段 16：

| 贯穿项 | 起始阶段 | 状态 | 当前位置 |
|---|---|---|---|
| 最小评估集 | 6 | **完成** | 已建 `99-minimal-eval` 模块的 `learn.agent.eval.MinimalEvaluationSetTest`：跨阶段 6/7/8/9 的回归基线共 29 行，改完 `mvn -o test` 即跑 |
| Trace 与结构化日志 | 7 | **完成** | 已建 `AgentTrace`/`RoundTrace`：trace id + 每轮工具名、`tool_call_id`、结局、耗时、token；`toLogLine()` 输出 `key=value` 可 grep |
| 每章面试题 | 1 | IN_PROGRESS | 阶段 4 五课、阶段 5 至 8 各课的文档均已含「常见面试题」 |

## 当前阶段

- 阶段：9：上下文工程（计划、压缩、记忆、按需加载）
- 本阶段目标：让 Agent 在长任务里不失控 —— 会话计划快照、按需加载、上下文压缩、记忆机制
- 为什么现在学：阶段 5 到 8 已经能跑完一轮完整的「模型选工具 → 程序执行 → 裁决与 Hook」，但轮数一多上下文就爆。长任务失败通常不是模型不够聪明，是上下文管理失控
- 前置知识：阶段 7 的 `AgentTrace`（压缩要先有可裁剪的结构）、阶段 8 的裁决与 Hook（压缩不能把审计记录压掉）
- 阶段状态：IN_PROGRESS（6 课中前 2 课已完成）
- 主教材：`code/chapters/ch05`、`ch06`、`ch07`、`ch08`、`ch09`、`ch10`
- 阶段 5 至 8 的模块与文档路径见下方「已完成内容」，每个模块自带 README 导航
- 测试/验证命令：`Set-Location '.\learning\agent-java-learning'; $env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'; mvn -o test`（当前 327 个测试，3 跳过为缺 `REDIS_PASSWORD` 的真实 Redis）
- 本阶段六课进度与后续计划：

| 课次 | 主题 | 教材 | 状态 | 开工前要先解决的事 |
|---:|---|---|---|---|
| 1 | 会话计划 | ch05 | **已完成** | — |
| 2 | 子 Agent | ch06 | **已完成** | — |
| 3 | Skill 按需加载 | ch07 | 下一个 | 无阻塞。纯内存机制（扫描摘要 + 按名加载），场景域里能原样落地 |
| 4 | 产物落盘与上下文压缩 | ch08 | 待做 | **有阻塞**：需要先补 `validateToolPairing`（教材 16 处调用，压缩不能压断 tool 配对），并决定「artifact 落盘」在无文件系统的场景域里怎么落 |
| 5 | 文件记忆 | ch09 | 待做 | **有阻塞**：机制本体是 `manifest.json` + `MEMORY.md` + 文件锁，域重映射在这里绕不过去，必须先做二选一决定 |
| 6 | 动态 Prompt 组装 | ch10 | 待做 | 依赖第 3 课的 `SkillRegistry`（教材 `prompting.ts` 直接 import 它），所以第 3 课必须在它之前 |

- **第 4、5 课的阻塞是已知的、有解的**，不是临时发现：两条路（补受约束的文件工具集 / 降级为纯内存部分）已写进路线图的「Java 复刻的域约定」。四级压缩里 `microCompactHistory`、`snipCompactHistory` 是纯函数，无论选哪条路都能照做
- 本阶段的贯穿项动作：每课往 `99-minimal-eval` 加 3-5 行；第 4 课起 trace 里要能看出「哪些结果被压缩过」，否则压缩会变成静默丢数据

## 已完成内容

- 已确定学习方向：先 Java 基础，再 Redis/MQ，最后进入 Agent/LangGraph
- 已理解 Harness、Graph、MQ、Redis 在智能场景中的职责边界
- 已确认学习主线以通用基础知识为主，`fw` 只作为可选案例参考
- 已创建 `java-agent-career-coach` 学习 Skill
- 已生成 Java 状态机概念示例、完整 Maven 项目和 JUnit 测试
- 已验证主源码可由 JDK 17 `javac` 编译
- 已验证 Maven 离线测试通过；发现 Maven 默认读取旧 `JAVA_HOME` 的环境问题
- 已通过阶段 1 验收：理解不同进程/机器的内存彼此不可见，跨实例幂等需要共享持久化边界和原子条件更新
- 已生成第 2 阶段第一课：`learning/java-async-command-executor`，用 JDK 8 `ExecutorService`、`Callable` 和 `Future` 实现简单异步执行
- 已完成第 2 阶段第二课：使用两个工作线程和容量为二的有界队列观察任务执行与排队
- 当前并发项目测试通过：6 个测试，0 失败、0 错误、0 跳过
- 已创建统一 Java 多模块工程：`learning/agent-java-learning/`，包含前三个阶段目录
- 已生成第 3 阶段第一课：Spring Boot 异步命令 API，包含 POST 提交和 GET 状态查询
- 已完成第 3 阶段第二课：为命令 API 增加 `@Valid` 请求校验、`CommandNotFoundException` 和 `@RestControllerAdvice` 统一错误响应
- 统一多模块工程全量测试通过：17 个测试，0 失败、0 错误、0 跳过
- 已生成第 4 阶段第一课：用 `RedisLikeStore` 模拟 Redis 的原子 `SETNX + TTL`，实现 commandId 幂等抢占
- Redis 第一课包含可运行 `RedisIdempotencyDemo` 和 4 个带中文业务注释的测试；统一工程累计 21 个测试通过
- 已完成第 4 阶段第二课：使用 Lettuce `RedisClient` 连接真实 Redis，发送 `SET NX EX`、`GET`、`TTL` 和 `DEL`
- 本机 127.0.0.1:6379 可达但 Redis 开启认证；代码改为从 `REDIS_PASSWORD` 环境变量读取密码，未提供时跳过真实测试
- 本次全量测试结果：历史模块和离线 Redis 测试通过；真实 Redis 测试因未提供 `REDIS_PASSWORD` 跳过，不能记为真实连接通过
- 根据学习反馈移除 `record`、自定义任务句柄和 CountDownLatch 测试，改为 Java 8 常见的 `Callable + Future + try/finally`
- 已生成第 5 阶段第一课：`05-llm-client`，把模型调用抽象成 `ModelClient` 接口，业务层不依赖任何厂商 SDK
- 第一课包含 `ChatRole`、`ChatMessage`、`ChatRequest`、`ChatResponse`、`TokenUsage`、`FinishReason`、`ModelException` 和 `SceneSummaryService`
- 已补齐第一课的 26 个 JUnit 测试、`lessons/01-model-client.md` 课程文档和模块 README 导航
- 已把 `05-llm-client` 注册进根 `pom.xml`，统一工程可一次运行全部阶段测试
- 已生成第 5 阶段第二课：真实 HTTP 调用。含 `ModelSettings` 配置校验、`ChatJsonCodec` 编解码、`HttpModelClient` 传输层、`RetryingModelClient` 指数退避
- 第二课环境变量与 `python/ch01_agent` 对齐（`OPENAI_BASE_URL`/`OPENAI_API_KEY`/`OPENAI_MODEL`），同一份配置两边通用
- 已验证第 1 课的 `SceneSummaryService` 换成真实 HTTP 客户端后**一行未改**，证明 `ModelClient` 接口的价值
- 已补 `learning/agent-java-learning/.gitignore` 的 `.env` 防御规则：Java 侧原先没有，密钥只从环境变量读取
- 已按学习反馈为阶段 5 全部测试方法补方法级说明（规则 / 为什么重要 / 违反会怎样）；此前 70 个方法 0 个有说明
- 已生成第 5 阶段第三课：Structured Output。四步链路 = 解析 → 结构校验 → 业务校验 → 预览
- 第三课核心论点已由测试证明：结构完全合法的 JSON 仍可能业务非法（设备不存在、受保护、场景已满）
- 第三课坚持「只生成预览，不修改数据」；`SceneSnapshot` 为不可变快照，校验全程无写操作
- 统一多模块工程全量测试通过：151 个测试，0 失败、0 错误、6 跳过（3 个真实 Redis 缺 `REDIS_PASSWORD`，3 个真实模型调用缺 `OPENAI_*`）
- 各模块分布：状态机 8、并发 6、Spring Boot 3、Redis 12（跳 3）、llm-client 122（跳 3）
- 已按学习反馈重写测试注释风格：从固定的「规则 / 为什么重要 / 违反会怎样」三段表改为一句话说清在证明哪条规则。原因是每段都写「很重要」，信号就没了
- 已生成第 5 阶段第五课（阶段 7）：手写 Agent Loop。`run` 返回 `AgentTrace` 而不是 `String`，停止原因是 `StopReason` 枚举
- 第五课只补 lesson04 没有的三件事：工具超时、重复 tool call 幂等、trace id 与每轮日志；最大轮次/白名单/参数校验/异常回传直接复用 lesson04
- 四道有序工具边界：prepare（零副作用）→ 破坏性闸门 → 幂等缓存 → 超时执行。破坏性闸门在缓存之前，因为「不执行」不需要缓存
- 幂等键故意不含 `tool_call_id`（每次都不同，算进去永不命中）；失败结果不缓存，避免一次偶发超时在整个会话里变成永久失败
- 第五课 15 个测试全绿（`AgentLoopTest` 10 + `ToolCallMemoTest` 5）；`TraceIdGenerator` 接口让 trace id 在测试里可固定
- 已生成阶段 9 第 1 课：`10-context-engineering` 会话计划。`TodoTracker` 只收完整快照，`beforeModel()` 给请求级临时提醒，`PlanReminderHook` 接进阶段 8 的循环；35 个离线测试
- 已生成阶段 9 第 2 课：子 Agent。`task` 工具隔离消息历史、共享 Hook 与权限策略、两道防线封死递归委派；13 个离线测试

## 需要复习

- 主题：Harness 与 Graph 的区别
  - 复习原因：后续学习 LangGraph 时避免把业务状态机和 Agent 图混为一谈
  - 复习方式：用一句话解释“运行环境”和“流程编排”的区别
  - 验收问题：为什么智能场景需要 LangGraph + Java 业务状态机，而不是只用其中一个？
- 主题：RabbitMQ、Redis、WebSocket 的职责
  - 复习原因：进入 MQ/Redis 阶段前需要明确消息、状态和通知的边界
  - 复习方式：画出 Java → MQ → Python → MQ → Java 的时序
  - 验收问题：为什么 MQ 不能代替 Redis 保存当前命令状态？

- 主题：每章常见面试题
  - 复习原因：把代码学习转成能用于面试的基础表达
  - 复习方式：每章结束回答 3～5 道与本章相关的常见问题
  - 验收要求：先说业务含义，再说实现方式和一个生产风险

## 下一阶段

- 阶段 9 第 3 课**Skill 按需加载**（教材 `code/chapters/ch07`）：先扫描摘要、再按名称加载正文。这是把 ch07 从原阶段 10 挪回来的 —— 教材 ch10 的动态 Prompt 直接依赖 SkillRegistry，学第 6 课之前必须先有它
- 阶段 9 六课的进度：第 1 课会话计划、第 2 课子 Agent **均已完成**，第 3 至 6 课（Skill 按需加载、产物落盘与压缩、文件记忆、动态 Prompt 组装）未开始
- 第 1 课留下的伏笔已了结：补了 `ToolRoundObserver` 扩展点（教材 ch05 本来就有），提醒改走请求级临时上下文，不再绕 Hook。上期那条「等第 5 课 Provider 解决」的记录是错的，Provider 管的是系统提示组装，不是这个
- 第 2 课留下的伏笔：子 Agent 只回一句结论，**那句结论没有落盘**。第 4 课把产物写文件之后，委派的结论也该走同一条路 —— 回路径而不是回全文
- 阶段 5 至 9 的交付明细见「已完成内容」，模块与包路径见各模块 README

### 已解决：阶段与模块编号对齐

- 原偏差：阶段 6、7、8 的代码都作为 `05-llm-client` 的子课（`lesson03` 到 `lesson07`）交付，一个模块装了四个阶段，目录编号和阶段编号对不上
- 处理（2026-08-26）：拆成 `06-structured-output`、`07-tool-calling`、`08-agent-loop`、`09-agent-guardrails` 四个模块，加上跨阶段的 `99-minimal-eval`。此后**一个模块对应一个阶段**
- 包名随之从 `lessonNN` 改为按主题命名：`client`、`structured`、`tool`、`loop`、`permission`、`hook`
- 拆分是纯搬迁：234 个测试在拆分前后完全一致，没有改动任何逻辑

### 贯穿项

- **最小评估集**：`99-minimal-eval` 模块的 `MinimalEvaluationSetTest`，29 行跨阶段回归基线。它依赖全部上游模块，所以必须留在最末端，不能被任何模块依赖。每进入一个新阶段往里加 3-5 行
- **Trace 与结构化日志**：已补（`AgentTrace`/`RoundTrace`，阶段 7）。做成内存里可断言的对象而不是日志行：测试能直接断言「第 2 轮调了哪个工具、为什么停」，不用 grep stdout；后续接日志框架时序列化即可，不必重新找埋点位置

### 阶段 5 收尾可选项

- Streaming 流式输出、连接池复用。两项都不阻塞后续阶段

## 学习会话记录

### 2026-08-21

- 本次目标：启动 Agent 学习路线并确定 Java 优先顺序
- 实际完成：建立阶段路线，确认 Java 基础、MQ、Redis 是前置重点
- 代码/测试产出：尚未生成；下一次学习先生成状态机概念示例和完整 Maven 项目
- 未解决问题：Java 基础薄弱的具体范围还需要通过状态机练习暴露
- 复习安排：Harness/Graph；MQ/Redis/WebSocket 边界
- 下一次主任务：阅读状态机短示例，再运行完整 Java + JUnit 项目

### 2026-08-21（状态机课程）

- 本次目标：理解 Java 枚举、封装、异常、不可变迁移表和 JUnit 行为测试
- 实际完成：生成状态机短示例和完整 Maven 项目；实现合法迁移、非法迁移与终态保护
- 代码/测试产出：`learning/java-state-machine`；8 个 JUnit 测试通过（0 失败、0 错误、0 跳过）
- 未解决问题：无；阶段验收通过
- 本次复述反馈：学习者明确指出不同机器/进程拥有独立内存，重复消费时彼此不可见；幂等必须使用共享持久化边界和原子更新
- 学习材料反馈：测试类缺少业务说明和注释，已补充测试类总览、每个测试的规则说明以及 Arrange/Act/Assert 注释
- 环境发现：终端 Java 为 17，但 Maven 的 `JAVA_HOME` 原为 JDK 8；`.m2/settings.xml` 仍有根元素警告
- 复习安排：阅读 README 概念示例；依次查看测试、枚举、领域对象和异常
- 下一次主任务：阅读并运行 Java 并发与线程池的概念示例和完整异步命令执行器

### 2026-08-21（阶段 1 验收）

- 验收问题：两个 MQ 消费者为什么不能依靠各自内存里的 `SceneCommand.status` 防止重复处理？
- 学习者回答：不同消费者运行在自己的机器/进程中，拥有独立主机内存；共享持久化边界配合原子更新才能保证幂等
- 结论：阶段 1 `DONE`，阶段 2 `IN_PROGRESS`
- 复习安排：状态机终态和“内存状态不等于共享状态”在进入 Redis/MQ 前回顾
- 下一次主任务：异步命令执行器

### 2026-08-21（并发与线程池第一课）

- 本次目标：理解线程池、Future、超时、取消、异常传播和线程池关闭
- 实际完成：生成 JDK 8 常见版线程池示例；用 `ExecutorService.submit(Callable)` 返回 `Future`
- 代码/测试产出：`learning/java-async-command-executor`；`AgentTaskDemo` 可运行，4 个带业务说明和 Arrange/Act/Assert 注释的 JUnit 测试通过
- 学习材料反馈：代码从复杂封装改为普通类、匿名 `Callable`、显式 `try/finally`；增加“这课解决什么问题”的场景说明
- 未解决问题：线程池大小、队列、拒绝策略和 CompletableFuture 链式编排尚未学习
- 复习安排：用一句话解释“线程池管线程，Future 管一次任务结果，MQ 管跨服务消息”
- 下一次主任务：线程池队列、并发度和 CompletableFuture 基础

### 2026-08-21（并发课程降级为 JDK 8 基础写法）

- 调整原因：学习者希望先看工作中更常见、更直白的 JDK 8 写法
- 实际调整：删除 `record`、自定义结果对象、`AsyncCommandTask` 和 CountDownLatch 测试
- 当前核心：`ExecutorService.submit(Callable)` 返回 `Future`，使用 `Future.get()`、`cancel()` 和 `shutdown()`
- 阅读要求：先只阅读 `shouldGetTaskResult`，看懂后再读超时、取消和异常测试

### 2026-08-21（并发课程补充学习目标）

- 学习者反馈：只给测试类看不出学习意义，要求先解释真实后端用途，并坚持 JDK 8 常见代码风格
- 已补充：`AgentTaskDemo` 主入口，模拟“Java 收到智能场景请求 → 线程池执行 Agent 慢任务 → 获取结果 → 关闭线程池”
- 当前结论：线程池解决单 JVM 内的任务执行资源管理；它不会自动提供 MQ、Redis、幂等或真正的 HTTP 异步响应
- 验收回答：`Callable.call()` 在线程池线程执行；`Future` 是获取未来结果的凭证；`future.get()` 可能等待
- 下一次主任务：先用 `AgentTaskDemo` 口头复述执行顺序，再学习线程池大小、任务排队和拒绝策略

### 2026-08-21（线程池大小与任务队列）

- 本次目标：理解任务数量大于工作线程数量时，任务在哪里等待，以及线程和队列都满时会发生什么
- 实际完成：生成 `ThreadPoolQueueDemo`；使用 `ThreadPoolExecutor`、两个固定工作线程、容量为二的 `ArrayBlockingQueue` 和 `AbortPolicy`
- 运行观察：任务 1、2 立即执行；任务 3、4 进入队列；工作线程完成后继续取出排队任务
- 代码/测试产出：增加 `ThreadPoolQueueTest` 两个规则测试；并发项目累计 6 个测试通过
- 当前结论：工作线程决定并行数量；任务队列保存本 JVM 内等待执行的任务；拒绝策略处理线程与队列都满的情况
- 重要边界：线程池内存队列不能替代 MQ，服务重启时内存任务可能丢失，MQ 未确认消息可重新投递
- 验收结果：第 1 题正确；第 2 题理解了无界积压可能导致内存压力和溢出；第 3 题修正为不能把 MQ 全部消息搬入 JVM 内存，应按线程池处理能力消费并在成功后 ACK
- 下一次主任务：学习拒绝策略如何与 MQ ACK/NACK 配合

### 2026-08-24（线程池队列验收）

- 学习者回答：线程数量决定同一时间能执行多少任务；继续接收任务可能导致内存溢出；最初认为 MQ 消息应全部进入内存后按顺序执行
- 纠正重点：MQ 是可持久化的跨服务消息边界，线程池队列只是当前 JVM 的执行缓冲区；不能把 MQ 积压全部转移到 JVM
- 正确处理：消费者只拉取有限数量的消息；成功执行后 ACK；失败、超时或服务宕机前未 ACK 的消息由 MQ 保留或重新投递
- 当前可复述结论：线程池控制并发度，有限队列限制 JVM 内存压力，MQ 保存尚未完成确认的消息
- 复习问题：为什么“先从 MQ 全部取出，再慢慢放入线程池”会削弱 MQ 的可靠性？

### 2026-08-24（进入 Spring Boot 阶段）

- 阶段切换：阶段 2 Java 并发与线程池标记 `DONE`；阶段 3 Spring Boot 后端基础标记 `IN_PROGRESS`
- 统一工程：将之前的状态机、并发和 Spring Boot 练习集中到 `learning/agent-java-learning/` 多模块 Maven 工程
- 本次产出：`03-springboot-command-api`，实现 `POST /api/commands` 提交命令和 `GET /api/commands/{commandId}` 查询状态
- 业务链路：Controller 接收请求，Service 创建 commandId 并提交线程池，后台任务更新内存状态，查询接口返回当前状态
- 测试注意：提交后的瞬时状态可能是 `PENDING` 或 `RUNNING`，测试验证状态集合和最终 `SUCCEEDED`，不把并发时序写死
- 未解决问题：当前状态保存在 JVM 内存，重启丢失；尚未加入参数校验、统一异常、Redis 和 MQ
- 下一次主任务：运行 Spring Boot API，理解 Controller、Service 和 DTO 的职责边界

### 2026-08-24（Spring Boot 校验与异常）

- 本次目标：让 HTTP 接口拒绝非法请求，并统一返回可被前端识别的错误 JSON
- 实际完成：加入 `@Valid`、`@NotBlank`、`CommandNotFoundException`、`ApiErrorResponse` 和 `GlobalExceptionHandler`
- 测试产出：空指令返回 `400 INVALID_ARGUMENT`；不存在命令返回 `404 COMMAND_NOT_FOUND`；Spring Boot 模块共 3 个测试通过
- 代码规范反馈：本次新增主代码、异常类、测试类和关键断言均补充中文业务注释；继续使用 Java 8 普通类和显式写法
- 阶段结论：阶段 3 `DONE`；Controller 负责 HTTP，Service 负责业务，Advice 负责统一错误边界
- 下一阶段：阶段 4 Redis，替换内存状态，学习共享状态、TTL 和幂等原子操作

### 2026-08-24（Redis SETNX 与幂等第一课）

- 本次目标：理解两个消费者处理同一 commandId 时，如何只允许一个消费者执行业务
- 实际完成：新增 `04-redis` 模块；实现 `RedisLikeStore.setIfAbsent()`、TTL、`IdempotencyService` 和教学入口
- 运行结果：第一次消费返回 `CLAIMED`；重复消费返回 `ALREADY_CLAIMED`
- 测试产出：验证 SETNX 首次成功、重复失败、TTL 过期可重新抢占、空 commandId 被拒绝；Redis 模块 4 个测试通过
- 重要边界：当前实现只模拟 Redis 语义，不能跨 JVM；下一课使用真实 Redis 和 `StringRedisTemplate`
- 代码规范：新增类、字段、方法、业务分支和测试均使用中文注释说明用途
- 下一次主任务：安装/确认 Redis 环境，把 Spring Boot 命令状态迁移到真实 Redis

### 2026-08-24（真实 Redis 客户端）

- 本次目标：从 Redis 语义模拟切换到真实 Redis 服务，理解 Java 客户端如何发送原子命令
- 实际完成：新增 `RealRedisIdempotencyStore`，使用 Lettuce 连接 127.0.0.1:6379；实现 `SET NX EX`、`GET`、`TTL`、`DEL`
- 教学入口：新增真实连接代码和测试；端口可达但服务要求认证，密码必须通过 `REDIS_PASSWORD` 环境变量提供，禁止硬编码和提交 Git
- 验证状态：真实 Redis 认证测试 `Blocked, not run`；需要设置密码后重新运行 `mvn -o test`
- 代码规范：真实连接类、测试和资源关闭逻辑均补充中文注释
- 下一次主任务：把阶段 3 Spring Boot 命令状态从 ConcurrentHashMap 迁移到真实 Redis

### 2026-08-24（Redis Hash 命令状态）

- 本次目标：把阶段 3 的 JVM 内存命令状态迁移到 Redis Hash，理解共享状态的保存、读取和过期
- 实际完成：新增 `RedisCommandState`、`RedisCommandStateStore` 和 `RedisCommandStateDemo`；使用 Lettuce 的 `HSET`、`HGETALL`、`EXPIRE` 与 `MULTI/EXEC`
- 代码产出：真实 Redis 状态测试包含中文注释，按 Arrange / Act / Assert 验证字段和 TTL
- 验证状态：统一 Maven 测试 `BUILD SUCCESS`；历史与离线 Redis 测试通过；真实 Redis 状态测试因未设置 `REDIS_PASSWORD` 跳过，记为 `Blocked, not run`
- 学习结论：Java `ConcurrentHashMap` 只解决单 JVM 状态；Redis Hash 让多个服务实例共享命令状态；Redis 不是最终业务数据库
- 常见面试题：本课 README 已补充 Hash 与 SET 的选择、Redis 与数据库边界、MULTI/EXEC 的作用、TTL 风险
- 复习安排：用一句话解释“幂等 claim key”和“命令 state key”分别解决什么问题
- 下一次主任务：在 Spring Boot 中使用 Redis 保存和查询命令状态，并学习条件更新避免旧状态覆盖新状态

### 2026-08-25（Spring Redis 与条件状态更新）

- 本次目标：使用 Spring 管理 Redis 连接，并让命令状态更新具备“预期旧状态匹配才允许写入”的条件
- 实际完成：新增 `SpringRedisConfig`、`SpringRedisCommandStateStore`、`SpringRedisCommandStateService` 和 `SpringRedisCommandDemo`
- 实现重点：使用 `StringRedisTemplate` 保存 Hash；使用 Lua 在 Redis 内完成状态检查与更新，避免 Java 先查再改产生竞态
- 测试产出：新增 2 个离线条件更新测试和 1 个真实 Spring Redis 集成测试；离线测试验证匹配更新成功、旧状态更新失败
- 验证状态：Redis 模块 `BUILD SUCCESS`；9 个测试中 6 个执行通过，3 个真实 Redis 测试因未设置 `REDIS_PASSWORD` 跳过，记为 `Blocked, not run`
- 学习结论：`StringRedisTemplate` 负责 Spring 集成和生命周期；Lua 条件更新解决 Redis 内部的并发检查问题；这仍不能替代跨 Redis/数据库事务
- 常见面试题：本课 README 已补充 StringRedisTemplate、Lua、条件更新失败语义和构造方法注入题目
- 复习安排：能说明“状态更新返回 false”为什么通常是业务竞争结果，而不是系统异常
- 下一次主任务：学习 Redis 缓存读写策略、缓存穿透/击穿/雪崩的基础处理

### 2026-08-25（Redis 缓存基础与课程拆包）

- 本次目标：理解缓存命中、空值缓存、主动删除，以及缓存穿透、击穿、雪崩的区别；同时让每课代码和文档可独立定位
- 实际完成：新增 `CommandCacheClient`、`SpringRedisStringCacheClient`、`CommandCacheService` 和 `CommandCacheDemo`
- 测试产出：新增 3 个离线测试，验证重复查询只回源一次、空值缓存防穿透、删除缓存后重新回源
- 结构调整：`04-redis` 拆成 `lessons/01` 到 `lessons/05` 五篇文档；Java 和测试分别拆到 `lesson01` 到 `lesson05` 子包；根 README 只保留导航
- 验证状态：Redis 模块 `BUILD SUCCESS`；12 个测试中 9 个执行通过，3 个真实 Redis 测试因未设置 `REDIS_PASSWORD` 跳过，记为 `Blocked, not run`
- 学习结论：缓存只负责加速，不是最终业务事实；单 JVM 锁不能代替跨实例协调；数据库更新成功后通常删除相关缓存
- 常见面试题：缓存课文档已补充穿透、击穿、雪崩、空值缓存、TTL 抖动和更新后删除缓存题目
- 复习安排：能用自己的话区分“穿透是查不存在、击穿是热点过期、雪崩是大量同时失效”
- 下一次主任务：完成 Redis 阶段收尾，串联命令状态、幂等、缓存和 Spring Boot 查询边界，然后进入 RabbitMQ

### 2026-08-25（Agent 工程师路线重审）

- 本次目标：重新评估 Java 转 Agent 开发需要的完整能力，判断 `fw` 是否适合作为主教材
- 调研证据：阅读 `fw` 的 Java 控制面、Python LangGraph、智能场景 Graph 说明和服务目录；参考 GitHub 上的 `NirDiamant/agents-towards-production`、`Prompthon-IO/agent-systems-handbook`、`Haozhe-Xing/agent_learning`、`Annyfee/agent-craft`、`JetBrains/koog`、`agents-flex/agents-flex`
- 关键结论：Agent 工程师需要 LLM 基础、Structured Output、Tool Calling、Agent Loop、RAG、Graph 状态、Java 集成、MQ/Redis 生产化、MCP/Skills、安全、评估和可观测性；不能只学习中间件或框架 API
- `fw` 定位：适合阶段后半程综合项目；不适合前期教材，因为同时包含 Java、Python、LangGraph、MQ、Redis、WebSocket、前端、语音、视频和领域模型
- 新路线：新增 `agent-engineer-roadmap.md`，采用 24 周 10 阶段路线；先理解 Agent 机制，再用 Java 后端能力将其生产化（该编号已于同日被 16 阶段路线取代，见下一条记录）
- 路线调整：Redis 完成一次串联验收后，不再无限扩展 Redis，下一主题切换到 LLM 调用基础，再学习 Tool Calling、手写 Loop、RAG 和 LangGraph
- 复习安排：阅读路线文档第“四、fw 项目是否适合学习”，按 Graph State → Node → Tool → Contract → Java 命令链路顺序分析项目
- 下一次主任务：Redis 阶段收尾验收，并创建 LLM 调用基础的独立课程目录

### 2026-08-25（路线修正：统一编号并接入本仓库教程）

- 本次目标：审查 `agent-engineer-roadmap.md` 是否合理，并修正发现的问题
- 发现问题一：路线完全没有引用本仓库自身的 20 章 Agent Harness 教程（`code/chapters/ch01`–`ch20`、`python/ch01_agent`–`ch20_agent`），却让学习者去读 6 个外部 GitHub 仓库。手写 Loop、Skill、MCP、权限、Hook、API 韧性等主题在本仓库已有可运行代码和测试门禁
- 发现问题二：阶段编号存在**三套**互相冲突的版本 —— `agent-engineer-roadmap.md`（0-10 共 11 阶段）、`agent-learning-plan.md`（13 阶段）、`skills/java-agent-career-coach/references/roadmap.md`（12 周）。同一个「阶段 4」在两份文档里分别指 Redis 和 RAG
- 发现问题三：24 周中 8 周给 Java 后端（既有优势），仅 4 周给 Agent 核心机制（实际短板），比例倒置；且缺少「上下文工程」（压缩、产物落盘、跨会话记忆、动态 Prompt）独立阶段 —— 这与 RAG 检索不是同一件事
- 其他修正：阶段 1 用 Java 学 LLM 调用改为 Python 优先再 Java 重写；评估集从阶段 9 收尾项改为阶段 6 起的贯穿项
- 实际修改：重写 `agent-engineer-roadmap.md` 为 16 阶段约 34 周；重写 `skills/java-agent-career-coach/references/roadmap.md` 为编号速查摘要；更新 `SKILL.md` 的教材规则、贯穿项和 Python 使用范围；同步本档案阶段表并新增「贯穿项进度」表
- 编号原则：保留阶段 1-4 原有含义，使阶段 1-3 的 DONE 完成证据继续有效；新增阶段插入在 5 之后
- 三份文件现使用同一套编号，修改任一份必须同步其余两份
- 下一次主任务：Redis 阶段（阶段 4）收尾验收，然后按阶段 5 从 `python/ch01_agent` 开始

### 2026-08-26（阶段 5 第 1 课：模型调用边界补全）

- 本次目标：把已有的 `05-llm-client` 半成品补全为可运行、可验证、可导航的一课
- 起始状态：`lesson01` 只有 11 个主源码文件；未注册进根 `pom.xml`、没有任何测试、没有课程文档
- 实际完成：注册 `05-llm-client` 模块；新增 3 个测试类；新增 `lessons/01-model-client.md` 和模块 README
- 测试产出：`SceneSummaryServiceTest` 9 个、`ChatRequestTest` 7 个、`ChatResponseTest` 10 个，共 26 个测试通过
- 覆盖规则：截断被拦截、可重试错误重试、不可重试错误立即失败、失败请求同样计费、请求不可变、`isUsable()` 边界
- 验证状态：`mvn -o test` 全量 `BUILD SUCCESS`；55 个测试，0 失败、0 错误、3 跳过（真实 Redis 测试未设 `REDIS_PASSWORD`）
- 运行验证：`SceneSummaryDemo` 四个场景正常输出；Windows 控制台需要 UTF-8 代码页才能正确显示中文，非代码问题
- 学习结论：业务代码只依赖 `ModelClient` 接口，因此不需要密钥和网络也能测出截断、限流和鉴权分支
- 关键边界：`finishReason` 比 `content` 更重要；失败的请求同样计费；`chat()` 是阻塞调用，不能放在 Web 请求线程里
- 常见面试题：本课文档已补充 5 道（Fake 客户端价值、finishReason、错误分类、Token 分开统计、system/user 分离）
- 待学习者验收：口头回答本课 5 道面试题，重点是「为什么截断比报错更危险」
- 下一次主任务：阶段 5 第 2 课，把 Fake 客户端换成真实 HTTP 调用，密钥从环境变量读取，并加入超时和退避重试

### 2026-08-26（阶段 5 第 2 课：真实 HTTP 调用与退避重试）

- 本次目标：把第 1 课的 Fake 客户端换成真实 HTTP 调用，并补上第 1 课欠的退避等待
- 实际完成：新增 `lesson02` 六个主类和四个测试类；第 2 课文档；模块 README 增加第 2 课导航
- 主类职责：`ModelSettings` 配置校验、`ChatJsonCodec` 编解码与错误映射、`HttpModelClient` 传输、`RetryingModelClient` 退避、`Sleeper` 可测等待
- 测试产出：`ModelSettingsTest` 11 个、`ChatJsonCodecTest` 18 个、`RetryingModelClientTest` 9 个、`HttpModelClientTest` 6 个（3 个需密钥）
- 验证状态：`mvn -o test` 全量 `BUILD SUCCESS`；99 个测试，0 失败、0 错误、6 跳过（3 真实 Redis + 3 真实模型调用）
- 运行验证：`RealModelCallDemo` 六个场景正常输出；前五个场景无需密钥即可完整教学
- 关键验证：`HttpModelClientTest.shouldWorkWithLesson01ServiceUnchanged` 证明第 1 课的 `SceneSummaryService` 一行未改就能对接真实模型
- 修正的问题一：`pom.xml` 注释原写「第 3 课需要 Jackson」，与文档和 Demo 的「第 2 课」矛盾，已统一为第 2 课
- 修正的问题二：端点拼接原本会加 `/v1`，但 Python 的 OpenAI SDK 只追加 `/chat/completions`；若不改，同一份配置在 Python 能跑、Java 会 404
- 安全发现：Java 侧 `.gitignore` 原先没有 `.env` 规则（Python 侧有）。本课密钥只走环境变量，并补了防御性忽略规则
- 已确认 `python/.env` 未被 git 跟踪、不在提交历史中
- 学习结论：不设超时（默认 0 = 永不超时）会让线程池被慢请求占满；失败响应体在 `errorStream` 而非 `inputStream`；未知 `finish_reason` 要归 `UNKNOWN` 而不是 `STOP`
- 关键边界：超时不代表服务端没执行，请求可能已计费；抖动用于避免多客户端同时重试形成惊群
- 常见面试题：本课文档已补充 5 道（超时默认值、限流为何不能立即重试、响应为何不可信、业务代码为何不用改、为何给等待定接口）
- 待学习者验收：配置 `OPENAI_*` 三个环境变量跑通真实调用；口头回答本课 5 道面试题
- 下一次主任务：Structured Output，同时按路线要求建立最小评估集和 trace 日志

### 2026-08-26（阶段 5 第 3 课：Structured Output 与两层校验）

- 本次目标：让模型输出结构化 JSON，并建立「Schema 校验 + 业务校验」两层防线，最终只生成预览不改数据
- 实际完成：新增 `lesson03` 十一个主类和四个测试类；第 3 课文档；模块 README 增加第 3 课导航
- 核心链路：`propose()` 四步 —— 调模型（temperature=0）→ 解析 JSON → 结构校验 → 业务校验 → 预览
- 两层分工：Schema 层是纯函数，用写死常量判断（字段搭配、坐标绝对范围）；业务层依赖 `SceneSnapshot`，判断设备是否存在、场景是否已满、设备是否受保护
- 关键结论：同一个操作在不同场景下结论不同 —— 这就是业务校验必须独立成层的原因，也是「结构正确 ≠ 业务合法」的具体证据
- 测试产出：解析 15 个、Schema 11 个、业务 15 个、端到端 11 个，共 52 个测试通过，全部离线
- 注释覆盖：52/52 测试方法都有「规则 / 为什么重要 / 违反会怎样」三段式说明，本次一次到位，未重复上次的遗漏
- 验证状态：`mvn -o test` 全量 `BUILD SUCCESS`；151 个测试，0 失败、0 错误、6 跳过
- 运行验证：`StructuredOutputDemo` 八个场景全部按预期输出，含「JSON 合法但设备不存在」和「删除受保护设备」两个关键拦截
- 实现过程中发现并修正的三个真实缺陷（不是测试问题）：
  1. system 消息只放了 schema 说明，**没放当前场景状态** —— 模型不知道有哪些设备 id，只能编，编出来必被业务层拦掉，白烧一轮 token。已补场景边界、设备清单、受保护设备
  2. Schema 层缺坐标绝对范围校验 —— 999999 这类明显荒谬的值应在纯函数层挡掉，不必带到需要查状态的下一层
  3. 两层 null 策略不一致 —— 业务层原先抛异常、Schema 层返回 fail。已统一为返回 fail：校验器是防线，防线自己不该崩
- `reason` 改为必填：预览要让用户判断模型有没有理解错，没有理由的预览等于让用户盲目点确认
- 暴露的一个已知缺陷（如实记录，未修）：模型返回 JSON 数组时，提取算法取第一个对象，**其余元素被静默丢弃**。批量操作涉及部分成功和事务边界，留到后续阶段
- 教训：本次多处凭记忆写方法名导致编译失败（`failure` vs `fail`、`getOperation` vs `getType`、`ADD` vs `CREATE`），应先读实际定义再写调用
- 待学习者验收：口头回答第 3 课 5 道面试题，重点是「为什么两层校验不能合并成一层」
- 下一次主任务：建立最小评估集（路线要求现在就做），然后进入 Tool Calling

### 2026-08-26（提交前发现本地档案落后于远端）

- 起因：准备提交今天的代码时发现 `origin/master` 比本地 `master` 多一个提交 `9ed1f87`（8-25 22:23，由学习者从别处推送），本地反而落后
- 影响面：本地工作区里 `.gitignore`、`SKILL.md`、`python/ch20_agent/tests/test_mailbox.py`、`agent-learning-plan.md` 四个文件是 `9ed1f87` **之前**的旧版本
- 风险：如果直接把工作区提交上去，会把学习者已推送的内容**反向覆盖** —— 尤其是本档案的 16 阶段表和「贯穿项进度」表会退回旧的 13 阶段版本
- 处理方式：先 `git reset --mixed origin/master` 把分支指针前移（不动工作区、不丢提交），再从 `origin/master` 取回那三个纯回退文件，最后把今天的进度重新叠加到本档案的新版结构上
- 教训：多机器/多客户端提交同一仓库时，提交前必须先 `git fetch` 并确认本地是否落后；只看 `git status` 看不出这一点，因为它只和本地 HEAD 比较
- 遗留：`gcm-diagnose.log` 是 Git 凭据管理器的诊断日志，未提交也未加忽略规则，需要时自行删除

### 2026-08-28（阶段 5 第 4 课：Tool Calling 与 prepare/invoke 分离）

- 本次目标：让模型**主动决定**调用哪个工具、传什么参数，程序负责执行与把关；交付最小工具调用闭环
- 实际完成：新增 `lesson04` 十四个主类、两个测试类（17 个测试）、`lessons/04-tool-calling.md` 文档；未改动第 1–3 课源码（保持「第 1 课一行未改」）
- 核心设计一：`prepare`/`invoke` 分离 —— `prepare` 查工具、解析参数、跑校验（零副作用），`invoke` 是全类唯一产生副作用的地方，两者之间就是人工确认的插入点
- 核心设计二：工具失败是返回值不是异常 —— 模型是结果消费者，把「设备不存在，当前是 …」回传，模型下一轮能自己改；只有编程错误（context 为 null）和 handler 意外（NPE）才用异常
- 核心设计三：破坏性工具不执行 —— `ToolEffect.DESTRUCTIVE` 由程序侧枚举声明，绝不交给模型判断（提示词注入能让模型自我批准删除）；只回传「等待确认」让模型转述
- 核心设计四：结果以 TOOL 角色回传并带原始 `tool_call_id` —— 模型靠 id 配对，自己造或写错字符就会张冠李戴
- 教学桥：`ToolCallCodec` 用 content 承载工具调用，磁盘不破坏第 1 课的消息类型；文档明确标注这是教学策略，生产走协议原生 `tool_calls` 字段，最终要删
- 测试产出：`ToolRegistryTest` 12 个（注册校验、prepare 零副作用、四种失败、invoke 短路、异常兜底）、`ToolCallingServiceTest` 5 个（一次往返、破坏性不执行、幻觉恢复、轮数上限、截断），共 17 个全绿，全部离线
- 端到端验证：`ToolCallingDemo` 五个场景按预期输出，含「破坏性工具等待确认」和「轮数上限打断死循环」两个关键控制
- 待学习者验收：口头回答第 4 课 5 道面试题，重点是「为什么 prepare 和 invoke 必须分开」和「副作用等级为什么必须在程序侧声明」
- 下一次主任务：**补齐最小评估集**（贯穿项连续两课欠账），然后进入阶段 7 手写 Agent Loop

### 2026-08-28（贯穿项：最小评估集）

- 本次目标：补齐连续两课欠账的贯穿项 —— 最小评估集
- 实现：`learn.agent.eval.MinimalEvaluationSetTest`，单一 `@Test` 逐行跑 7 个场景（3 行 Structured Output + 4 行 Tool Calling），逐行收集失败而非遇错即停
- 姿态：不做静态表格，做成可执行断言 —— 改完代码 `mvn -o test` 直接得到「哪几行坏、坏在哪」，这才符合贯穿项「改完先跑评估」的要求
- 覆盖：合法 create 通过、不存在的设备被拦、受保护删除被拦；一次完整工具往返、破坏性工具不执行、模型幻觉恢复、轮数上限打断
- 验证：`mvn -o test -Dtest=MinimalEvaluationSetTest` BUILD SUCCESS；全量 llm-client 150 测试（唯一 error 仍是既有 HttpModelClientTest PKIX 网络抖动）
- 待学习者验收：口头说明「为什么评估集用可执行断言而不是静态表格」
- 下一次主任务：阶段 7 手写 Agent Loop，并顺手补 Trace/结构化日志

### 2026-08-28（阶段 7：手写 Agent Loop 与工具边界 + 贯穿项 Trace）

- 本次目标：把第 4 课的循环重写成有完整边界和可观测性的 Loop，同时补齐贯穿项「Trace 与结构化日志」
- 先做的判断：阶段 7 七项要求里，最大轮次/白名单/参数校验/异常回传第 4 课已有，**真正新增的只有三项** —— 工具超时、重复 tool call 幂等、trace id 与每轮日志。所以 `lesson05` 是复用 `lesson04` 的注册表和消息类型，不重写一遍
- 核心变化一：`run` 返回 `AgentTrace` 而不是 `String`。第 4 课的字符串返回值答不了「为什么停、跑了几轮、花了多少 token」，调用方只能去正则匹配模型说的话；现在停止原因是 `StopReason` 枚举，一个 if 就能判断是否异常收尾
- 核心变化二：Trace 做成**可断言的内存对象**，不是日志行。仓库里没有任何日志框架且构建离线，加 slf4j 不是选项；做成 `RoundTrace`/`AgentTrace` 后测试能直接断言「第 2 轮调了 create_device、因为 X 停止」，`toLogLine()` 又能随时输出成 `key=value` 的结构化行
- 核心变化三：四道边界按固定顺序 —— prepare（白名单+解析+校验，零副作用）→ 破坏性闸门 → 幂等缓存 → 超时执行。破坏性闸门刻意放在缓存**之前**，因为「没有执行」这件事不需要缓存
- 超时的诚实表述：`future.cancel(true)` 只发中断信号，不理中断标志的工具会继续跑完。所以 `tool_timeout` 的含义是「我放弃等待了」，不是「已取消」；这道闸门是最后一道防线，工具自己也该有超时
- 幂等键 = 工具名 + 原始参数串，**故意不含 `tool_call_id`**（每次都不同，算进去就永远命中不了）；失败结果不缓存，否则一次偶发超时会在整个会话里变成永久失败。已知限制：字面量比较，`{"a":1,"b":2}` 和 `{"b":2,"a":1}` 算两个键
- 顺手第二次应用第 1 课的接口隔离思路：`TraceIdGenerator` 把随机性隔离到接口后，测试用 `fixed("trace-1")` 断言精确的 trace id（第 1 课隔离的是网络，这次隔离的是随机数）
- 代码产出：`lesson05` 八个主类（`AgentLoop`、`AgentTrace`、`RoundTrace`、`StopReason`、`ToolCallMemo`、`ToolTimeoutGuard`、`TraceIdGenerator`、`AgentLoopDemo`）
- 测试产出：`AgentLoopTest` 10 个 + `ToolCallMemoTest` 5 个，共 15 个全绿全离线；覆盖超时、幂等、五种停止原因和每轮 trace 字段
- 端到端验证：`AgentLoopDemo` 五个场景输出正确，含「工具卡住超时后放弃等待」和「模型请求 2 次但 handler 只执行 1 次」
- 全量：165 个测试，唯一 error 仍是既有 `HttpModelClientTest` 真实调用的 PKIX 证书问题（本机网络环境，与本次改动无关）
- 待学习者验收：口头回答「谁决定调工具、谁真正执行、结果如何回到模型、什么时候结束」，以及「幂等键为什么不能包含 tool_call_id」
- 下一次主任务：**阶段 8 权限、Hook 与安全边界**（把第 4/5 课那道硬编码的破坏性闸门换成可配置的四态权限决定 + 审计记录）

### 本期记录：阶段 8 前半（第 6 课 权限策略）

- 拆课决定：阶段 8 拆成第 6 课（权限）+ 第 7 课（Hook），沿用 `c6db8ce` 按主题拆课的先例。两半的合并优先级不同，硬塞一课会让两套优先级互相污染
- 完成标准已达成：`GuardedAgentLoop` + 注入的 `PermissionPolicy` 给 `delete_device` 加上「必须人工确认」，`lesson05.AgentLoop` **一个字节都没改**。由 `shouldAddConfirmationPolicyWithoutTouchingLoop` 和演示场景三证明（同一份 Loop 代码，拒绝时 handler 执行 0 次、批准时 1 次，两种都留下审计记录）
- 四态不是三态：`allow | deny | ask | passthrough`。`ALLOW`/`DENY` 是唯一允许离开策略的值，`ASK`/`PASSTHROUGH` 是中间态，`isFinal()` 就是这条边界
- 归约不用 `max`/`Comparator`：`strongest()` 是按 `{DENY, ASK, ALLOW}` 显式扫三遍。**绝不用 `ordinal()`** —— 那把优先级绑在枚举声明顺序上，同级冲突还必须取列表里最靠前的候选，`max` 给不出这个保证。`passthrough` 候选直接不参与投票（弃权不是票）
- 候选收集顺序固定：硬边界 → 破坏性默认 → Hook 建议 → 规则（注册顺序）
- `passthrough` 归一为 **allow** 不是 deny：否则每加一个新工具都得先补一条规则才能用
- ask 五路 fail-closed：无审批器 / 审批器抛异常 / 返回 null / 返回 ask / 返回 passthrough，全部落到 deny
- 硬边界拒绝**不可上诉** —— 审批器连问都不问。Java 侧域重映射：原教材那条 workspace 路径边界换成 `SceneSnapshot.isProtected(deviceId)`，因为 `ToolEffect` 只有 READ/WRITE/DESTRUCTIVE，没有 execute，路径在这个域里没有对应物。这次域重映射已升级成全局决策，写进 `agent-engineer-roadmap.md` 的「Java 复刻的域约定」
- 审计是**闸门不是日志**：`record()` 抛异常 → `decide()` 抛异常 → Loop 转成 `permission_evaluation_error` → handler 不执行。吞掉异常会造成「副作用已发生却无记录」，比操作失败严重得多。每次 `decide()` 恰好一条记录，写在最终决定之后，所以审计里只有 allow/deny
- 裁决必须排在**幂等缓存之前**：反过来的话，一次被批准的调用会绕过后续全部裁决，权限只在首次调用生效
- 规则谓词抛异常 → 按那条规则的名字 deny。捕获 `Throwable` 而不是 `RuntimeException`：自递归匹配器抛的是 `StackOverflowError`，漏出去就既没有 deny **也没有审计记录**，正是审计要防的那种状态
- 值类全部 `final`：非 final 的 `PermissionDecision` 允许审批器返回一个子类，在 `isFinal()` 检查时报 DENY、检查过后报 ALLOW，这是个 TOCTOU 缺口
- 如实记下的设计债：第 5 课 `executeWithBoundaries` 是私有方法、`AgentTrace.addRound`/`finish` 是**包私有**，所以本课复用不了，只能新写 `GuardedTrace` 并重写循环骨架。包私有是**包**边界不是类边界 —— 换个包就够不着。没有回头给第 5 课加 `ToolGate` 抽象：那层抽象要见过第二个用例才讲得清，选择保留重复、把代价写进注释
- 代码产出：`lesson06` 八个权限类 + `GuardedTrace` + `GuardedAgentLoop` + `PermissionDemo`
- 测试产出：`PermissionPolicyTest` 26 个 + `GuardedAgentLoopTest` 10 个，共 36 个全绿全离线
- 全量：195 个测试 0 失败 0 错误，排除的 3 个是既有 `HttpModelClientTest` 真实网络调用（本机 PKIX 证书问题，与本次改动无关）
- 待学习者验收：`lessons/06-permissions.md` 的 6 道验收题，重点是第 2 题（换成 `ordinal()` 版会挂哪两个测试）和第 5 题（忽略审计异常后系统进入什么状态）
- 下一次主任务：**阶段 8 第 7 课 Hook 生命周期**

### 本期记录：阶段 8 后半（第 7 课 Hook 生命周期）—— 阶段 8 完成

- 阶段 8 到此完整交付：第 6 课权限 + 第 7 课 Hook，`lesson06` 36 个测试 + `lesson07` 33 个测试
- 只有四个事件：UserPromptSubmit、PreToolUse、PostToolUse、Stop。链路是 `prepare → Pre → 权限裁决 → 幂等缓存 → 限时执行 → Post`
- **权限裁决排在 Pre 之后、执行之前**：Hook 能在裁决前改参数，但改完还得过裁决。Hook 的权限意见只生成**候选**（`source=pre-tool-hook`），最终决定权仍在策略手里 —— `shouldKeepHardBoundaryAboveHookAllow` 证明 Hook 说 allow 也翻不动受保护设备
- 两套优先级阶梯**刻意不共用**：策略归约是三级（passthrough 弃权、不计票），Hook 合并是四级（`passthrough:0, allow:1, ask:2, deny:3`）。合并要的是「多个 Hook 里最严的那个」，弃权在这里必须是可比较的最低档
- `updatedInput` 三道锁，威胁模型是「批准 A、执行 B」：① 保留 `tool_call_id` ② 保留工具名 ③ **definition 必须是同一个对象**，用 `!=` 判引用不是 `equals` —— `ToolDefinition` 没重写 equals，而「就是注册表里那一个」本来只有引用相等能表达。过锁之后**重跑参数校验**（Hook 改的参数不比模型给的更可信），再**新构造**一个 `PreparedToolCall` 返回，和 Hook 手里那份引用彻底断开
- 异常走向**故意不对称**：UserPromptSubmit 和 Stop 的异常**不捕获**，直接终止整次运行（这两步失败意味着输入还没成形 / 结局还没定）；PreToolUse、PostToolUse 的异常降级成工具错误，模型下一轮还能换做法。`hook_contract_error` 和 `hook_execution_error` 分成两个错误码：前者是 Hook 写错了，后者是 Hook 跑挂了，排查方向完全不同
- PostToolUse 挂掉要**如实回传**「工具已执行但结果未能处理」：副作用已经发生，不能假装什么都没跑
- 三条消息角色约束，每条都对应一个伪造手段：`additionalContext` 只收 SYSTEM（Hook 不能冒充用户）、`forceContinue` 只收 USER（模型不会答一条 system 消息）、`blockingError` 必须是错误态（否则 Hook 能伪造一次「执行成功了」而工具压根没跑）
- `stopHookActive` 让无限续写**在机制上不可能**：注册表直接吞掉第二次 `forceContinue`，不靠 Hook 自律。`additionalContext` 保留 —— 它只是说明文字，无害
- Builder 在 setter 里校验而不是 `build()` 里：报错要指向写错的那一行
- `validateFor` 在归一化**之前**跑：一个 Stop Hook 返回 `updatedInput` 是写错了，不该被静默忽略
- 串行执行、逐个重新构造上下文：第二个 Hook 看到的是第一个改过之后的状态，不是模型最初那份。`blockingError` 或 `forceContinue` 一出现就短路，后面的 Hook 不再跑
- 上一课的结论这次用上了：`GuardedTrace.addRound`/`addDecision`/`finish` 由包私有**改成 public**。第 6 课刚写下「希望被下游扩展的类，写入口不能停在包私有」，第 7 课就是那个下游 —— 不改就得连犯两次同样的错误（第三个一模一样的轨迹类）。代价也写进注释了：写入口公开后，任何拿到 trace 的人都能往里塞记录，轨迹不再只由循环写
- 代码产出：`lesson07` 的 `HookEvent`、`HookContext`、`HookResult`、`HookCallback`、`HookRegistry`、`HookContractException`、`HookedAgentLoop`、`HookDemo`
- 测试产出：`HookRegistryTest` 19 个 + `HookedAgentLoopTest` 14 个，共 33 个全绿全离线。核心断言是 `顺序 == [user, pre, permission, handler, post, stop]`
- 评估集扩到 19 行（新增 4 行覆盖第 7 课：阶段顺序、契约锁拦下换工具名、Hook 建议翻不动硬边界、Stop 只能续一轮）
- 全量：234 个测试 0 失败 0 错误（本次 3 个真实网络测试也跑过了）
- 待学习者验收：`lessons/07-hooks.md` 的验收题，重点是第三道锁为什么用 `!=` 而不是 `equals`，以及 UserPromptSubmit/PreToolUse 的异常为什么走两条不同的路
- 下一次主任务：**阶段 9 上下文工程**（会话计划、上下文压缩、记忆机制）

### 本期记录：模块拆分 —— 目录编号与阶段编号对齐

- 起因：`05-llm-client` 一个模块装了四个阶段（第 1-2 课=阶段 5、第 3-4 课=阶段 6、第 5 课=阶段 7、第 6-7 课=阶段 8）。三份文档里 `05-llm-client/lesson06` 这类路径读起来像「阶段 5 的东西」，实际是阶段 8 的，找代码要先在脑子里做一次映射
- 为什么现在能拆：先做了前置审计 —— 依赖链是线性无环的（`01 → 03 → 04 → 05 → 06 → 07`，main 和 test 一致）；没有任何测试类 import 另一课的测试类，所以不需要 `test-jar`；两个待合并的包之间没有类名冲突
- 拆分结果：`05-llm-client`（client 包，第 1-2 课）、`06-structured-output`（structured）、`07-tool-calling`（tool）、`08-agent-loop`（loop）、`09-agent-guardrails`（permission + hook 两包）、`99-minimal-eval`（跨阶段评估集，必须是末端模块）
- `09` 保留两个包不再细拆：hook 依赖 permission 的裁决结果，拆开就要把裁决类型再暴露一层，而它们本来就同属阶段 8
- `99` 依赖全部上游，所以**不能被任何模块依赖**，编号用 99 而不是 10，避免以后阶段 10 撞号
- 全部用 `git mv` 移动，保留文件历史；合并第 1-2 课时清掉 38 个变成同包的冗余 import
- 验证：拆分前后都是 **234 个测试**，6 个模块全绿。数目不变是这次改动「只搬位置不改逻辑」的证据
- 顺手修的文档债：3 条 `java -cp` 命令原先只写自己模块的 `target/classes`，拆分后上游类不在路径里，跑 demo 会 `NoClassDefFoundError`；`09` 两篇文档的文件表还写着 `lesson06/`、`lesson07/`
- 离线环境注意：`mvn -o install` 装不了（`maven-install-plugin:3.1.2` 及其几个依赖不在本地仓库），但 `mvn -o test` 可以 —— reactor 直接从兄弟模块的 `target/classes` 解析依赖，不需要先 install
- 回滚点：拆分前打了 tag `pre-module-split`
- 下一次主任务不变：**阶段 9 上下文工程**（会话计划、上下文压缩、记忆机制）

### 本期记录：阶段 9 第 1 课（会话计划与陈旧提醒）

- 本次目标：阶段 9 开篇。让 Agent 在长任务里不忘记自己要干什么 —— 会话计划快照 + 陈旧提醒
- 新模块 `10-context-engineering`，包名 `learn.agent.llm.plan`。依赖链延长成 `05 → 06 → 07 → 08 → 09 → 10 → 99`，`99` 仍在最末端
- **没有再写第四个循环骨架。** 第 6 课那笔设计债（`GuardedTrace` 之后又抄一遍循环）本来要在这里第三次发生，这次改成复用阶段 8 的 Hook 扩展点：`PlanReminderHook` 注册在 `POST_TOOL_USE` 上，循环一行未改。这是阶段 8 那套扩展点第一次被下游真正消费，也算对它的一次验收
- 核心设计一：**只收完整快照，不提供 `todo_update(index, status)`**。增量的代价是模型得记住下标，而它记不住 —— 猜错下标会把「补测试」标成完成，而实际完成的是「接设备」，这种错不报错，只是静默脱节。完整快照强迫模型每次重读整个计划，这个「重读」本身就是对抗遗忘的机制，不是副作用
- 核心设计二：**三态封死**（`pending`/`in_progress`/`completed`）。加 `blocked`/`deferred` 会让计划从进度记录退化成借口清单 —— 模型会把「我不想做」写成 `deferred`。三态保证每项只能回答一个问题：做完了没有
- 核心设计三：**提醒是请求级临时消息，读取即清零**。`beforeModel()` 有副作用、不是纯查询。写进历史的话，跑三十轮会攒下十条一模一样的「保持计划更新」，每轮都为它付 token，还污染了可回放的历史（那些话没有任何人说过）
- 核心设计四：`todo_write` 是 **WRITE 不是 DESTRUCTIVE**。副作用等级按撤销的真实成本定，不按听起来危险不危险定。标 DESTRUCTIVE 会让模型每次更新计划都弹确认框，用户会直接关掉整个机制
- **本课最值得记的一个发现**：Hook 表达不了「请求级临时上下文」。它的 `additionalContext` 会被 append 进 messages，从此永久占预算 —— 也就是说走 Hook 这条路**做不出** `beforeModel()` 的语义。这不是取舍失误，是 Hook 的设计目标决定的：它的每种返回值（改参数、改结果、拦下、续写）都在**改变对话**，而提醒要的恰恰是「不改变对话，只影响下一次请求」，这在 Hook 的词汇表里没有对应物。正确的位置是一个「每次请求前被问一遍」的扩展点，也就是第 5 课的 Provider。两条路都留下了：`beforeModel()` 保住教材语义并有单测护住，Hook 版证明它接得进现有循环、同时暴露出现有循环缺什么
  - **【后续订正，2026-09-01】上面这个「发现」是错的，保留原文以记录当时的推理错误。** 教材在讲会话计划的同一章（`code/chapters/ch05/src/core/loop.ts`）本来就有 `toolRoundObserver` 扩展点，接口正是 `beforeModel()` + `recordToolRound()`，产出只拼进当次请求、不进历史。所以落差的真实原因不是「Hook 表达不了」，而是**我的循环少抄了这个扩展点**。当时只查了自己的三个循环、没回去读教材同章的 loop，就把「我的实现没有 X」写成了「教材没有 X」。另外 Provider 管的是系统提示组装，和这件事是两个不同的扩展点。已补 `ToolRoundObserver` 并让 `TodoTracker` 实现它
- 如实记下的第二个限制：`POST_TOOL_USE` 只在工具**真的执行了**之后触发，被权限拒绝／被 prepare 拦下／命中幂等缓存的轮次不计入陈旧计数。从「计划有没有推进」看这是对的，但和 `recordToolRound` 的字面语义有出入
- 代码产出：`TodoStatus`、`TodoItem`、`TodoWriteValidator`、`TodoTracker`、`PlanReminderHook`、`PlanDemo`
- 测试产出：`TodoTrackerTest` 25 个 + `PlanReminderHookTest` 10 个，共 35 个全绿全离线
- 评估集从 19 行扩到 23 行（完整快照可读回、增量补丁被拒、三轮未更新才提醒、写计划那轮重置计数）
- 全量：**292 个测试**，0 失败 0 错误，3 跳过（真实 Redis 缺 `REDIS_PASSWORD`）。另有 2 个既有的真实模型调用测试因本机 PKIX 证书问题失败，与本次改动无关，本次用 `-Dtest=!HttpModelClientTest#shouldCallRealModelWhenConfigured+shouldFailFastWithInvalidApiKey` 排除
- 端到端：`PlanDemo` 五个场景按预期输出，含「三处错误一次列全」和场景五那个「提醒被 append 进历史」的反面证据
- 过程中被编译器和测试抓到的三处问题（都是我自己写错，如实记）：
  1. 桥接类方法定义叫 `install`，7 处调用写的是 `registerOn` —— 又一次凭记忆写调用名，和第 3 课那次（`failure` vs `fail`）同一个毛病
  2. `TodoTracker` 的工具结果返回 `render()` 的中文文本，测试按 JSON 断言。**改的是实现不是测试** —— 教材 `ch05` 回传确定性 JSON 是对的：模型刚写进来的就是 JSON，回一份同构 JSON 它才能逐字段对比；回中文列表它得先在脑子里翻译一遍，那步翻译可能把差异抹掉。`render()` 保留给 demo 和日志，两个受众两种格式
  3. 评估集类注释写着「15 条基线用例」，实际早就 19 条、现在 23 条 —— 注释里写死数字必然过期，已改成不写死
- 环境记录：WSL 侧没有 Linux JDK，Maven 必须走 `powershell.exe` 调 Windows 的 JDK 17；Windows 控制台输出是 UTF-16 且中文在管道里会乱码，看失败详情要先 `iconv -f UTF-16LE` 转码
- 待学习者验收：`lessons/01-session-plan.md` 的验收题，重点是第 1 题（为什么不提供增量接口）和最后一题（为什么提醒不能写进历史 / Hook 为什么表达不了它）
- 下一次主任务：**阶段 9 第 2 课 子 Agent**（`code/chapters/ch06`）—— 隔离历史、共享运行边界、禁止递归委派、限制轮数

### 本期记录：阶段 9 第 2 课（子 Agent）

- 本次目标：第 1 课让主 Agent 记住要干什么，但没减少**探索过程本身**的上下文。本课把一段多轮探索挪出主对话：派一个隔离的子 Agent 去查，主 Agent 只收一句有证据的结论
- **开局状态：上期留下的代码是半成品，编译不过。** 本期第一件事是修它，不是从零写。`SubagentTool`/`SubagentConfig`/两个工厂接口和 13 个测试都已存在，但 `mvn test-compile` 挂在两处：
  1. 测试调 `new SubagentTool(config)`，主类要 `(model, config, traceIdGenerator)` 三个参数
  2. 测试的 `AuditSink` 实现了 `record(decision)`，接口是 `record(request, decision)`
- **两处都改的是主类/测试签名，不是绕过。** 第 1 处选择「让 config 吃下 model 和 traceIdGenerator」而不是「让测试传三个参数」：委派需要的全部信息应当在一个对象里，否则会出现「模型名从构造参数来、工具从 config 来」的两个来源。第 2 处是测试写错了上游接口，改测试
- 核心设计一：**隔离的只有消息历史**。父子共享同一个 JVM、同一个 `ToolContext`（同一身份、同一场景）、同一组 Hook、同一份权限策略，子 Agent 的副作用**会保留**。它不是沙箱 —— 这是本课最危险的误读，README 和文档都写明了
- 核心设计二：**权限必须共享，而且不能更宽**。否则 `task` 就是提权路径：父 Agent 删不掉受保护设备，但它可以派个子 Agent 去删。提示词注入的标准手法正是「换个身份再试一次」。`shouldShareParentPermissionPolicy` 用「父策略 DENY inspect → 子 Agent 的 handler 一次没执行 + 留下审计」把这条钉住
- 核心设计三：**依赖用工厂，不用实例**。历史隔离靠新建循环，依赖隔离靠工厂，少任何一半子 Agent 都不是真的从零开始。共享一个 `FakeModelClient` 时第二次委派会接着读第一次剩下的响应队列；生产里共享的是连接状态、重试计数、熔断器状态，问题一模一样
- 核心设计四：**递归委派两道防线，真正生效的是第二道**。提示词里「不要再委派」是软约束，模型可以不听；子 Agent 的注册表里根本没有 `task` 才是硬的。另加一道**针对开发者**的检查：`toolsFactory` 返回的注册表若含 `task` 直接报配置错误 —— 最可能打开这个洞的不是模型，是图省事直接返回父注册表的人
- 核心设计五：**`hooks` 不许传 null，`policy` 允许**。两个都是治理边界，但「没配」的含义不同：`policy` 为 null 是明确的「本次不启用权限系统」，而 `hooks` 为 null 读起来像「子 Agent 不受 Hook 管」，恰好是本课要否定的那句话。没有 Hook 时传空注册表 —— 「受管但当前无规则」和「不受管」是两件事
- 核心设计六：**失败只回结构化错误码，不回子 Agent 最后一条工具结果**。轮数耗尽时最后一条工具结果通常看着像个正常答案，回传它父 Agent 会以为子任务成功了。异常文本也不回传：里面可能有路径、SQL、配置键名，进了父上下文就等于进了模型可见范围
- **Java 特有的一笔（教材没有）**：`HookedAgentLoop` 内部的 `ToolTimeoutGuard` 持有线程池，`runTask` 的 `finally` 里必须 `shutdown()`。不写就是**每次委派泄漏一个线程池**。教材是 Node 单线程模型，照抄会漏掉这一句
- 代码产出：`ModelClientFactory`、`ToolRegistryFactory`、`SubagentConfig`、`SubagentTool`（本期修复至可编译可运行），文档 `lessons/02-subagent.md`
- 测试产出：`SubagentToolTest` 13 个全绿全离线；模块累计 48 个（tracker 25 + hook 桥接 10 + 子 Agent 13）
- 评估集从 23 行扩到 26 行（只回结论不漏中间轨迹、父策略对子 Agent 生效、递归委派被拦）
- 全量：**311 个测试**，0 失败 0 错误，3 跳过（真实 Redis 缺 `REDIS_PASSWORD`）。上期那个 PKIX 证书问题这次没出现，两个真实模型调用测试**不加任何排除**跑过了
- 这个数字我第一次记错了，记的是 309。原因是我把上期那条 `-Dtest=!HttpModelClientTest#...` 排除参数顺手带进了本次全量验证 —— 上期加它是为了绕开 PKIX 证书失败，本次证书问题已经没有了，参数却还在。于是那两个真实模型测试根本没跑，而我在记录里写成了「本次真实模型调用测试也通过了」。查 `surefire-reports` 的 XML（`tests="4" skipped="0"`）才发现它们不在本次运行里。**教训：「通过」和「没跑」在控制台摘要里长得一样，声称某个测试通过之前要确认它真的在运行列表里**，而不是只看 BUILD SUCCESS
- **本课没有 demo。** 第 1 课有 `PlanDemo` 五场景，本课只有单测。`PlanDemo` 里没加子 Agent 场景，文档也没声称有 —— 如实记，想补的话是下次的小任务
- 过程中的两个记录：
  1. 又一次「注释里写死数字」：评估集类注释写着「23 条基线用例」。上期已经因为同样的问题改过一次（15 → 19 → 23），当时的结论就是「不写死」，但那次只改了一处措辞、没把数字彻底删掉。这次直接删掉数字，改成「全部通过」
  2. PowerShell 下 `-Dsurefire.failIfNoSpecifiedTests=false` 必须整体加引号，否则参数在点号处被切断，Maven 报「Unknown lifecycle phase .failIfNoSpecifiedTests=false」
- 待学习者验收：`lessons/02-subagent.md` 的 7 道验收题，重点是第 1 题（隔离了什么、没隔离什么，为什么不是沙箱）、第 5 题（递归委派哪道防线真正生效）和第 7 题（`shutdown()` 不写会怎样）
- 下一次主任务：**阶段 9 第 3 课 产物落盘与上下文压缩**（`code/chapters/ch08`、`ch09`）—— 工具结果写文件、分层裁剪、压缩时不能丢审计记录

### 本期记录：对着教材做重构检查，修掉一个安全回归

- 本次目标不是新交付，是**拿教材当基准审自己已写的代码**。派了五条并行核查线（文档真实性、章节映射、ch01-04 对照、重构健康度、ch05-06 对照）
- **最重要的发现是一个安全回归**：`HookedAgentLoop` 复制骨架时整块漏掉了破坏性闸门（连 `ToolEffect` 都不在 import 列表里）。不配策略时 `delete_device` 直接落副作用 —— 也就是说「接了 Hook 和权限的循环」防护**比最原始的 `AgentLoop` 还弱**，而恰恰是这种循环最容易让人以为更强。三个循环各自的单测都是绿的，因为**没有任何测试同时看着三份**
- 这个回归我没只靠读代码断言，写了两个探针实测：同一个 `delete_device` 喂给两个循环，`AgentLoop` 给 `blocked_destructive`／副作用 `[]`，`HookedAgentLoop` 给 `executed`／副作用 `[DELETED]`。修完再跑，两边都拦住
- 修复清单：破坏性兜底闸门；`SubagentConfig` 的 `policy` 改必填（null 会让循环整段跳过裁决，是 `task` 变提权路径的缝）；Stop Hook 续写时丢模型答复；幂等键与有效参数错位（改 `HookRegistry` 让 `call` 和 `arguments` 同源）；`todo_write` 拒绝未知字段
- **补了 `ToolRoundObserver` 扩展点，并订正了上期一条错误结论。** 详见上一期记录里那条「后续订正」。教训单独记：**断言「教材没有某个机制」之前，必须回去读教材同章的 `core/loop.ts`。**「我的实现没有 X」和「教材没有 X」是两件事，我把后者写成了前者
- 新增防漂移测试 `LoopBehaviorParityTest`：三个循环跑同一组不变量（破坏性不执行、只读放行、白名单拦截）。破坏性那条的结局标签三份不同（`blocked_destructive` vs `permission_denied`），所以断言的是「handler 没执行」这个真正通用的不变量，不假装三份实现相同
- **两个测试都做了变异验证**，因为「修好后通过」证明不了测试有效：把闸门改成 `false &&`、把 guidance 改成 append 进历史，各跑一次，确认对应那一条立刻挂、其余仍绿（说明断言精准而非笼统）。验完撤销并 grep 确认无残留
- 评估集从 26 行扩到 29 行（无策略破坏性不执行、提醒不进历史、`todo_write` 拒未知字段）
- 全量 **327 个测试**，0 失败 0 错误，3 跳过（真实 Redis 缺 `REDIS_PASSWORD`）。两个真实模型调用测试因本机 PKIX 证书问题排除，**它们没有跑，不是通过了**
- 路线图两处结构性修正：ch07（Skill 按需加载）从阶段 10 挪进阶段 9 作第 3 课 —— 教材 `ch10` 的动态 Prompt 直接 `import SkillRegistry`，原顺序会让第 6 课缺前置；域重映射从阶段 8 的局部说明升级为 roadmap 的「Java 复刻的域约定」全局小节，写明进入第 4/5 课前必须二选一
- 过程中的三个坑，如实记：
  1. **和子代理撞车**：我的测试文件被并行子代理的探针覆盖丢失，重建时才发现。同一工作区并行写文件有风险
  2. `sed` 漏了**跨行**的构造调用（`SubagentToolTest:314` 的 `hooks, null`），跑测试才暴露。批量替换后必须跑测试，不能只看 grep 计数
  3. **总数算错**：把 327 加成了 325，还写进了文档和 commit message。逐模块数字都对，是相加错了 —— 报数字之前要么用工具核，要么算两遍
- 另一件如实记的事：修复当时我只加了 `ToolRoundObserver` 接口并接进循环，**没让任何生产类实现它**（`TodoTracker` 缺 `implements`、`PlanDemo` 仍走 Hook），而文档已经写成「缺口已补上」。这是过早声称完成。本期后半补齐：`TodoTracker implements ToolRoundObserver`，`PlanDemo` 场景五改成两条路径正面对比，跑出来 Hook 路径累计 5 次提醒、观察器 2 次
- 下一次主任务不变：**阶段 9 第 3 课 Skill 按需加载**（`code/chapters/ch07`）
