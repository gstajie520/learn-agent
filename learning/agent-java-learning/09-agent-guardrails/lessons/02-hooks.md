# 第 7 课：Hook 生命周期与契约边界

## 这一课解决什么

第 6 课让权限成了一道可注入的闸门，但闸门只能回答「许不许」。真实需求里还有一批要求，它们既不是权限也不是业务：

- 每次调用前把模型给的 `limit=999` 收敛成 `limit=10`。
- 工具返回的手机号，在进模型历史**之前**脱敏。
- 用户提问时自动补一句当前场景说明。
- 模型说「我做完了」，但检查发现某项没做，要它再来一轮。

这些都是横切关注点。硬写进循环，循环就会长成一坨谁都不敢改的东西；写成工具，它们又不该由模型决定要不要调。Hook 是第三条路：**在循环的固定几个点上，让外部代码插进来**。

阶段 8 的完成标准在第 6 课已经达成。这一课是同一阶段的另一半 —— 权限管「许不许」，Hook 管「在哪些时刻可以介入，介入能做什么、不能做什么」。

## 一、只有四个事件

```java
public enum HookEvent {
    USER_PROMPT_SUBMIT("UserPromptSubmit"),
    PRE_TOOL_USE("PreToolUse"),
    POST_TOOL_USE("PostToolUse"),
    STOP("Stop");
}
```

四个，不多不少。判断标准是：**这个时刻有没有一件别处做不了的事**。

| 事件 | 时刻 | 独占能力 |
| --- | --- | --- |
| UserPromptSubmit | 用户消息进历史**之前** | 补上下文；这是唯一能在模型看到问题前动手的点 |
| PreToolUse | prepare 之后、裁决之前 | 改参数、提权限建议、直接拦下 |
| PostToolUse | 工具执行之后、结果进历史之前 | 改结果、要求收手 |
| Stop | 模型给出非工具调用的答复后 | 判定「其实还没完」，续写一轮 |

被砍掉的候选事件里最值得说的是「模型调用前后」。它看着有用（改 prompt、记 token），但改 prompt 和 UserPromptSubmit 重叠，记 token 是 trace 的活。一个不提供独占能力的事件只会增加要维护的契约。

## 二、一次调用的完整链路

```
prepare              零副作用，失败直接回传
  → PreToolUse       可改参数、可提权限建议、可直接拦下
  → 权限裁决          最终决定权在这里，Hook 的建议只是候选
  → 幂等缓存
  → 限时执行          唯一产生副作用的地方
  → PostToolUse      可改结果、可要求收手
```

这个顺序是设计出来的，两个位置尤其要说清楚。

**PreToolUse 排在权限裁决之前。** 所以 Hook 能在裁决前改参数，但改完还得过裁决 —— Hook 不是绕过权限的后门，它是权限的输入。

**权限裁决排在幂等缓存之前。** 第 6 课已经论证过：排在缓存之后，重复调用就只有第一次会被裁决，第二次直接命中缓存拿到结果，审计里少一条记录。

`HookedAgentLoopTest.shouldFireHooksInDocumentedOrder` 把这个顺序钉死成断言：

```java
assertEquals(Arrays.asList("user", "pre", "permission", "handler", "post", "stop"), order);
```

## 三、`updatedInput` 的三道锁

`PreToolUse` 允许 Hook 替换整个 `PreparedToolCall`。这是本课最危险的一个能力，威胁模型是**「批准 A、执行 B」**：Hook 拿到一次 `read_device` 调用，返回一个 `delete_device`，然后权限层裁决的是删除、还是放行的只读？无论哪种答案都错了。

所以合法的改写只能改参数。三道锁：

```java
if (!originalCall.getId().equals(updatedCall.getId())) {
    throw new HookContractException("updatedInput 必须保留原来的 tool_call_id");
}
if (!originalCall.getName().equals(updatedCall.getName())) {
    throw new HookContractException("updatedInput 必须保留原来的工具名");
}
if (updated.getDefinition() != original.getDefinition()) {
    throw new HookContractException("updatedInput 必须保留注册表里那一份工具定义");
}
```

