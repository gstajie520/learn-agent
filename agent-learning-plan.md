# Agent 学习进度档案

> 当前路线：Java 后端 → Agent/LLM 应用后端。每次学习开始前读取，结束后更新。

## 学习者画像

- 目标岗位：Java Agent/LLM 应用后端工程师
- 当前优势：已有 Java 后端背景
- 当前短板：Java 基础、MQ、Redis
- 目标项目：`E:\cj\study\fw` 智能场景项目

## 总体路线

| 阶段 | 主题 | 状态 | 完成证据 |
|---|---|---|---|
| 1 | Java 基础与测试 | DONE | 状态机完整项目；8 个 JUnit 测试通过；已理解跨实例幂等边界 |
| 2 | Java 并发与线程池 | DONE | 6 个测试通过；已理解线程池、队列、拒绝策略、MQ ACK 和幂等边界 |
| 3 | Spring Boot 后端基础 | DONE | 3 个 API 测试通过；已掌握 Controller、Service、DTO、参数校验和统一异常 |
| 4 | Redis：状态、缓存、幂等 | IN_PROGRESS | 待把内存 ConcurrentHashMap 替换为共享 Redis 状态 |
| 5 | RabbitMQ：异步、确认、重试 | NOT_STARTED |  |
| 6 | Agent Loop 与结构化输出 | NOT_STARTED |  |
| 7 | LangGraph | NOT_STARTED |  |
| 8 | Java/Python 异步 Agent 系统 | NOT_STARTED |  |
| 9 | 安全、评估、可观测性与求职 | NOT_STARTED |  |

## 当前阶段

- 阶段：4：Redis：状态、缓存、幂等
- 本阶段目标：把 Spring Boot 中的命令状态从 JVM 内存迁移到共享 Redis，并实现幂等抢占
- 为什么现在学：MQ 消费者、Agent 推理和后台任务都不会阻塞 Web 请求线程
- 前置知识：阶段 1 状态机、异常、封装和 JUnit 测试
- 阶段状态：IN_PROGRESS
- 开始日期：2026-08-21
- 本阶段唯一主任务：用 Redis 保存 commandId 状态，并用原子条件更新防止重复消费
- 概念示例路径：待生成
- 完整代码路径：待生成
- 测试/验证命令：`Set-Location '.\learning\agent-java-learning'; $env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'; mvn -o test`
- 完成标准：能解释 Redis key、TTL、`SETNX`/条件更新和跨实例幂等，并有可运行测试

## 已完成内容

- 已确定学习方向：先 Java 基础，再 Redis/MQ，最后进入 Agent/LangGraph
- 已理解 Harness、Graph、MQ、Redis 在智能场景中的职责边界
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
- 根据学习反馈移除 `record`、自定义任务句柄和 CountDownLatch 测试，改为 Java 8 常见的 `Callable + Future + try/finally`

## 需要复习

- 主题：Harness 与 Graph 的区别
  - 复习原因：后续学习 LangGraph 时避免把业务状态机和 Agent 图混为一谈
  - 复习方式：用一句话解释“运行环境”和“流程编排”的区别
  - 验收问题：为什么智能场景需要 LangGraph + Java 业务状态机，而不是只用其中一个？
- 主题：RabbitMQ、Redis、WebSocket 的职责
  - 复习原因：进入 MQ/Redis 阶段前需要明确消息、状态和通知的边界
  - 复习方式：画出 Java → MQ → Python → MQ → Java 的时序
  - 验收问题：为什么 MQ 不能代替 Redis 保存当前命令状态？

## 下一阶段

- 阶段：2：Java 并发与线程池
- 主题：线程池、任务提交、超时、Future 和 CompletableFuture
- 进入条件：阶段 1 状态机测试全部通过，并能解释非法迁移和终态保护
- 预告产出：一个可超时、可取消、可观察的异步命令执行器

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
