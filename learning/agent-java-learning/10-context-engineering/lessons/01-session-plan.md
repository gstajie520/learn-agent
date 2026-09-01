# 第 1 课：会话计划与陈旧提醒

## 这一课解决什么

前八个阶段解决的都是「这一轮怎么跑对」：工具选得对不对、参数合不合法、该不该被允许执行、什么时候该停。这一课换一个问题：

**跑了二十轮之后，它还记得自己要干什么吗。**

长任务失败的真实样子不是模型突然变笨了，而是它**漂移**了。第 3 轮它说「先建 schema、再写 endpoints、最后补测试」，到第 18 轮它在反复调整 schema 的字段命名，后面两件事已经不在它的视野里。这时候你问它「你的计划是什么」，它会临时编一个听起来很合理的新计划 —— 而那不是它 15 轮前定下的那个。

原因不神秘：最初那句话在上下文里越来越远，注意力权重越来越低，而中间十几轮的工具结果全都是新鲜的、离得近的。系列文章第 5 篇「为什么上下文越长，系统提示词越没用」讲的就是这件事。

所以解决办法不是把提示词写得更长，而是**让计划成为一个必须被反复重写的对象**。

## 一、只接受完整快照

`todo_write` 的参数只有一个字段，而且必须是完整的任务数组：

```json
{"todos":[
  {"content":"读取配置","status":"completed"},
  {"content":"接入雷达设备","status":"in_progress"},
  {"content":"补充回归测试","status":"pending"}
]}
```

不提供 `todo_update(index, status)` 这种增量接口。这是本课第一个、也是最重要的设计决定。

增量补丁在短对话里没问题，在长对话里必然漂移：**模型记不清第 3 项是什么了，它只是在猜一个下标。** 猜错了下标，它会把「补充回归测试」标记成已完成，而实际完成的是「接入雷达设备」。这种错误不会报错，只会静默地让计划和现实脱节。

要求完整快照的代价是每次多花一些 token，收益是模型每次都必须把整个计划重读一遍 —— **这个「重读」本身就是对抗遗忘的机制，不是副作用。**

`TodoWriteValidator` 把增量补丁明确挡在门外，错误信息直接说清原因：

```
todos 必须是数组，实际是：OBJECT；todo_write 只接受完整快照，不接受单项补丁
```

## 二、三个状态，刻意不给第四个

```java
public enum TodoStatus {
    PENDING("pending"),
    IN_PROGRESS("in_progress"),
    COMPLETED("completed");
}
```

见过的失败设计是加上 `blocked`、`cancelled`、`deferred`。状态一多，模型就开始把「我不想做」写成 `deferred`，把「我做不动了」写成 `blocked`，计划从进度记录退化成**借口清单**。

三态的好处是每一项只能回答一个问题：**做完了没有。**

枚举带显式 `wireValue`，和阶段 7 的 `StopReason` 同一个理由：枚举名以后改了，落到日志和工具结果里的字符串不能跟着变，否则历史记录对不上。阶段 7 `AgentLoop.wireOf` 那处 `name().toLowerCase()` 是反例。

`fromWireValue` 返回 null 而不是抛异常 —— 这里的输入来自模型，写错是**预期内**的事件。它要变成一条能回传给模型的错误，而不是让整个请求崩掉。这条规则从阶段 6 的 `prepare` 一直沿用到现在。

## 三、一次列全部错误

校验器复用阶段 6 的 `ValidationResult`，一次性收集全部错误：

```
第 1 项的 status 非法：done；合法值：pending, in_progress, completed；
第 2 项的 content 不能是空白；
第 3 项的 status 非法：blocked；合法值：pending, in_progress, completed
```

模型一次写错三项，最好一次全告诉它。分三轮告诉它，就要多烧三轮 token，而且每一轮都有新的机会引入新的错误。

错误信息里**必须列出合法值**。只说「status 非法」等于让模型继续猜；把 `pending, in_progress, completed` 写出来，它下一轮才改得对。

下标从 1 开始报：模型看到的是它自己写的那个列表，从 1 数更自然。

## 四、提醒是请求级临时消息

计划建好之后还有第二个问题：模型建完计划就不管了，接着连调十几轮别的工具，计划永远停在第一版。

`TodoTracker` 数着「连续多少轮没更新计划」，到 3 轮就在下一次模型请求前塞一条提醒。

```java
public List<ChatMessage> beforeModel() {
    if (nonTodoToolRounds < STALE_TOOL_ROUNDS) {
        return Collections.emptyList();
    }
    nonTodoToolRounds = 0;
    return Collections.singletonList(ChatMessage.system(STALE_REMINDER));
}
```

这段代码有两个容易做错的地方。