1. **`tool_call_id` 不变** —— 变了结果就会和模型的另一次调用配错。
2. **工具名不变** —— 这是「批准 A 执行 B」的正面防线。
3. **`definition` 必须是同一个对象** —— 用 `!=` 比引用，不是 `equals`。

第三道锁的引用比较是刻意的。`ToolDefinition` 没有覆写 `equals`，但即便覆写了也不该用：攻击者可以构造一个名字、描述、schema、`effect` 全都一致、只有 `handler` 指向别处的孪生对象。字段相等在这里毫无意义 —— **要的是「就是注册表里那一个」，只有引用相等能表达这件事。**

`shouldRejectUpdatedInputThatSwapsDefinitionInstance` 就是照这个攻击写的：孪生定义的 handler 一旦跑起来就往列表里记一笔，测试断言那个列表始终是空的。

三道锁之后还有两步：

- **重跑参数校验** —— Hook 改出来的参数不比模型给的更可信。
- **返回新构造的对象** —— Hook 手里那份引用改不到后续执行。否则 Hook 可以先返回一份合法参数，等过了裁决再去改它手里的 `ObjectNode`（一个活的可变节点），这是经典的 TOCTOU。

## 四、异常的两种走向，刻意不一致

| 事件 | 异常处置 |
| --- | --- |
| UserPromptSubmit | **不捕获**，终止整次运行 |
| PreToolUse | 降级成工具错误 |
| PostToolUse | 降级成工具错误 |
| Stop | **不捕获**，终止整次运行 |

看着不一致，理由是这两组的失败含义不同。

`PreToolUse` / `PostToolUse` 挂掉，失败范围是**一次工具调用**。回传一个工具错误，模型下一轮还能换个做法，整次运行仍有可能成功。

`UserPromptSubmit` 挂掉，意味着输入还没成形就出了问题 —— 没有「下一轮」可言。`Stop` 挂掉同理：这时循环正要收尾，降级只能是「假装它没说话」，而它可能正想说「这次结果不能交」。

PostToolUse 的失败还有一个必须如实交代的细节：

```java
// 注意：工具已经执行了，副作用已经发生。所以这里不能假装
// 什么都没发生，要如实回传「结果处理失败」，而不是丢掉结果。
return new Outcome("hook_error", ToolExecutionResult.error(
        "hook_execution_error", "PostToolUse Hook 执行失败，工具已执行但结果未能处理"),
        decision, preHook.getAdditionalContext(), false);
```

契约违反和执行异常还分成了两个错误码（`hook_contract_error` / `hook_execution_error`）。前者是 Hook 写错了，后者是 Hook 跑挂了，排查方向完全不同。

## 五、合并多个 Hook：四级阶梯

同一事件可以注册多个 Hook，串行执行，结果需要合并。权限建议的合并用四级：

```
passthrough: 0    allow: 1    ask: 2    deny: 3
```

和第 6 课的归约**刻意不共用**一套阶梯。第 6 课是三级扫描，`passthrough` 弃权不计票；这里是四级取最大值。为什么不统一：第 6 课的归约要产出一条带 `reason` 和 `source` 的审计记录，所以需要「最早的同级候选」这种顺序语义；Hook 合并只需要一个最严的行为值，没有审计义务。强行统一会把审计的约束带进一个不需要它的地方。

合并之间还要**重新构造上下文**：

```java
if (effective.getUpdatedInput() != null) {
    current = HookContext.preToolUse(effective.getUpdatedInput());
}
```

第二个 Hook 看到的必须是第一个 Hook 改过之后的调用，否则两个都想改参数时，后一个会基于过时的输入做判断，把前一个的改动覆盖掉。

`blockingError` 或 `forceContinue` 一出现就 `break` —— 已经决定拦下了，后面的 Hook 没有再表态的意义。

## 六、三条「Hook 不能假装成别人」的规则

`HookResult.Builder` 在 setter 里就校验，不等到 `build()`：

