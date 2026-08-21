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
| 2 | Java 并发与线程池 | IN_PROGRESS | 已掌握 Future 基础；正在学习线程数、任务队列和拒绝策略 |
| 3 | Spring Boot 后端基础 | NOT_STARTED |  |
| 4 | Redis：状态、缓存、幂等 | NOT_STARTED |  |
| 5 | RabbitMQ：异步、确认、重试 | NOT_STARTED |  |
| 6 | Agent Loop 与结构化输出 | NOT_STARTED |  |
| 7 | LangGraph | NOT_STARTED |  |
| 8 | Java/Python 异步 Agent 系统 | NOT_STARTED |  |
| 9 | 安全、评估、可观测性与求职 | NOT_STARTED |  |

## 当前阶段

- 阶段：2：Java 并发与线程池
- 本阶段目标：用 Java 实现可超时、可取消、可观察的异步命令执行器
- 为什么现在学：MQ 消费者、Agent 推理和后台任务都不会阻塞 Web 请求线程
- 前置知识：阶段 1 状态机、异常、封装和 JUnit 测试
- 阶段状态：IN_PROGRESS
- 开始日期：2026-08-21
- 本阶段唯一主任务：理解 `ThreadPoolExecutor` 的线程数、任务队列和拒绝策略，再进入 `CompletableFuture`
- 概念示例路径：`learning/java-async-command-executor/README.md`
- 完整代码路径：`learning/java-async-command-executor/src/main/java/learn/agent/async/`
- 测试/验证命令：`$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'; mvn -o test`
- 完成标准：能解释提交、结果、超时、取消、线程数、队列和拒绝策略；后续进入 `CompletableFuture`

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
- 下一次主任务：回答本课三个验收问题，再学习拒绝策略如何与 MQ ACK/NACK 配合
