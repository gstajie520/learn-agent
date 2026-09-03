# 阶段参考：17 阶段路线摘要

> **本文件不是独立路线。** 唯一权威路线是仓库根目录的 `agent-engineer-roadmap.md`，
> 唯一进度档案是 `agent-learning-plan.md`。三份文件使用**同一套阶段编号**，
> 本文件只提供教练在对话中快速判断阶段位置所需的摘要。
>
> 编号或阶段划分变更时，必须同步修改这三份文件。

## 阶段编号速查

| 阶段 | 主题 | 对应章节教材 | 主要语言 |
|---:|---|---|---|
| 1 | Java 基础与测试 | — | Java |
| 2 | Java 并发与线程池 | — | Java |
| 3 | Spring Boot 后端基础 | — | Java |
| 4 | Redis：状态、缓存、幂等 | — | Java |
| 5 | LLM 调用基础 | ch01 | Python 先，Java 后 |
| 6 | Structured Output 与 Tool Calling | ch02 | Python 先，Java 后 |
| 7 | 手写 Agent Loop 与工具边界 | ch01、ch02 | TypeScript/Python 读，Java 重写 |
| 8 | 权限、Hook 与安全边界 | ch03、ch04 | 本仓库章节代码 |
| 9 | Java 并发深化 | — | Java（CompletableFuture、Reactor） |
| 10 | 上下文工程：计划、压缩、记忆、按需加载 | ch05、ch06、ch07、ch08、ch09、ch10 | 本仓库章节代码 |
| 11 | RAG 与向量检索 | —（需自写，教材无独立章节） | Python |
| 12 | API 韧性与任务系统 | ch11–ch14 | 本仓库章节代码 |
| 13 | LangGraph 状态与工作流 | — | Python |
| 14 | Java Agent 集成 | — | Java（Spring AI） |
| 15 | 分布式 Agent 后端 | — | Java |
| 16 | MCP、动态工具池与多 Agent | ch15–ch19 | 本仓库章节代码 |
| 17 | 综合项目、评估与求职 | ch20 + `fw` | Java + Python |

## 每阶段固定学习顺序

```text
前置检查
  -> 概念示例（短代码 + 逐行解释）
  -> 完整小项目（源码 + 测试）
  -> 本地运行
  -> 故障分支练习
  -> 面试验收
  -> 更新进度档案
```

## 主教材使用规则

阶段 7-12 和 16 以本仓库 20 章教程为主教材，不要绕过它去找外部资料：

- 文章：仓库根目录 `NN. <标题>（Agent架构实操NN）.md` 与对应 `（Python版）.md`
- TypeScript 代码：`code/chapters/chNN/src/` 与 `tests/`
- Python 代码：`python/chNN_agent/`

阅读方式：先读文章的“验收结果/问题本质”，再读组合根和工具 handler，然后运行该章测试观察分支，最后与上一章对比只找新增能力。

验证命令（TypeScript，从 `code/` 执行）：

```powershell
npm run typecheck
npm run test:chNN
```

验证命令（Python，从 `python/` 执行）：

```powershell
& .\.venv\Scripts\python.exe -m pytest '.\chNN_agent\tests'
```

不要把“文件存在”或“能导入”当作章节完成证明；只有直接运行测试通过才算通过。

## 贯穿项

这三项从指定阶段起每阶段增量维护，不允许推迟到阶段 16：

| 贯穿项 | 起始阶段 | 每阶段要做的事 |
|---|---:|---|
| 最小评估集 | 6 | 新增覆盖本阶段能力的用例；每次改动后重跑，作为回归基线 |
| Trace 与结构化日志 | 7 | 保证新增链路带 trace id；能按一次请求串起全过程 |
| 每章面试题 | 1 | 每课 README 末尾 3～5 道，含参考答案、项目解决方案、风险边界 |

## 语言顺序规则

阶段 5-6 先用 Python 读通一次模型调用，再用 Java 重写同一次调用。原因是一手文档、SDK 更新和社区示例都是 Python 优先，先在 Python 侧看清请求和响应的真实结构，Java 重写会快得多。

不要跳过 Python 直接写 Java；也不要停在 Python 不回到 Java，目标岗位是 Java 侧。

阶段 13 用 Python（LangGraph 生态和采用率明显高于 Java 图编排）。阶段 14-15 回到 Java。

## 优先级调整

- 如果 Java 基础薄弱：优先补并发、事务、MQ、Redis、Spring Boot，而不是继续堆 Agent 框架。
- 如果 Python 阅读困难：补类型标注、async/await、Pydantic、pytest，暂缓高级语法。
- 如果只会调 API：回到阶段 6-7，手写 Loop 和 Structured Output。
- 如果只会框架：脱离框架重写最小 Loop，并解释框架替你管理的状态和恢复。
- 如果同时想学 Spring AI、LangChain4j、Koog、Agents-Flex：只选 Spring AI 作为主线，其余只读设计。
- 如果项目已经有 LangGraph：优先做校验、幂等、评估和故障演练，而不是换框架。

## 每次复盘模板

```text
本次目标：
实际产出：
能用代码证明什么：
遇到的失败：
失败根因：
下一次唯一主目标：
```

## 项目描述模板

> 面向 X 场景，使用 Y 让用户通过自然语言生成结构化领域操作；以 Z 校验、幂等和确认机制隔离模型不确定性；通过 MQ/Redis/状态机实现异步执行和恢复；用测试/评估验证成功率、延迟和失败分支。