**第一，提醒不能写进消息历史。** 它的作用是「让模型在**这一次**回答前想起计划」。append 进 messages 的话，它就永久占用上下文预算 —— 跑三十轮会攒下十条一模一样的提醒，每一轮都要为这十条重复付 token。更糟的是它污染了可回放的历史：这段对话被存档、被用于复盘或微调时，里面混着一堆运行时注入的噪声，而**它们并不是任何人说过的话**。

所以调用方必须只把返回值拼进这一次请求，发完就丢。

**第二，读取即清零。** 提醒已经发出去了，下一轮不该重复发。这也意味着 `beforeModel()` **有副作用**，不是纯查询 —— 名字里的 `before` 就是在说「它属于一次请求的生命周期」，不能随便多调一次。

没有工具调用的轮次不计数：模型纯说话（比如在追问用户）不算「干活」，拿它去催更新计划是误报。

## 五、工具结果回传 JSON，不是人类可读文本

写入成功后，回传的是一份同构的 JSON：

```json
{"todos":[{"content":"读取配置","status":"completed"}]}
```

**为什么要把整张表回传，而不是只回一句「已保存」**：这是让模型「重读」计划的最后一步。模型在下一轮看到的是**系统确认后的状态** —— 和它自己刚写的那份不一致时（比如某项被 trim 了、或者它写了 51 项），它能立刻发现。

**为什么回 JSON 而不是中文列表**：模型刚才写进来的就是 JSON，回一份同构的 JSON 它才能逐字段对比。回一段中文列表的话，它得先把自己的 JSON 在脑子里翻译成中文再比，这一步翻译本身就可能把差异抹掉。

人类可读的那份留给 `render()`，给 demo 和日志用。**两个受众，两种格式**，这是刻意分开的。

## 六、`todo_write` 是 WRITE 不是 DESTRUCTIVE

副作用等级选 `WRITE`：它只改会话内的计划状态，不动真实世界，撤销的成本就是再写一次快照。

如果标成 `DESTRUCTIVE`，按阶段 8 的规则它每次都要人工确认 —— 模型每更新一次计划就弹一次确认框，整个机制会立刻被用户关掉。

**副作用等级要按「撤销的真实成本」定，不是按「听起来危险不危险」定。**

## 七、接进阶段 8 的循环：一个发现

`PlanReminderHook` 把 tracker 注册到 `PostToolUse` 上，**没有给循环加一行代码**。这是阶段 8 那套 Hook 扩展点第一次被下游真正复用，也是对它的一次验收 —— 结论是它接得进去。

但接进去之后暴露了一件事：

```
=== 场景五：Hook 路径 vs 观察器路径 ===
  Hook 路径：全部请求累计出现 5 次提醒（进了历史，每轮重复付 token）
  观察器路径：全部请求累计出现 2 次提醒（每次触发只付一次）
```

Hook 返回的 `additionalContext` 会被 `HookedAgentLoop` **append 进 messages**，于是提醒一旦发出就留在历史里，此后每一轮都要为它付 token。同一个剧本跑 7 轮，两条路径的累计代价是 5 次对 2 次。

### 这里我曾经下过一个错误结论

当时我写的是：「这不是取舍失误，是一个发现 —— Hook 的设计目标是改变对话，而提醒要的恰恰是不改变对话，这在 Hook 的词汇表里没有对应物。正确的位置是第 5 课的 Provider。」

**前半句的观察是对的，结论是错的。** 教材在讲会话计划的**同一章**（`code/chapters/ch05/src/core/loop.ts`）就已经给了这个扩展点：

```ts
export interface ToolRoundObserver {
  beforeModel(): readonly ChatMessage[];
  recordToolRound(toolNames: readonly string[]): void;
}
```

循环在每次请求前调一次 `beforeModel()`，把产出拼进**这一次**请求的 messages，**不 push 进 history**。也就是说「请求级临时上下文」这个语义教材第 1 课就有，不需要等任何后续课程。

我当时只查了自己 Java 侧的三个循环、确认它们没有 observer，就直接下了「教材没有、要等 Provider」的结论 —— 把「**我的实现**没有 X」写成了「**教材**没有 X」。这两件事不一样。

修正后：`ToolRoundObserver` 放在 `08-agent-loop` 的 `loop` 包，`HookedAgentLoop` 多一个可选构造参数，`TodoTracker` 直接 `implements ToolRoundObserver`。两条路都留着 —— 观察器是正确语义，Hook 版留作反面教材，`PlanReminderHookTest` 钉住它「提醒会进历史」这个代价。

顺带纠正：Provider（第 6 课）管的是「整个系统提示怎么组装」，和「这一次请求要不要多带一句提醒」是两个不同的扩展点，教材 `ch10` 的循环里两者并存（`systemPromptProvider.render()` 和 `toolRoundObserver.beforeModel()`）。

