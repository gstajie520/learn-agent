# 上下文工程学习目录

阶段 9。前面八个阶段问的是「这一轮怎么跑对」，本模块问的是**「跑了二十轮之后，它还记得自己要干什么吗」**。

长任务失败通常不是模型不够聪明，是上下文管理失控。这一阶段解决「Agent 工作时间怎么变长」。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 状态 |
|---|---|---|---|---|
| 1 | 会话计划：完整快照、状态校验、陈旧提醒 | [01-session-plan.md](lessons/01-session-plan.md) | `learn.agent.llm.plan` | 已完成 |
| 2 | 子 Agent：隔离历史、共享运行边界、禁止递归委派 | [02-subagent.md](lessons/02-subagent.md) | `learn.agent.llm.plan` | 已完成 |
| 3 | Skill 按需加载：先扫描摘要、再按名称加载正文 | — | — | 未开始 |
| 4 | 产物落盘与上下文压缩：结果写文件、分层裁剪 | — | — | 未开始 |
| 5 | 文件记忆：跨会话提取、整理与检索 | — | — | 未开始 |
| 6 | 动态 Prompt 组装：Provider 按固定顺序生成运行态系统提示 | — | — | 未开始 |

对应教程章节：`code/chapters/ch05`、`ch06`、`ch07`、`ch08`、`ch09`、`ch10`。

Skill 按需加载（第 3 课）从原阶段 10 挪进这里，原因是教材 ch10 的动态 Prompt
直接 import `SkillRegistry` —— 学第 6 课之前必须先有第 3 课。它和阶段 10 的 RAG
是同一条问题的两条路：Skill 是「少拿」（本地知识按名称进入上下文），RAG 是「去找」
（外部知识按相似度召回）。教材里只实现了一条（ch07），另一条要自写。

## 第 1 课的三条核心规则

```text
只接受完整快照        不提供 todo_update(index, status)
                     增量要求模型记住下标，而它记不住
三个状态             pending / in_progress / completed
                     加 blocked、deferred 会让计划退化成借口清单
提醒是请求级临时消息    只拼进这一次请求，不写进历史
                     写进历史 = 每轮重复付 token + 污染可回放记录
```

## 第 2 课的三条核心规则

```text
隔离的只有消息历史      父子共享 JVM、ToolContext、Hook、权限策略
                     子 Agent 不是沙箱，把它当沙箱是最危险的误读
权限必须共享          否则 task 就是提权路径：把想做的事包装成一次委派
                     即可绕过全部裁决 —— 提示词注入正是这么找缺口的
只回结论，不回轨迹      轮数耗尽时尤其不能回最后一条工具结果
                     那看着像答案，父 Agent 分辨不出「没做完」
```

## 两课的关系

第 1 课让主 Agent 记住要干什么，但没减少**探索过程本身**的上下文。第 2 课把探索挪出主对话：派一个从零开始的子 Agent 去查，主 Agent 只收一句有证据的结论，中间三十轮读文件记录随子 Agent 一起消失。

一句话：第 1 课防遗忘，第 2 课防膨胀。

## 复用了阶段 8 的什么

`PlanReminderHook` 注册在 `PostToolUse` 上，**没有给循环加一行代码**。这是阶段 8 那套 Hook 扩展点第一次被下游真正复用 —— 也就是说不需要第四个循环骨架。

前三个阶段各写了一个循环（`AgentLoop`、`GuardedAgentLoop`、`HookedAgentLoop`），阶段 8 的笔记里把这个重复记成了设计债。本课的结论是：**这笔债不用还了**，Hook 这个扩展点已经够用。

## 但它暴露了一个缺口

Hook 注入的 `additionalContext` 会被 append 进 messages，而提醒要的是「只影响下一次请求，不进历史」。两者**不等价**：

| 路径 | 提醒去哪了 | 代价 |
|---|---|---|
| `TodoTracker.beforeModel()` | 只拼进这一次请求 | 阶段 8 的循环没有这个扩展点，用不上 |
| `PlanReminderHook` | append 进 messages | 每轮重复付 token，历史里多了没人说过的话 |

**这不是取舍失误，是一个发现。** Hook 的设计目标是「改变对话」；提醒要的恰恰是「不改变对话」。这在 Hook 的词汇表里没有对应物。

正确的位置是「每次请求前被问一遍，产出临时上下文」的扩展点 —— 也就是本阶段第 5 课的 Provider。本课两条路都留着：`beforeModel()` 保住教材语义并有单测护住，Hook 证明它接得进现有循环、也证明现有循环缺什么。

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 10-context-engineering -am test
```

`-am` 会连带跑上游模块的测试，控制台总数比本模块大得多。本模块自己有 48 个测试
（tracker 25 + hook 桥接 10 + 子 Agent 13），全部离线；只想看这些，加 `-Dtest=` 指定测试类。

跑 demo：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
mvn -o -pl 10-context-engineering -am package -DskipTests
java "-Dfile.encoding=UTF-8" -cp '10-context-engineering/target/classes;10-context-engineering/target/dependency/*' learn.agent.llm.plan.PlanDemo
```

## 依赖

依赖 05、06、07、08、09 五个模块。配置见 [05-llm-client](../05-llm-client/README.md)。

依赖 09 的两个理由：第 1 课的提醒注入复用它的 Hook 扩展点，第 2 课直接把它的 `HookedAgentLoop` 当作子 Agent 的循环体 —— 子 Agent 要享受同一套权限裁决和 Hook，所以复用那个「最全」的循环，而不是退回 `AgentLoop`。

## 边界说明

- **子 Agent 不是沙箱**。隔离的只有消息历史。父子共享 JVM、`ToolContext`（同一身份、同一场景）、Hook 和权限策略，子 Agent 写下的副作用会保留。当沙箱用是第 2 课最危险的误读；
- **子 Agent 的历史隔离靠新建循环，依赖隔离靠工厂**。`ModelClientFactory`/`ToolRegistryFactory` 收的是工厂不是实例，否则两次委派共享同一个客户端，响应队列和重试计数互相污染；
- **`SubagentConfig` 的 hooks 不许传 null，policy 允许**。policy 为 null 是明确的「本次不启用权限系统」，hooks 为 null 读起来像「子 Agent 不受 Hook 管」—— 恰好是第 2 课要否定的那句话。没有 Hook 请传空注册表；
- **子 Agent 的轮数上限只能收紧不能放宽**。它是同步委派的成本闸门，能被调用方抬高的闸门等于不存在；
- **每次委派都要 `shutdown()` 子循环**。`HookedAgentLoop` 内部的 `ToolTimeoutGuard` 持有线程池，不关就是每次委派泄漏一个 —— 教材是 Node 单线程模型，照抄会漏掉这一句；
- **计划是会话级状态**，不跨会话。跨会话持久化是第 4 课的问题，混进来会让「计划属于谁」没法回答；
- **`todo_write` 是 WRITE 不是 DESTRUCTIVE**。副作用等级按撤销的真实成本定，不按听起来危险不危险定。标成 DESTRUCTIVE 会让模型每次更新计划都弹确认框，用户会直接关掉整个机制；
- **`beforeModel()` 有副作用**（读取即清零），不是纯查询。它属于一次请求的生命周期，不能随便多调；
- **`PostToolUse` 只在工具真的执行后触发**。被权限拒绝、被 prepare 拦下、命中幂等缓存的轮次不计入陈旧计数。从「计划有没有推进」看是对的，但和 `recordToolRound` 的字面语义有出入；
- 工具结果回传 **JSON**（给模型逐字段对比），`render()` 的中文文本只给 demo 和日志。两个受众，两种格式。
