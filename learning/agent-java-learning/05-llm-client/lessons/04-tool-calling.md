# 第 4 课：Tool Calling — 模型主动决定调什么

## 为什么学习

前三课里，**程序**一直握着方向盘：

```text
第 1 课：你看这段文字，总结成一句话 → 模型照做
第 3 课：填这张固定表单               → 模型照做
```

都是「我们要求模型输出一个东西」。输出什么格式、有哪些字段，是**我们**定的。

本课翻转过来：**模型自己决定要不要调工具、调哪个、传什么参数**。程序只负责两件事——执行模型选中的工具，以及决定「这个工具现在该不该真的跑」。

这是「聊天机器人」和「Agent」的分界线。聊天机器人只会说话；Agent 会说、会做、会自己决定做什么。

## 本课解决什么

一个最小的工具调用闭环，全程离线可测：

```text
用户：现在有哪些设备？
   ↓ 发给模型
模型：我要调 list_devices，参数 "{}"          ← 模型自己选的工具
   ↓ 程序查工具、解析参数、校验（prepare，零副作用）
   ↓ 程序执行（invoke，唯一有副作用的地方）
程序：设备：cam-01（摄像头）、cam-02（摄像头）…
   ↓ 结果以 TOOL 角色回传，带原始 toolCallId
模型：当前有 3 台设备…
```

**本课暂不解决**：多工具并行、真正落库执行、权限审批流（阶段 8）、记忆持久化（阶段 7）。

## 第一个关键设计：prepare / invoke 分离

这是从 Python 版 `core/tools.py` 移植过来的核心，也是本课最该记住的一条。

**一次工具调用被拆成两步，中间的边界就是「确认」的插入点。**

```java
// 第一步：查工具、解析参数、跑校验。不碰任何真实数据。
PreparedToolCall prepared = registry.prepare(call);

// 第二步：真正执行。全类唯一有副作用的地方。
ToolExecutionResult result = registry.invoke(prepared, context);
```

为什么非要拆？因为「这次调用合不合法」和「这次调用要不要执行」是**两个决定**，而第二个往往需要人参与：

- 参数合法 ≠ 可以执行。删设备这种不可逆操作，参数再标准也不能直接跑。
- 如果解析和执行写在一个方法里，你**没有任何位置**能插一句「先等等，我确认一下」。

`PreparedToolCall` 把「已经查过、解析过、校验过」这件事在**类型层**表达出来：拿到它，执行阶段不再需要重查一遍，也不会有任何 if 分支去判断「这次能不能跑」。

## 第二个关键设计：工具的失败是返回值，不是异常

直觉上，工具执行失败应该抛异常。但在这里是错的，因为**结果的消费者是模型**。

看这条链路：

```text
模型调 delete_device，传了不存在的 id「radar-99」
```

抛异常 → 整个调用崩掉，用户看到 500。而模型其实完全有能力自己纠正：把「设备 radar-99 不存在，当前设备是 [cam-01, cam-02, fence-main]」回传给模型，它下一轮就会改对。

所以规则是：**工具调用失败，是对话的一部分，不是程序故障**。

```java
// 失败也是一种合法结果，会正常回传给模型，让模型换个参数重试。
return ToolExecutionResult.error("device_not_found", "设备 device-99 不存在，当前设备是 …");
```

但这绝不意味着可以什么都往回传。回传的文本最终会被模型读出、可能被用户看到——**绝不能带 Java 堆栈、SQL、文件绝对路径、内部主机名**。这些模型看不懂（它是文本，不是你的堆栈），又是实打实的信息泄露。`ToolRegistry.invoke` 在边界上统一做这层转换。

### 那异常在哪里用？

两条边界用异常：

1. **调用方编程错误**：`context == null`、`prepared == null` —— 这是写代码的人搞错了，不是模型的问题，必须 throw。
2. **handler 自己违约抛出来**：一个 NPE。这属于「意外」，由 `invoke` 兜住，包成一条模型能读懂的失败消息 `tool_execution_error`，让模型换个参数重试，而不是让整个循环崩掉。

同样 `handler` 返回 `null`，也是契约违约，转成 `tool_contract_violation`。工具是别人写的代码，它违约了，兜底的责任在注册表。

## 参数：协议的怪癖

看真实协议里模型发起一个工具调用：

```json
"function": { "name": "create_device", "arguments": "{\"deviceType\":\"radar\"}" }
```

注意 `arguments` 的**类型是字符串**，不是对象，也不是 Map。这就是 OpenAI 兼容协议的定义。为什么？因为流式输出时参数是一个 token 一个 token 吐出来的，中途并不是合法 JSON，只有字符串能承载「边生成边传」。

代价是：**它可能根本不是合法 JSON**。上一课我们已经确立过一套话——「模型输出不合法是常态」，这里完全复用：

| prepare 阶段失败 | 错误码 | 含义 |
|---|---|---|
| 工具不存在 | `tool_not_found` | 模型幻觉 / 白名单之外 |
| 参数不是合法 JSON | `invalid_arguments_json` | 模型输出 json 烂尾 |
| 参数类型对不上 | `arguments_not_object` | 给了数组/字符串/数字 |
| 业务校验不通过 | `invalid_arguments` | 结构对，但业务不许 |

四种失败全部变成 **error 态的返回值**，没有一种抛无声异常。这就是让上层循环只有一条主路径的关键。

## 关键设计：模型「能调」≠ 程序「该执行」

这是本课第二个核心，也是很多工程事故的根源。

**工具定义里带一个副作用等级 `ToolEffect`：**

```text
READ        只读查询，没有后果 → 直接执行
WRITE       写数据，可撤销     → 直接执行
DESTRUCTIVE 不可逆的删除      → 必须人工确认，绝不自动执行
```