### 另一个已知限制

`POST_TOOL_USE` 只在工具**真的执行了**之后触发。被权限拒绝、被 prepare 拦下、命中幂等缓存的轮次不会走到这里，所以那些轮次不计入陈旧计数。

从「计划有没有推进」的角度看这是对的（没执行就没推进），但它和 `recordToolRound` 的字面语义（「调过哪些工具」）有出入，如实记在这里。

## 八、计划是会话级状态

每次构建 Agent 都新建一个 tracker 实例。跨会话的计划持久化是**另一个问题**（本阶段第 4 课的文件记忆），混在一起会让「这个计划属于谁」变得没法回答 —— 两个用户共享一个 tracker，A 的计划会出现在 B 的上下文里。

`shouldIsolateSessions` 把这条钉成断言。

`handler` 是绑死在实例上的闭包，所以不可能出现「注册了 A 的工具、写进了 B 的 tracker」—— 那种 bug 在多用户场景下就是计划串号。

## 代码与测试

| 文件 | 作用 |
| --- | --- |
| `TodoStatus.java` | 三态枚举，带显式 wireValue |
| `TodoItem.java` | 不可变计划项，final 类 |
| `TodoWriteValidator.java` | 参数校验，一次收集全部错误 |
| `TodoTracker.java` | 完整快照 + 陈旧计数 + `beforeModel()` |
| `PlanReminderHook.java` | 桥接到阶段 8 的 `HookedAgentLoop` |
| `PlanDemo.java` | 五个场景的教学入口 |
| `TodoTrackerTest.java` | 25 个测试 |
| `PlanReminderHookTest.java` | 10 个测试 |

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 10-context-engineering -am test
```

本课自己 35 个测试，全部离线。`-am` 会把上游模块的测试一起跑掉，输出里的总数远大于 35；只想单独看这两个类，加 `-Dtest=TodoTrackerTest,PlanReminderHookTest`。

跑 demo：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
mvn -o -pl 10-context-engineering -am package -DskipTests
java "-Dfile.encoding=UTF-8" -cp '10-context-engineering/target/classes;10-context-engineering/target/dependency/*' learn.agent.llm.plan.PlanDemo
```

## 验收题

1. 为什么 `todo_write` 只接受完整快照？增量补丁在长对话里会怎么坏？
2. 提醒为什么不能 append 进消息历史？说出两个代价。
3. `beforeModel()` 为什么读取即清零？不清零会怎样？
4. 为什么 `todo_write` 是 `WRITE` 而不是 `DESTRUCTIVE`？标成 DESTRUCTIVE 会发生什么？
5. 工具结果为什么回传 JSON 而不是中文列表？
6. `PlanReminderHook` 和 `TodoTracker.beforeModel()` 的语义差在哪？这个差异说明现有循环缺了什么扩展点？

## 常见面试题

**问：Agent 跑长任务跑到一半忘了要干什么，你怎么定位和解决？**

先说清这不是模型能力问题，是上下文管理问题：早期消息在注意力上权重越来越低。解决方向有三层 —— 计划快照（本课）、上下文压缩（本阶段第 3 课）、跨会话记忆（第 4 课）。计划快照是最便宜的一层，它不需要压缩算法，只需要一个必须被反复重写的对象。

**问：为什么不用增量更新计划，那样不是更省 token 吗？**

省 token 但会漂移。增量要求模型准确记住每一项的下标或 id，而这恰恰是它在长上下文里最不可靠的能力。完整快照多花的 token 换来的是「每次都必须重读一遍」，重读本身就是对抗遗忘的机制。

**问：运行时注入的提醒，能不能直接写进消息历史？**

不能。两个代价：一是每一轮都要为重复的提醒付 token，三十轮会攒下十条一样的话；二是污染可回放的历史，这段对话被存档或用于微调时，里面混着从来没人说过的话。正确做法是请求级临时拼接，发完就丢。

**问：TODO 工具的副作用等级怎么定？**

按撤销的真实成本定。`todo_write` 只改会话内状态，撤销成本就是再写一次，所以是 `WRITE`。标成 `DESTRUCTIVE` 会让它每次都要人工确认，用户会直接把这个机制关掉 —— 一个天天弹确认框的安全机制等于没有安全机制。

**问：这个 TODO 状态跨会话保存吗？**

本课不保存，它是会话级的。跨会话持久化是另一个问题：要回答「计划属于谁」「过期的计划怎么处理」「两个会话同时改一份计划怎么办」。混进来会让当前这层的边界变模糊，留到文件记忆那一课单独解决。
