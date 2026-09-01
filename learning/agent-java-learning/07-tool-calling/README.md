# Tool Calling 学习目录

阶段 6 后半。把发起权交给模型：**模型自己决定**调哪个工具、传什么参数，程序负责执行和把关。

这是第二条分界线。阶段 5 和 06 模块都是**程序要求模型输出点什么**，从这里起是**模型决定程序做什么**。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | 模型主动选工具、prepare/invoke 分离、破坏性确认 | [01-tool-calling.md](lessons/01-tool-calling.md) | `learn.agent.llm.tool` | `learn.agent.llm.tool` |

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 07-tool-calling -am test
```

`-am` 会连带跑上游模块的测试，控制台总数比本模块大得多。本模块自己有 17 个测试，
全部离线；只想看这些，加 `-Dtest=` 指定测试类。

## 依赖

依赖 [05-llm-client](../05-llm-client/README.md) 的消息模型和 [06-structured-output](../06-structured-output/README.md) 的场景校验。配置见 05 那份 README。

## 边界说明

- 模型「能调」不等于程序「该执行」—— 副作用等级由**程序侧枚举**（`ToolEffect`）声明，不写进 prompt，模型无法覆盖；
- 工具失败是**返回值**，不是异常。它要回传给模型，让模型自己换参数重试；
- prepare 与 invoke 分离：prepare 零副作用，所以「查白名单、校验参数」可以在不执行的前提下先做完。