| 字段 | 只接受 | 拦住的是什么 |
| --- | --- | --- |
| `additionalContext` | `system` 消息 | Hook 冒充用户说话 |
| `forceContinue` | `user` 消息 | 模型不会回应一个 system 轮次，续写会哑掉 |
| `blockingError` | error 态结果 | 用 success 阻断，等于伪造一次「工具执行成功了」而工具压根没跑 |

`addContext` 还会重新构造那条消息，避免 Hook 持着同一个引用，在合并之后再去改它。

## 七、无限续写：靠机制，不靠自律

`Stop` 能要求循环再来一轮。一个写成「总是要求继续」的 Hook 会让循环永不结束。

解法不是在文档里写「请不要这样做」，而是让它做不到：

```java
if (context.getEvent() == HookEvent.STOP
        && context.isStopHookActive()
        && result.getForceContinue() != null) {
    // Stop 已经续写过一次，就不允许再续。
    // additionalContext 保留 —— 它只是说明文字，无害。
}
```

循环续写一次后置位 `stopHookActive`，注册表在第二次直接把续写请求吞掉。**Hook 依然可以请求，只是请求不再生效。**

顺带一提，这个开关暴露给了 Hook（`context.isStopHookActive()`），因为一个写得好的 Hook 应当能知道「我这次说了也没用」，从而输出一条更准确的说明文字。

## 八、`GuardedTrace` 的写入口改成了 public

第 6 课的设计债那一节写下过两条教训，其中一条是：

> **希望被下游扩展的类，写入口不能停在包私有。**

第 7 课就是那个下游。`GuardedTrace.addRound` / `addDecision` / `finish` 原本是包私有的，本课要用就得再抄一份一模一样的轨迹类 —— 同样的错误连犯两次。所以这次改成了 public，并在 javadoc 里写清代价：

> 写入口公开之后，任何拿到 trace 的人都能往里塞记录，轨迹不再只由循环写。

这是一个真实的取舍，不是免费的改进。选择公开，是因为「重复一整个类」的代价更大，而且第 6 课已经把结论写下来了 —— 写下来又不照做，等于没写。

## 代码与测试

| 文件 | 作用 |
| --- | --- |
| `hook/HookEvent.java` | 四个事件的枚举 |
| `hook/HookContext.java` | 事件上下文，按事件校验字段归属 |
| `hook/HookResult.java` | Hook 的返回，setter 即校验 |
| `hook/HookCallback.java` | 单方法回调接口 |
| `hook/HookRegistry.java` | 注册、串行执行、合并、三道锁 |
| `hook/HookContractException.java` | 契约违反的稳定异常类型 |
| `hook/HookedAgentLoop.java` | 把四个事件插进循环 |
| `hook/HookDemo.java` | 六个场景 |

测试 33 个，全部离线：

```powershell
mvn -o -pl 09-agent-guardrails test "-Dtest=HookRegistryTest,HookedAgentLoopTest"
```

运行演示：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
mvn -o -pl 09-agent-guardrails -am package -DskipTests
java "-Dfile.encoding=UTF-8" -cp '09-agent-guardrails/target/classes;08-agent-loop/target/classes;07-tool-calling/target/classes;06-structured-output/target/classes;05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.hook.HookDemo
```

## 验收题

1. 为什么 `PreToolUse` 排在权限裁决**之前**而不是之后？排在之后，Hook 会获得什么它不该有的能力？
2. 第三道锁为什么用 `!=` 比引用而不是 `equals`？构造一个能骗过 `equals` 的攻击对象。
3. 三道锁都过了，为什么还要重跑参数校验，还要返回新构造的对象？后者防的是哪一类时序问题？
4. `UserPromptSubmit` 的异常不捕获、`PreToolUse` 的异常捕获，这个不一致的依据是什么？
5. Hook 合并用四级阶梯，第 6 课的归约用三级扫描。统一成一套会把什么约束带到不需要它的地方？
6. `blockingError` 为什么不接受 success 态的结果？如果接受，一个 Hook 能伪造出什么？
7. `stopHookActive` 为什么要暴露给 Hook 自己看？不暴露会少掉什么？
