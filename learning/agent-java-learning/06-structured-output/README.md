# Structured Output 学习目录

阶段 6 前半。让模型输出**结构化数据而不是文本**，程序因此可以直接执行它 —— 但必须先过两层校验。

这一课是从「聊天机器人」转向「Agent 应用」的分界线。阶段 5 的模型输出是给人看的文本，从这里开始，模型输出的是给**程序**执行的数据，所以校验从「可选」变成「必须」。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | JSON 提取、两层校验、预览而非执行 | [01-structured-output.md](lessons/01-structured-output.md) | `learn.agent.llm.structured` | `learn.agent.llm.structured` |

## 四层链路

```text
自然语言指令
  ↓ 调模型（temperature=0）
  ↓ 解析      OperationJsonParser        JSON 合法吗、字段类型对吗
  ↓ 结构校验  OperationSchemaValidator   字段搭配对吗（纯函数，不查状态）
  ↓ 业务校验  SceneBusinessValidator     真实场景下能做吗（依赖场景快照）
预览（尚未执行）
```

分层的判断标准只有一条：**这条规则需要查运行时状态吗**。不需要的放 Schema 层，需要的放业务层。

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 06-structured-output -am test
```

52 个测试，**全部离线**。校验规则是纯逻辑，用 `FakeModelClient` 可以精确构造「模型输出了不存在的设备 id」这类场景，而这在真实模型上很难稳定复现。

## 依赖

依赖 [05-llm-client](../05-llm-client/README.md) 的 `ModelClient` 与消息模型。配置和 UTF-8 控制台设置见那份 README。

## 边界说明

- **结构正确不代表业务合法** —— 两层校验分开，是因为它们的失败原因不同、修复方式也不同；
- 模型输出只生成**预览**，不直接修改数据。真正执行需要用户确认，属于下一个模块。
