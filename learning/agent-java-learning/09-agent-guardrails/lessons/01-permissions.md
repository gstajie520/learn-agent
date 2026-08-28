# 第 6 课：权限四态、人工确认与审计

## 完成标准

阶段 8 的完成标准写得很具体：

> 能在**不修改 Loop 主体**的前提下，为某个工具加一条「必须人工确认」的策略，并留下审计记录。

三个考点，缺一个都不算过：

1. **不改 Loop 主体** —— 策略是注进去的，不是写死在循环里的 `if`。
2. **必须人工确认** —— 有一个真正的裁决环节，而不是「打了个日志然后照样执行」。
3. **留下审计记录** —— 事后能回答「谁批的、依据哪条规则、批的是什么」。

`GuardedAgentLoopTest.shouldAddConfirmationPolicyWithoutTouchingLoop` 是这条标准的直接证明：同一个 Loop、同一份代码，只换注进去的策略，一次执行、一次不执行。

## 一、四态，不是三态

直觉上权限只有「允许 / 拒绝」，加上人工确认就是三态。实际需要四态：

| 状态 | 含义 | 能否离开 policy |
| --- | --- | --- |
| `allow` | 放行 | 能，最终态 |
| `deny` | 拒绝 | 能，最终态 |
| `ask` | 需要人工裁决 | **不能**，中间态 |
| `passthrough` | 无意见 / 弃权 | **不能**，中间态 |

第四态 `passthrough` 是最容易被漏掉的那个，但少了它就没法区分两件事：

- 「我看过这次请求，我同意放行」 —— `allow`，是一张赞成票。
- 「这次请求不在我管的范围内」 —— `passthrough`，是弃权。

为什么必须区分：归约的时候弃权票不该参与计票。如果一条只管 `delete_*` 的规则在遇到 `list_devices` 时返回 `allow`，它就在替一个自己根本没审查过的请求背书。规则数量一多，总会有某条规则「顺手」放行了别的规则想拦的东西。

`passthrough` 归一为 **allow**，不是 deny：

```java
} else if (proposed.getBehavior() == PermissionBehavior.PASSTHROUGH) {
    last = new PermissionDecision(PermissionBehavior.ALLOW,
            "没有任何权限规则拦下这次请求", "default");
}
```

「没有任何规则反对」应当等于放行，否则每加一个工具都得配一条 allow 规则，权限系统会变成一件纯负担。注意 `source` 写的是 `default` 而不是某条规则名 —— 审计里必须能看出这次放行是「没人管」而不是「有人批」。

## 二、归约是三轮扫描，不是排序

`deny > ask > allow`，看着就是个优先级比较，很容易写成：

```java
// 错误示范
candidates.stream().max(Comparator.comparingInt(d -> d.getBehavior().ordinal()));
```

三个问题：

1. **依赖 `ordinal()`** —— 枚举常量的声明顺序变成了业务语义。哪天有人为了好看把 `ASK` 挪到 `ALLOW` 前面，权限系统就悄悄改变行为，而且不会有任何编译错误。
2. **`max` 在平级时的选择是实现细节** —— 两条同级的 deny 规则，`reason` 和 `source` 不一样，而这两个字段是要进审计的可观测输出。`max` 返回哪个取决于 JDK 实现，不是你定的。
3. **`passthrough` 会参与比较** —— 它必须被完全忽略，不是「排在最后」。

正确写法是三轮独立扫描，同级取**列表中最早出现的那个**：

```java
PermissionBehavior[] order = {DENY, ASK, ALLOW};
for (PermissionBehavior behavior : order) {
    for (PermissionDecision candidate : candidates) {
        if (candidate.getBehavior() == behavior) {
            return candidate;   // 同级取最早，可预测
        }
    }
}
```

「同级取最早」配上固定的候选收集顺序，整个裁决就是完全确定的：

```
硬边界 → 默认策略 → Hook 建议 → 规则（注册顺序）
```

`shouldPreferEarlierCandidateAtSameLevel` 和 `shouldEvaluateRulesInRegistrationOrder` 这两个测试锁的就是这件事。

顺带一句：**两个优先级阶梯不要共用一个比较器**。policy 归约是三级（deny/ask/allow，passthrough 忽略），第 7 课 Hook 合并是四级（passthrough=0 < allow=1 < ask=2 < deny=3，passthrough 参与）。语义不同，合成一个 `Comparator` 复用就会有一边是错的。

## 三、ask 有五条 fail-closed 路径

`ask` 绝不允许离开 policy，`resolveApproval` 负责把它收敛成最终态。五种出问题的情况**全部**变成 deny：

| 情况 | 结果 |
| --- | --- |
| 没有配置审批器 | deny |
| 审批器抛异常 | deny |
| 审批器返回 null | deny |
| 审批器又返回 `ask` | deny |
| 审批器返回 `passthrough` | deny |

后两种最容易被忽略：审批器返回 `ask` 等于「我不决定」，那就是没裁决。如果这时放行，等于「问了一句没人答，那就干吧」。

**默认答案必须是不执行。** 审批环节自己出故障时如果默认放行，这道闸门在最需要它的时刻恰好失效 —— 而这正是攻击者会去制造的状态。

## 四、硬边界不可翻盘

有些操作不该有「批准」这个选项。本课选的是受保护设备：

