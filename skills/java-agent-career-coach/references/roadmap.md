# Java 后端转 Agent 应用后端：12 周路线

## 使用方式

按阶段推进，不要求严格按周完成。每个阶段必须更新 `agent-learning-plan.md`，留下概念示例、完整可运行代码、测试结果和复盘。若用户时间不足，保留主任务，删除辅助阅读。

每个阶段的固定学习顺序：

```text
前置检查
  -> 概念示例（短代码 + 逐行解释）
  -> 完整小项目（源码 + 测试）
  -> 本地运行
  -> 故障分支练习
  -> 面试验收
  -> 更新进度档案
```

## 第 1-2 周：LLM 应用基础

掌握 Chat API、消息角色、Tool Calling、Structured Output、JSON Schema、Streaming、Token、上下文窗口、Embedding 和 RAG 基础。

概念示例：展示一次最小 Tool Calling 和严格 JSON 的消息结构。

完整代码：一个最小 Python 或 Java 示例，能让模型调用一个工具，并把结果转换为严格 JSON；加入参数错误和模型超时测试。

面试验证：解释“模型输出 JSON”与“业务操作合法”的区别。

## 第 3-4 周：手写 Agent Loop

不使用 LangGraph，完成：用户输入 → 模型 → 工具调用 → 工具执行 → 结果回填 → 再次推理 → 最终回答。

必须加入最大轮次、工具白名单、参数校验、工具异常回填、超时和空结果处理。

概念示例：用少量代码展示模型—工具—回填循环。

完整代码：有限轮次 Loop、单元测试、一次失败分支复盘。

## 第 5-6 周：LangGraph

学习 `StateGraph`、Typed State、Node、Edge、Conditional Edge、ToolNode、Checkpointer、Thread ID、Streaming、Interrupt/Resume。

概念示例：展示 State、Node 和条件边的最小图。

完整代码：一个“计划 → 审批 → 执行/拒绝”的小图；至少有一个条件分支和一个可恢复 checkpoint。

重点理解：图负责控制流，节点内部仍可能调用 Agent Loop；不要为了画图而把所有逻辑塞进一个巨大节点。

## 第 7-9 周：异步 Agent 后端

用 Java/Spring Boot 作为业务入口，用 Python/FastAPI 或现有 Agent 服务作为推理服务。

实现：HTTP 提交命令、RabbitMQ 任务/结果队列、Redis 状态、WebSocket 或轮询查询、ACK/NACK、有限重试、超时和 `command_id` 幂等。

推荐状态：`pending → running → preview/clarification → applied/failed/timeout/cancelled`。

概念示例：展示命令状态、消息和幂等键之间的关系。

完整代码：时序图、状态迁移图、重复消息测试和服务重启恢复说明。

## 第 10 周：安全与可靠性

补齐结构化输出校验、业务规则校验、权限、版本冲突、危险操作确认、审计日志、Prompt/Tool 注入防护、模型降级和错误分类。

产出：一条“模型输出不可直接落库”的完整防线；列出至少五种故障及处理策略。

## 第 11 周：评估与可观测性

记录 trace id、模型轮次、工具调用、token、延迟、重试和错误码。建立小型离线评估集，覆盖正常请求、歧义请求、非法操作、重复请求和边界数据。

产出：评估表、结构化日志样例、一次回归测试报告。

## 第 12 周：作品集与面试

整理 README、架构图、时序图、状态机、故障演练、测试命令和部署方式。准备 3 分钟项目介绍和 10 个追问的简洁回答。

项目描述模板：

> 面向 X 场景，使用 Y 让用户通过自然语言生成结构化领域操作；以 Z 校验、幂等和确认机制隔离模型不确定性；通过 MQ/Redis/状态机实现异步执行和恢复；用测试/评估验证成功率、延迟和失败分支。

## 每周复盘模板

```text
本周目标：
实际产出：
能用代码证明什么：
遇到的失败：
失败根因：
下一周唯一主目标：
```

## 优先级调整

- 如果 Java 基础薄弱：优先补并发、事务、MQ、Redis、网络和 Spring Boot，而不是继续堆 Agent 框架。
- 如果 Python 阅读困难：补类型标注、async/await、Pydantic、pytest 和 FastAPI，暂缓高级 Python 语法。
- 如果只会调 API：回到手写 Loop 和 Structured Output。
- 如果只会框架：脱离框架重写一个最小 Loop，并解释框架替你管理的状态和恢复。
- 如果项目已经有 LangGraph：优先做专用图、校验、幂等、评估和故障演练，而不是换框架。
