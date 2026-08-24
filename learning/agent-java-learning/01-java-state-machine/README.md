# Java 状态机学习练习

## 今天学什么

把智能场景命令建模成一个受约束的状态机。它对应 `fw` 项目中的命令生命周期：Java 接收请求后创建命令，Python Agent 返回预览或失败结果，用户确认后才应用变更。

本练习只关注 Java 基础，不连接 Redis、RabbitMQ 或模型服务。

## 概念示例：先看懂这 20 行

```java
enum Status { PENDING, RUNNING, APPLIED }

final class Command {
    private Status status = Status.PENDING;

    void moveTo(Status next) {
        boolean allowed = status == Status.PENDING && next == Status.RUNNING
                || status == Status.RUNNING && next == Status.APPLIED;
        if (!allowed) {
            throw new IllegalStateException(status + " -> " + next + " is not allowed");
        }
        status = next;
    }

    Status status() {
        return status;
    }
}
```

逐行理解：

1. `enum Status`：用有限枚举代替随意的字符串，编译器可以帮助发现拼写错误。
2. `private Status status`：状态只能由对象内部改变，外部不能直接赋值。
3. `moveTo`：所有状态变化集中在一个入口，便于统一校验。
4. `allowed`：只允许 `PENDING -> RUNNING` 和 `RUNNING -> APPLIED`。
5. 非法迁移抛异常：调用方必须处理业务错误，不能悄悄修改状态。
6. 最后才写入 `status`：校验失败时对象保持原状态。

这个例子故意很小，但它揭示了后面 Redis/MQ 的关键：消息可以重复、服务可以重启，所以状态迁移必须有明确规则，不能到处写 `status = ...`。

## 完整项目

完整实现位于：

```text
src/main/java/learn/agent/statemachine/
  CommandStatus.java
  IllegalStateTransitionException.java
  SceneCommand.java
src/test/java/learn/agent/statemachine/
  CommandStatusTest.java
```

完整实现增加了：

- `PREVIEW`、`FAILED`、`TIMEOUT`、`CANCELLED` 分支；
- 面向领域的异常类型；
- 集中维护的不可变迁移表；
- `commandId` 和只读状态访问；
- 合法迁移、非法迁移、终态保护、重复迁移、实例隔离测试。

### 如何阅读测试类

先看 [CommandStatusTest.java](src/test/java/learn/agent/statemachine/CommandStatusTest.java)，不要先看实现。
每个测试都对应一条业务规则：

| 测试方法 | 它在验证什么 |
|---|---|
| `allowsTheHappyPath` | 正常路径可以从等待执行走到已应用 |
| `allowsFailureAndCancellationBranches` | 失败、超时、取消可以进入终态 |
| `rejectsBlankCommandIds` | 没有命令标识就不能创建可追踪命令 |
| `rejectsIllegalTransitions` | 不能跳过执行/预览直接应用 |
| `protectsTerminalStates` | 终态不能重新执行 |
| `repeatedTransitionDoesNotSilentlySucceed` | 重复迁移不能被当成新成功 |
| `rejectsNullAsTheNextStatus` | 空目标状态必须拒绝 |
| `commandInstancesKeepIndependentState` | 不同命令实例的状态互不污染 |

测试内部使用 `Arrange → Act → Assert` 注释：先准备场景，再执行动作，最后断言外部行为。学习时应先根据测试回答“系统必须保证什么”，再去看 `SceneCommand` 如何实现。

代码中的注释专门说明了三层边界：

1. `SceneCommand`：只负责单个 JVM 内的领域状态规则；
2. Redis/数据库：负责跨请求、跨进程的状态持久化；
3. RabbitMQ：负责把任务或结果消息传给另一个服务，不负责保存最终业务状态。

## 状态规则

```text
PENDING -> RUNNING
PENDING -> CANCELLED
RUNNING -> PREVIEW
RUNNING -> FAILED
RUNNING -> TIMEOUT
PREVIEW -> APPLIED
```

没有列出的迁移全部拒绝。

## 运行

在 PowerShell 中执行：

```powershell
Set-Location '.\learning\agent-java-learning\01-java-state-machine'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o test
```

本机的 `java -version` 可能显示 17，但 Maven 使用的是 `JAVA_HOME`。如果 `mvn -v` 显示 Java 8，必须先修正 `JAVA_HOME`，否则 Java 17 的 `--release` 参数无法编译。

当前用户目录下的 `.m2/settings.xml` 还有一个根元素格式警告；它没有阻止离线测试，但后续学习 Maven 时需要单独修复。

## 验收问题

1. 为什么不能让任何类直接修改 `status`？
2. 如果两个 MQ 消费者同时处理同一个 `commandId`，这个内存对象能否保证幂等？
3. 为什么 `APPLIED` 不能回到 `RUNNING`？
4. 哪些状态适合放 Redis，哪些数据仍需要数据库？

## 四个问题的答案

### 1. 为什么不能让任何类直接修改 `status`？

你的回答方向正确。更完整地说，是为了保护状态不被绕过规则随意修改。
如果外部代码可以直接写：

```java
command.status = CommandStatus.APPLIED;
```

那么它可以跳过 `PENDING -> RUNNING -> PREVIEW`，导致用户还没有确认，场景却被标记为已应用。封装让所有迁移都集中经过 `transitionTo`。

### 2. 两个 MQ 消费者同时处理同一个 `commandId`，这个对象能保证幂等吗？

不能。原因是每个消费者通常运行在不同线程、不同 JVM，甚至不同机器上。每个进程里都有自己的 `SceneCommand` 对象：

```text
消费者 A：内存中的 command-A，看到 PENDING
消费者 B：内存中的 command-B，也看到 PENDING
```

它们互相看不到对方的内存，所以都可能执行一次。要保证跨实例幂等，必须把 `commandId` 和当前状态放到共享持久化边界，例如 Redis 或数据库，并使用原子条件更新：

```text
只有 status = PENDING 时，才允许更新为 RUNNING
更新成功的消费者继续执行，更新失败的消费者识别为重复消息
```

### 3. 为什么 `APPLIED` 不能回到 `RUNNING`？

你的回答“不能”是结果，但还需要说明原因：`APPLIED` 是终态，表示用户已经确认且变更已经应用。再次回到 `RUNNING` 会让同一个命令重复执行，可能造成重复新增、版本覆盖或数据破坏。

如果用户想再次修改，应创建一个新的 `commandId`，而不是重启已完成命令。

### 4. Redis 和数据库应该分别保存什么？

“全部”不够准确。要按数据的可靠性和用途区分：

| 数据 | Redis | 数据库 |
|---|---|---|
| 当前命令状态 | 适合，支持快速查询和原子迁移 | 适合做最终审计/长期记录 |
| `commandId` 幂等记录 | 适合，设置 TTL | 如果需要永久审计也保存 |
| MQ 消息正文 | 通常不作为主存储 | 按业务需要保存请求/结果摘要 |
| LangGraph checkpoint | 适合专用 checkpoint 存储 | 也可用专门持久化方案 |
| 最终 SceneDocument | 不建议只放 Redis | 应放数据库或对象存储等持久化介质 |
| 审计日志 | 可短期缓存 | 应放长期可查询存储 |

简单记忆：Redis 偏“快速状态和协调”，数据库偏“长期事实和审计”。生产系统可以两边都存，但不能把两边当成同一个真相源。
