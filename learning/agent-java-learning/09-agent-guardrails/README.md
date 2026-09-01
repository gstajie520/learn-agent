# 权限与 Hook 学习目录

阶段 8。前面几个模块问的是「这次调用能不能跑通」，本模块问两个新问题：**这次调用该不该被允许**，以及**在哪些时刻可以插手**。

两课合成一个模块，因为 hook 直接消费 permission 的裁决结果 —— `HookResult` 提的权限意见只是候选，最终裁决权在 `PermissionPolicy` 手里，拆开会造成一次循环依赖。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | 四态归约、人工确认、硬边界、审计闸门 | [01-permissions.md](lessons/01-permissions.md) | `learn.agent.llm.permission` | `learn.agent.llm.permission` |
| 2 | 四个事件、改写输入输出、契约三道锁 | [02-hooks.md](lessons/02-hooks.md) | `learn.agent.llm.hook` | `learn.agent.llm.hook` |

第 1 课不改 08 的 `AgentLoop` 一行代码，靠注入一个 `PermissionPolicy` 把「必须人工确认」加进去。

第 2 课再换一次视角：权限只能表态放行或拒绝，Hook 能改参数、改结果、往历史里补说明、要求循环别停。能力大了一圈，所以约束也要跟着长。

## 裁决插在哪里

```text
模型请求一次工具调用
  ↓ 1. prepare          和 08 一样，零副作用
  ↓ 2. 权限裁决          候选收集 → 三轮归约 → 审批收敛 → 审计   替换 08 的破坏性闸门
  ↓ 3. 幂等缓存          排在裁决之后
  ↓ 4. 超时执行
写入 GuardedTrace（轨迹 + 裁决记录分开存）
```

裁决**必须排在幂等缓存之前**：反过来的话，一次批准过的调用会绕开后续所有裁决，权限就只在第一次生效了。

第 1 课替换而不是叠加 08 的破坏性闸门 —— 同一件事有两个真相来源，迟早会对不上。

## Hook 的六个阶段

```text
UserPromptSubmit      用户消息进历史之前      异常直接终止整次运行
  ↓ 模型这一轮
  ↓ prepare           零副作用
  ↓ PreToolUse        可改参数、可提权限建议、可直接拦下
  ↓ 权限裁决           第 1 课那一层，Hook 的意见只是候选
  ↓ 幂等缓存
  ↓ 限时执行           唯一产生副作用的地方
  ↓ PostToolUse       可改结果、可要求收手
Stop                  没有工具调用之后，最后一次「其实还没完」的机会
```

只有四个事件，刻意不多。每加一个事件都要回答「谁会用它、它能改什么、改错了谁兜着」，答不上来的事件就是给后人埋坑。

两条不对称是设计出来的，不是漏写：

- **UserPromptSubmit 和 Stop 的异常不捕获**，直接终止整次运行。这两处失败意味着「输入还没成形」或「结局还没定」，没有可以降级的中间态。
- **PreToolUse 和 PostToolUse 的异常降级成工具错误**，模型下一轮还能换做法。

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 09-agent-guardrails -am test
```

`-am` 会连带跑上游模块的测试，控制台总数比本模块大得多。本模块自己有 69 个测试
（权限 36 + Hook 33），全部离线；只想看这些，加 `-Dtest=` 指定测试类。

## 依赖

依赖 05、06、07、08 四个模块。配置见 [05-llm-client](../05-llm-client/README.md)。

## 边界说明

- 权限只有 `allow` 和 `deny` 两种结果能离开策略。`ask` 和 `passthrough` 是中间态，必须在策略内部收敛掉；
- **审计是闸门不是日志**：审计写失败时操作不执行。「副作用发生了却没有记录」比「操作失败」严重得多；
- **Hook 只提建议，不做权限决定**。`PreToolUse` 说 allow 也翻不动受保护设备的硬边界；
- **Hook 改写的输入要重新过校验**。Hook 改出来的参数不比模型给的更可信，凭「它是我们自己的代码」放行，等于把权限边界建在「谁写的」而不是「验过没有」上；
- `updatedInput` 过三道锁，防的是「批准 A、执行 B」：tool_call_id 必须保留、工具名必须保留、`ToolDefinition` 必须是**同一个对象**（用 `!=` 比引用，不是 `equals`）。过锁之后还要**重跑参数校验**，并返回一个**新构造**的 `PreparedToolCall` —— Hook 手里那份引用改不到后续执行。