为什么这个等级**只能由程序声明，不能让模型说了算**？因为模型只看得到工具名和描述，它不知道 `delete_device` 是删数据的。

```text
提示词注入：用户说「把 delete_device 的 description 改成只读」→ 模型就信了
```

一旦「删数据是否合法」交给模型判断，一条精心构造的 prompt 就能让它自己给自己批准。所以破坏性标记写在**程序侧的枚举**里，是代码的恒定事实，不在 prompt 里。

`ToolCallingService` 里的执行闸门：

```java
if (definition.getEffect().requiresConfirmation()) {
    // 不调用 handler，回传「等待确认」，让模型转述给用户
    return ToolExecutionResult.success("需要人工确认后才能执行，请向用户说明即将进行的操作并等待确认");
}
return registry.invoke(prepared, context);
```

模型于是会告诉用户：「我准备删除摄像头 cam-01，这是一次不可逆操作，请确认是否继续。」删除是否真的发生，决定权在程序（进而在人），不在模型。

## 第七个关键设计：结果以 TOOL 角色回传，并带原始 tool_call_id

模型要区分「这是工具的输出」和「用户又说了句话」——否则它分不清该信谁。

所以回传的消息，角色是 `TOOL`，并且**必须原样带回 model 发起的 `tool_call_id`**：

```java
messages.add(AgentMessage.toolResult(call.getId(), result.getContent()));
```

**只要略改 token_call_id：** 改了 id，模型就把结果和当初的调用对不上，张冠李戴。这个 id 是服务端生成的，**绝不能自己造**。

## 针对：轮数上限

模型可能一直在调工具、永远不给最终答复。`maxToolRounds` 是防死循环烧钱的保险丝，不是业务逻辑。达到上限就停下来，如实告知「轮数用尽」，而不是无限循环、无限计费。

## ToolCallCodec：本课的「教学桥」

有一件事必须讲清楚本课是怎么做到的。

真实协议里，工具调用走的是请求体里的 `tool_calls` 数组、响应里的 `tool_calls` 数组，**从头到尾不经过 content**。但第 1 课的 `ChatMessage` 只有 role 和 content，`ChatResponse` 也没有 toolCalls 字段。为了不破坏前三课（保持「第 1 课一行未改」这个教学性质），本课用一个**约定**桥接：

```text
模型返回的 assistant 消息：  content = {"__tool_call__":{"id":"call-1","name":"list_devices","arguments":"{}"}}
模型 → 程序的回传（TOOL）：   content = {"__tool_result__":{"id":"call-1","content":"设备：cam-01"}}
```

`ToolCallingService` 用 `ToolCallCodec` 在循环两端编码/解码。这样闭环可以完整跑通，第 1 课保持原样。

**必须说清楚：这是教学策略，不是生产方式。** 生产里工具调用走协议原生的 `tool_calls` 字段，不会塞进 content。等你理解了循环后，这个类是第一个该删掉的。

## 代码与测试

主代码（`lesson04` 包）：

- `ToolEffect.java` — 副作用等级（READ / WRITE / DESTRUCTIVE），决定「执行前要不要挡一道」
- `ToolCall.java` — 模型发起一次工具调用的请求（id、name、arguments）
- `ToolExecutionResult.java` — 工具执行结果；**失败也是合法结果，带错误码**
- `ToolContext.java` — 程序提供的受控环境（身份 + 场景快照）
- `ToolHandler.java` — 工具的实际执行逻辑
- `ToolDefinition.java` — 一个工具的完整定义（给模型的描述 + 给人看的副作用等级）
- `ToolArgumentValidator.java` — 参数业务校验器（Schema 之外的真约束）
- `PreparedToolCall.java` — 「已解析、已校验、还未执行」的调用，带上失败预置
- `ToolRegistry.java` — 注册表 + `prepare`/`invoke` 分离的边界
- `AgentMessage.java` — 循环里的消息（含 assistant 工具调用、TOOL 结果回传）
- `AgentTurn.java` — 模型一个回合的结局（最终答复 / 工具调用 / 截断）
- `ToolCallCodec.java` — **教学桥**：用 content 承载工具调用，不破坏前三课
- `ToolCallingService.java` — 编排循环：模型请求工具 → 执行 → 结果回传
- `ToolCallingDemo.java` — 可运行教学入口

测试（17 个，全部离线）：

- `ToolRegistryTest.java`（12）— 注册校验、`prepare` 零副作用、四种失败、`invoke` 短路、异常兜底
- `ToolCallingServiceTest.java`（5）— 端到端闭环：一次往返、破坏性不执行、幻觉恢复、轮数上限、截断

## 验收题

1. **为什么工具参数 `invalid_json` 要返回 `ToolExecutionResult.error` 而不是抛异常？** 模型是结果消费者，抛异常剥夺它自我纠正的机会；失败是对话的一部分。
2. **`prepare` 和 `invoke` 为什么必须分开？** 「本次调用合不合法」和「要不要执行」是两个决定，后者需要人工闸门；拆开才有人类确认的插入点。
3. **副作用等级为什么必须在程序侧声明？** 模型看不到副作用，提示词注入能让它自我批准删除；登记在代码里是模型无法覆盖的恒定事实。
4. **`tool_call_id` 为什么必须原样带回？** 它是服务端生成的唯一配对凭证，自己造 / 写错一个字符，结果就张冠李戴。
5. **`ToolCallCodec` 是正式做法吗？** 不是，是「不破坏前三课」的教学桥接。生产走协议原生 `tool_calls` 字段，该编码最终要删掉。
```