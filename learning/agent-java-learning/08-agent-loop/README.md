# Agent Loop 学习目录

阶段 7。不引入新能力，只把 07 的工具调用变成可以放心跑的东西 —— 有上限、有超时、有去重、出问题能归因。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | 四道工具边界、超时、幂等、Trace 与停止原因 | [01-agent-loop.md](lessons/01-agent-loop.md) | `learn.agent.llm.loop` | `learn.agent.llm.loop` |

## 四道工具边界

```text
模型请求一次工具调用
  ↓ 1. prepare        查白名单 + 解析参数 + 校验      零副作用
  ↓ 2. 破坏性闸门      不可逆操作不执行，回传等待确认   排在缓存之前
  ↓ 3. 幂等缓存        同样的调用命中缓存，不重复执行   键不含 tool_call_id
  ↓ 4. 超时执行        唯一真正调 handler 的地方       结束等待，不保证结束执行
写入这一轮的 RoundTrace
```

顺序是设计的一部分：破坏性闸门在幂等缓存**之前**，因为「这次没有执行」不需要缓存。

每轮的处置写进 trace，六个 outcome 标签是完整分类：`rejected`、`blocked_destructive`、`deduplicated`、`executed`、`failed`、`protocol_violation`。测试断言标签，不断言文案。

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 08-agent-loop -am test
```

15 个测试，全部离线。

## 依赖

依赖 [07-tool-calling](../07-tool-calling/README.md) 的 `ToolRegistry`。配置见 [05-llm-client](../05-llm-client/README.md)。

## 边界说明

- 循环的结局是**枚举**（`StopReason`），不是一句话。调用方靠字段判断，不靠正则匹配模型说的话；
- 超时保证的是「结束等待」，不保证「结束执行」—— 被中断的 handler 可能还在跑，这是 Java 线程模型的事实，不是实现偷懒。
