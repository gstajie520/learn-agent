# 第 5 课：手写 Agent Loop —— 边界、超时、幂等与 Trace

## 为什么还要再写一遍循环

第 4 课已经有一个能跑的循环了（`ToolCallingService`）。本课不是重写它，而是补上它**缺的那几样东西**。

先看第 4 课那个循环的签名：

```java
public String run(String systemPrompt, String userInput)
```

返回一个 `String`。现在请回答这几个问题，只允许看这个返回值：

- 这次是正常答完的，还是轮数耗尽被打断的？
- 一共跑了几轮？
- 第 2 轮调的是哪个工具，成功了吗？
- 这次对话烧了多少 token？

答案全都在那句话里**混着**，只能靠字符串匹配去猜。「轮数已用尽，请稍后重试」和模型自己说的「我稍后再试」，在类型层面是同一个东西。

本课把这四个问题变成**字段**。

## 本课新增的三件事

第 4 课已经有的东西（最大轮次、工具白名单、参数校验、异常回传、破坏性闸门），本课直接复用，不重复实现。真正新增的只有三条：

| 新增 | 解决什么 |
|---|---|
| 工具超时 | 工具卡住不返回时，循环整体挂死 |
| 重复调用幂等 | 模型重复请求同一个调用，副作用发生两次 |
| Trace 与结构化日志 | 出问题时无法归因：哪一轮、哪个工具、为什么停 |

## 一、`run` 返回 Trace，不返回字符串

```java
public AgentTrace run(String systemPrompt, String userInput)
```

`AgentTrace` 里有 `traceId`、`List<RoundTrace> rounds`、`stopReason`、`finalAnswer`。调用方要判断这次跑得好不好，一个 if 就够了：

```java
if (trace.getStopReason().isAbnormal()) { ... }
```

`StopReason` 是枚举，五个取值互斥：

```text
FINAL_ANSWER        模型给出了最终答复          ← 唯一的正常结局
MAX_ROUNDS          轮数耗尽被打断
TRUNCATED           输出被 max_tokens 截断
PROTOCOL_VIOLATION  响应自相矛盾
MODEL_ERROR         模型调用抛异常
```

### 为什么是内存对象，不是日志行

「结构化日志」听起来应该是往日志里打 `key=value`。本课先做成**内存对象**，理由是：

日志行只能人眼看。测试要验证「第 2 轮调了 create_device 并且命中了缓存」，如果信息只在 stdout，测试就得去抓输出、正则匹配——这种测试一改文案就红。而 Trace 是对象，直接断言：

```java
assertEquals("deduplicated", trace.getRounds().get(1).getToolOutcome());
```

这个顺序不能反。**先有可断言的结构，再把结构序列化成日志**，两边用同一份数据。反过来做（先打日志、以后再补结构）意味着要把散落在循环各处的埋点重新找一遍。

`RoundTrace.toLogLine()` 就是那层序列化，输出可 grep 的格式：

```text
round=1 finish=tool_calls tool=list_devices tool_call_id=call-1 outcome=executed tool_ms=2 model_ms=0 prompt_tokens=120 completion_tokens=30
```

### traceId 从接口来，不是直接 UUID

```java
public interface TraceIdGenerator {
    String next();
}
```

`AgentLoop` 里不写 `UUID.randomUUID()`，而是注入一个生成器。生产用 `TraceIdGenerator.RANDOM`，测试用 `TraceIdGenerator.fixed("trace-1")`，于是 trace id 也能精确断言。

这是第 1 课那条规矩的**第二次应用**：第 1 课用 `ModelClient` 接口隔离了「网络」，本课用 `TraceIdGenerator` 隔离了「随机」。凡是不确定的东西都藏在接口后面，测试才能确定。

## 二、工具超时：结束的是「等待」，不是「执行」

一个工具卡住不返回，整个循环就挂死——用户看着转圈，token 也没花出去，什么都没发生。

```java
Future<ToolExecutionResult> future = executor.submit(...);
try {
    return future.get(timeoutMillis, TimeUnit.MILLISECONDS);
} catch (TimeoutException e) {
    future.cancel(true);
    return ToolExecutionResult.error("tool_timeout",
            "工具执行超过 " + timeoutMillis + "ms，已放弃等待（工具可能仍在后台运行）");
}
```

**必须看清 `future.cancel(true)` 到底做了什么**：它只是给那个线程设了个中断标志。如果工具代码里没有任何检查中断的地方（比如它在跑一个纯计算的死循环，或者一个不响应中断的阻塞调用），它会**继续跑完**。

所以错误文案写的是「已放弃等待」，不是「已取消」。前者是事实，后者是谎话。

由此得到一条工程结论：**这道闸门是最后一道防线，不是唯一防线。** 工具自己也该有超时（HTTP 客户端的 read timeout、SQL 的 query timeout）。循环层的超时只保证「循环不会被一个工具拖死」，不保证「那个工具停了」。