```java
if (scene.isProtected(targetId.asText())) {
    return new PermissionDecision(DENY, "设备 " + ... + " 受保护，禁止删除", "protected-device");
}
```

它凭什么翻不动：

- 它**第一个**进候选列表；
- 它给的是 `deny`，而 deny 在归约里压过一切；
- 于是最终态是 deny，`decide` 走的是 `else { last = proposed; }` 分支，**审批器连问都不会问**。

`shouldNotConsultApproverWhenHardBoundaryDenies` 断言的就是审批器的调用次数为 0。这一条比「结果是 deny」更强：只要人还能被问到，就总有办法让人点下同意。

**能被批准的边界不是边界，是提示。**

## 五、审计是闸门，不是日志

这是本课最反直觉的一条。审计写失败时，操作**不执行**：

```java
// decide() 里刻意不包 try-catch
if (audit != null) {
    audit.record(request, last);
}
return last;
```

`record` 抛异常 → `decide` 抛异常 → Loop 转成 `permission_evaluation_error` → handler 不执行。

为什么不能把异常吞掉：吞掉之后会出现「副作用已经发生，却没有任何记录」的状态。对一个需要审计的系统来说，这比操作失败严重得多 —— 操作失败可以重试，无记录的操作没法追溯，事后你甚至不知道它发生过。

演示里的场景五刻意用了一个**只读**工具：它一定会被放行，但审计写失败，所以它也不执行。

另外两条约束：

- **每次 `decide()` 恰好一条记录**，写在最终决定之后。所以审计里永远看不到 `ask` 和 `passthrough` —— 只有真正生效的 allow/deny。
- **规则谓词抛异常 → 按那条规则的名字 deny**，不是忽略。一条规则写崩了就当它不存在，等于给了「让规则崩溃」这个绕过手段。

## 六、一处如实交代的设计债

第 5 课的 `AgentLoop` 把 `executeWithBoundaries` 写成私有方法、四道边界硬编码、字段全 `private final`。结果本课**没法复用它**：不能继承覆盖那一个方法，也不能从外面替换某道边界，只能把循环骨架重写一遍。

`AgentTrace` 同理 —— `addRound` 和 `finish` 是包私有的。包私有是**包**边界不是类边界，第 5 课把写入方和轨迹放在同一个包里，自己用得很顺，换个包就够不着了。所以本课新写了 `GuardedTrace`，但 `RoundTrace` 和 `StopReason` 本来就是 public，照原样复用。

两个教训：

- **希望被下游扩展的类，写入口不能停在包私有。**
- **「不改主体就能扩展」是设计出来的，不是自然长出来的。**

那为什么不回头给第 5 课加抽象？因为把边界提成可注入的 `ToolGate` 列表，需要先见过第二个用例才讲得清；第 5 课那时只有一个。这里选择保留重复、把代价写在注释里，而不是让第 5 课提前引入一层读者还理解不了的抽象。

## 代码与测试

| 文件 | 作用 |
| --- | --- |
| `permission/PermissionBehavior.java` | 四态枚举，`isFinal()` 区分中间态 |
| `permission/PermissionDecision.java` | 决定 + `reason` + `source`，三者都不可为空 |
| `permission/PermissionRequest.java` | 提交裁决的请求，带 `PreparedToolCall` 而非原始调用 |
| `permission/PermissionRule.java` | 一条规则：匹配器 + 行为 + 理由 |
| `permission/ApprovalProvider.java` | 人工裁决接口 |
| `permission/AuditSink.java` | 审计接口，允许抛异常 |
| `permission/PermissionPolicy.java` | 候选收集 + 三轮归约 + 审批收敛 + 审计 |
| `permission/GuardedTrace.java` | 轨迹 + 裁决记录 |
| `permission/GuardedAgentLoop.java` | 把裁决插进边界链 |
| `permission/PermissionDemo.java` | 五个场景 |

测试 36 个，全部离线：

```powershell
mvn -o -pl 09-agent-guardrails test "-Dtest=PermissionPolicyTest,GuardedAgentLoopTest"
```

运行演示：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
mvn -o -pl 09-agent-guardrails -am package -DskipTests
java "-Dfile.encoding=UTF-8" -cp '09-agent-guardrails/target/classes;08-agent-loop/target/classes;07-tool-calling/target/classes;06-structured-output/target/classes;05-llm-client/target/classes;05-llm-client/target/dependency/*' learn.agent.llm.permission.PermissionDemo
```

## 验收题

1. 为什么 `passthrough` 归一为 allow 而不是 deny？如果归一为 deny，加一个新工具要付什么代价？
2. 把 `strongest` 换成 `Collections.max(candidates, comparingInt(d -> d.getBehavior().ordinal()))`，哪两个测试会挂？为什么其中一个和 `reason` 字段有关？
3. 审批器返回 `ask` 时为什么必须当成 deny？返回 `allow` 和返回 `ask` 在「它是否做了决定」上差在哪？
4. 硬边界拒绝时，为什么连审批器都不问？只断言「结果是 deny」为什么不够？
5. 把 `audit.record` 包进 `try-catch` 并忽略异常，系统会进入什么状态？为什么这比「操作失败」更糟？
6. 一条规则的谓词抛了异常，为什么不能当它没匹配上？