线程池用 daemon 线程，这样即使有工具赖着不走，JVM 也能正常退出。

## 三、幂等：同样的调用只真正执行一次

模型会重复请求同一个调用。原因很多：上一轮结果它没看懂、温度导致它又想了一遍、多轮里它忘了自己已经调过。如果那个工具是 `create_device`，重复执行就是**多建一台设备**。

```java
public static String keyOf(ToolCall call) {
    String raw = call.getRawArguments();
    String normalized = (raw == null || raw.trim().isEmpty()) ? "{}" : raw.trim();
    return call.getName() + SEPARATOR + normalized;
}
```

两个设计决定值得说清楚：

**幂等键里故意不含 `tool_call_id`。** 那个 id 是服务端为每次调用新生成的，两次「一模一样的调用」也会有不同 id。把它算进键，缓存永远不会命中——这个功能就等于不存在。

**失败结果不缓存。**

```java
if (result == null || result.isError()) {
    return;   // 不记
}
```

如果缓存失败，一次偶发的超时或限流就会在整个会话里**变成永久失败**：模型第二次尝试同一个调用，直接拿到缓存里那条旧的失败消息，连重试的机会都没有。可重试的错误必须让它真的能重试。

**已知局限**：键是原始参数串的字面比较，所以 `{"a":1,"b":2}` 和 `{"b":2,"a":1}` 会被当成两个不同调用。要修就得把 JSON 解析后按 key 排序再序列化。本课不做，但要知道这个洞在哪。

## 四、四道边界，顺序是设计的一部分

`executeWithBoundaries` 里四步的**次序**不是随便排的：

```text
1. prepare        查白名单 + 解析参数 + 校验。零副作用。
2. 破坏性闸门      不可逆操作不执行，只回传等待确认。
3. 幂等缓存        同样的调用命中缓存，不重复产生副作用。
4. 超时执行        唯一真正调 handler 的地方。
```

为什么**破坏性闸门在幂等缓存之前**？因为「这次没有执行」这件事不需要缓存。破坏性工具压根没跑，它没有结果可缓存；如果反过来先查缓存，逻辑上就要处理「一个从未执行的调用的缓存」这种别扭状态。

每一步失败都带一个 outcome 标签，写进那一轮的 trace：

| outcome | 含义 |
|---|---|
| `rejected` | prepare 阶段就没过（工具不存在 / 参数非法） |
| `blocked_destructive` | 破坏性，等人工确认 |
| `deduplicated` | 命中幂等缓存，没有重复执行 |
| `executed` | 真的执行了，成功 |
| `failed` | 真的执行了，失败（含超时） |
| `protocol_violation` | 说有工具调用，内容里却没有 |

这六个标签是「这一轮到底发生了什么」的完整分类，测试直接断言标签，不去猜文案。

## 代码与测试

主代码（`lesson05` 包）：

- `StopReason.java` — 循环为什么停，五个互斥取值，`isAbnormal()` 一句话判断
- `RoundTrace.java` — 一轮的完整记录（轮次、工具、outcome、耗时、token），`toLogLine()` 转结构化日志
- `AgentTrace.java` — 整次运行的 trace；`addRound` / `finish` 是包级私有，只有循环能改
- `TraceIdGenerator.java` — 把「随机」藏到接口后面，测试可注入固定 id
- `ToolTimeoutGuard.java` — 超时闸门；结束等待，不保证结束执行
- `ToolCallMemo.java` — 幂等缓存；键不含 tool_call_id，失败不缓存
- `AgentLoop.java` — 循环本体，四道边界按序编排
- `AgentLoopDemo.java` — 五个场景的可运行入口

测试（15 个，全部离线）：

- `AgentLoopTest.java`（10）— 正常往返的 trace 字段、超时、幂等、四种异常停止原因、破坏性拦截、参数非法恢复
- `ToolCallMemoTest.java`（5）— 键的构成、失败不缓存、命中计数

## 验收题

1. **`run` 为什么要把返回值从 `String` 换成 `AgentTrace`？** 字符串里「答完了」和「被打断了」混在一起，调用方只能正则匹配去猜；枚举 + 字段让它变成一个 if。
2. **`future.cancel(true)` 之后工具停了吗？** 不一定。它只设中断标志，不检查中断的代码会跑完。所以文案是「放弃等待」，工具自己也必须有超时。
3. **幂等键为什么不含 `tool_call_id`？** 那个 id 每次调用都不同，含进去缓存永远不命中，功能等于不存在。
4. **为什么失败结果不进缓存？** 否则一次偶发超时会在整个会话里变成永久失败，模型连重试的机会都没有。
5. **破坏性闸门为什么排在幂等缓存前面？** 破坏性工具根本没执行，没有结果需要缓存；顺序反了就要处理「未执行调用的缓存」这种别扭状态。
6. **为什么先做内存 Trace 而不是直接打日志？** 日志只能人眼看、测试得抓 stdout 正则匹配；先有可断言的结构，再序列化成日志，两边共用一份数据。
