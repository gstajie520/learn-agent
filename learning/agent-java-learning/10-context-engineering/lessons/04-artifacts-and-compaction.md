# 第 4 课：产物落盘与上下文压缩

## 这一课解决什么

前三课解决的是「避免把不必要的东西塞进上下文」：

- 第 1 课：计划不用增量，每次重读完整快照
- 第 2 课：探索过程挪出主对话
- 第 3 课：Skill 正文按需加载

但还有第四种膨胀，而且最难控：**工具结果本身很大**。

一次 `grep` 返回 50 KB，模型读完写进计划，下一轮这 50 KB 仍在上下文里。跑二十轮，上下文全是历史工具输出，预算耗尽。

本课的机制是**分层压缩**：

```text
工具结果 → 判断是否落盘 → 写文件 → 只回引用 + 预览
        ↓
      消息历史 → snip 压缩（头尾保留）→ micro 压缩（旧工具结果占位符）
        ↓
      仍超预算 → 模型生成摘要 → 摘要 + 最近几组消息
```

## 一、工具结果落盘：大结果写文件，只回引用

**单个工具结果超过阈值时，正文写入 artifact 文件，消息只保留引用和预览。**

```java
if (result.getBytes(UTF_8).length > persistThresholdBytes) {
  String path = writeArtifact("tool-result", id, content);
  String preview = renderPreview(path, content, headBytes, tailBytes);
  return toolSuccess(preview); // 只回引用，不回全文
}
```

### 为什么不能直接删掉

删掉等于告诉模型「工具没跑」或「结果是空的」，下一轮它会重新调用。

正确做法：**告诉模型结果已落盘、在哪、多大、头尾预览是什么**，它需要时可以主动 `read_file` 重新读取。

### 批次预算

同一轮返回多个工具结果时，不是逐个独立判断，而是**按总预算做"最大优先"批次选择**：

```java
// 按大小倒序排列
List<Integer> ranked = rankBySize(results);
Set<Integer> selected = new HashSet<>();
int retained = 0;

for (int index : ranked) {
  if (retained <= batchBudgetBytes) break;
  if (sizes[index] > persistThresholdBytes) {
    selected.add(index);
    retained -= sizes[index];
  }
}
```

**为什么要批次预算**：如果只看单个阈值，10 个 25 KB 的结果全部留在上下文（每个都没超 30 KB），总共 250 KB，照样爆预算。

## 二、snip 压缩：保留头尾，插入省略标记

消息按**消息组**划分：
- 普通消息单独成组
- assistant 工具调用 + 其全部 tool 结果是一组（不可拆分）

**snip 压缩保留头部 N 组、尾部 M 组，中间插入省略标记**：

```java
if (groups.size() > maxGroups) {
  List<MessageGroup> head = groups.subList(0, keepHeadGroups);
  List<MessageGroup> tail = groups.subList(groups.size() - keepTailGroups, groups.size());
  MessageGroup marker = systemMessage("[Compacted: " + omitted + " groups omitted]");
  return flatten(head, marker, tail);
}
```

### 为什么要以组为单位

**绝不能拆散 assistant 工具调用与 tool 结果的配对。** OpenAI 协议要求：

```text
assistant (toolCalls=[id1, id2])
tool (id1, content)
tool (id2, content)
```

如果 snip 在中间切一刀，只留 `assistant` 和第一个 `tool`，第二个 `tool (id2)` 丢了 → `validateToolPairing` 报错 `missing tool result for id: id2`。

## 三、micro 压缩：旧工具结果替换成占位符

保留最近 N 组工具交换，其余工具结果正文替换成固定占位符：

```java
String COMPACTED = "[Earlier tool result compacted. Re-run if needed.]";

for (MessageGroup group : oldToolGroups) {
  AssistantMessage assistant = group.getAssistant();
  List<ToolMessage> tools = group.getTools().stream()
    .map(tool -> toolMessage(COMPACTED, tool.getToolCallId()))
    .collect(toList());
  return new MessageGroup(assistant, tools);
}
```

**关键**：
- **保留 `tool_call_id`**，不破坏配对
- **保留 assistant 调用消息**，模型知道曾经调过什么
- 只替换 tool 消息的 `content`

## 四、summary 压缩：模型生成结构化摘要

当上面三层仍不够时，调用模型生成**结构化 JSON 摘要**：

```java
String SUMMARY_PROMPT = """
  请将当前 Agent 历史压缩为一个 JSON object。
  只能返回 JSON，不得调用工具。JSON 必须且只能包含：
  current_goal: 非空字符串；
  key_findings: 字符串数组；
  files_read_or_changed: 字符串数组；
  remaining_work: 字符串数组；
  user_constraints: 字符串数组。
  """;
```

摘要请求**不携带工具定义**，模型 `finishReason` 必须是 `stop`，输出必须是严格五字段 JSON。

### 为什么摘要必须结构化

如果让模型自由发挥写一段话，下一轮它读到的是**自己写的话**，而不是**可查询的字段**。

结构化摘要的好处：
- `files_read_or_changed` 可以直接映射成工作区快照
- `remaining_work` 可以和计划对比
- `user_constraints` 可以在每次裁决前重读

### 摘要后保留尾部

摘要不是全部替换，而是 **摘要 + 最近几组消息**：

```java
List<ChatMessage> history = new ArrayList<>();
history.add(summaryMessage(summary, transcriptPath));
history.addAll(flattenGroups(groups.subList(groups.size() - keepTailGroups, groups.size())));
return history;
```

**为什么要留尾部**：只有摘要的话，模型看不到最近的进展，会重复已经做过的事。

## 五、`validateToolPairing`：压缩的安全边界

**任何压缩之后都必须跑一遍 `validateToolPairing`**，确保没有压断配对：

```java
public static void validateToolPairing(List<ChatMessage> messages) {
  Set<String> pending = new HashSet<>();
  
  for (ChatMessage message : messages) {
    if (!pending.isEmpty()) {
      if (message.getRole() != Role.TOOL) {
        throw new MessageContractException("missing tool results for ids: " + pending);
      }
      if (!pending.remove(((ToolMessage) message).getToolCallId())) {
        throw new MessageContractException("unexpected tool result id");
      }
      continue;
    }
    
    if (message.getRole() == Role.TOOL) {
      throw new MessageContractException("orphan tool result");
    }
    if (message.getRole() == Role.ASSISTANT) {
      AssistantMessage assistant = (AssistantMessage) message;
      for (ToolCall call : assistant.getToolCalls()) {
        pending.add(call.getId());
      }
    }
  }
  
  if (!pending.isEmpty()) {
    throw new MessageContractException("missing tool results for ids: " + pending);
  }
}
```

### 三种非法状态

1. **孤儿 tool**：`pending` 为空时遇到 tool 消息
2. **缺失 tool**：`pending` 非空但下一条不是 tool
3. **ID 不匹配**：tool 消息的 ID 不在 `pending` 里

## 六、artifact 路径安全

所有 artifact 必须落在固定目录 `.agent_tutorial/artifacts/` 下：

```java
Path artifactDir = workspace.resolve(".agent_tutorial/artifacts");
Files.createDirectories(artifactDir);

// artifact ID 必须是安全 slug
if (!ARTIFACT_ID_PATTERN.matcher(id).matches()) {
  throw new ArtifactPathException("invalid artifact id");
}

Path path = artifactDir.resolve("tool-result-" + id + ".txt");
// 写入后重新检查真实路径
Path real = path.toRealPath();
if (!real.startsWith(workspace.toRealPath())) {
  throw new ArtifactPathException("artifact escapes workspace");
}
```

**为什么要二次检查**：写入后目录可能被替换成符号链接，`toRealPath()` 解析链接后再判断前缀。

## 七、压缩的四个预算参数

| 参数 | 默认值 | 用途 |
|---|---:|---|
| `persistThresholdBytes` | 30,000 | 单个工具结果超过此值优先落盘 |
| `batchBudgetBytes` | 200,000 | 同一轮结果留在上下文的总预算 |
| `snipMaxGroups` | 50 | 消息组超过此数量触发 snip 压缩 |
| `proactiveThresholdBytes` | 50,000 | 请求历史超过此值触发主动摘要 |

**为什么有两套字节预算**：
- `persistThresholdBytes` 针对单个结果：一个 100 KB 的日志必须落盘
- `batchBudgetBytes` 针对整轮总和：10 个 25 KB 的结果也要落盘几个

## 八、Java 域的一个取舍

教材的 `CompactionManager` 是一个有状态的类，持有 `#preparedSource` 和 `#preparedHistory` 缓存。

**Java 侧暂不实现缓存**，原因：
- 缓存的收益是「纯追加时只压缩新增后缀」
- 代价是管理两个可变字段 + `historiesEqual` 比较逻辑
- 阶段 9 第 4 课的重点是**压缩机制本身**，不是缓存优化

所以 Java 的 `prepare` 每次都从头压缩，不判断 `cachedSource`。

## 常见面试题

### 1. 为什么工具结果落盘后不能直接删掉，要留引用和预览？

**答**：删掉等于告诉模型「结果是空的」，下一轮它会重新调用。正确做法是告诉模型：结果已落盘、在哪个路径、多大、头尾预览是什么。模型需要时可以主动 `read_file` 重新读取。

**为什么重要**：如果每次都重跑工具，一个慢查询会在每一轮都执行一次，耗时和费用都无法接受。

### 2. 为什么压缩必须以消息组为单位，不能按字节位置切？

**答**：OpenAI 协议要求 assistant 工具调用后必须紧随对应数量的 tool 消息。如果在中间切一刀，`assistant (toolCalls=[id1, id2])` 和 `tool (id1)` 留下，`tool (id2)` 丢了，`validateToolPairing` 会报 `missing tool result for id: id2`。

**为什么重要**：协议违规会导致模型调用直接失败，不是「效果不好」，是「请求被拒」。

### 3. micro 压缩时为什么要保留 `tool_call_id`？

**答**：`tool_call_id` 是 assistant 调用与 tool 结果配对的唯一键。压缩时只替换 `content` 为占位符，`toolCallId` 必须保留，否则 `validateToolPairing` 会报 `unexpected tool result id`。

**为什么重要**：模型看到的历史必须始终满足协议约束，压缩不能破坏这条边界。

### 4. 为什么摘要必须是结构化 JSON，不能让模型自由发挥？

**答**：自由文本的话，下一轮模型读到的是「自己写的一段话」，无法可靠提取出「改了哪些文件」「还有哪些任务」。结构化摘要有固定字段，可以直接查询 `files_read_or_changed` 和 `remaining_work`。

**为什么重要**：压缩后的摘要是模型恢复上下文的唯一依据，字段缺失或格式错误会让模型失去方向。

### 5. 为什么 artifact 路径要二次检查 `toRealPath()`？

**答**：写入后目录可能被替换成符号链接。只检查写入前的路径挡不住「先通过、后替换」的 TOCTOU 攻击。`toRealPath()` 解析符号链接后再判断前缀，确保最终文件真的在 workspace 下。

**为什么重要**：如果 artifact 目录被链接到 `/etc`，模型调用 `write_artifact` 可能覆盖系统配置文件。

### 6. 为什么批次预算要"最大优先"而不是"先到先得"？

**答**：如果按顺序处理，前 8 个小结果留在上下文（每个 20 KB），第 9 个大结果（80 KB）才落盘。但总预算是 200 KB，8×20 = 160 KB 已经占了大半。正确做法：先落盘最大的几个，让更多小结果留在上下文。

**为什么重要**：小结果通常是状态确认（`{"status":"ok"}`），大结果通常是数据转储（日志、文件内容）。优先落盘大结果可以让模型看到更多次操作的结局，而不是只看到少数几个大块。

### 7. 为什么摘要后还要保留尾部几组消息？

**答**：只有摘要的话，模型看不到最近的进展，会重复已经做过的事。保留尾部几组（例如最近 5 组）让模型既有全局摘要，又能看到刚刚发生了什么。

**为什么重要**：压缩的目标不是「尽可能删」，是「在预算内保留最有用的信息」。最近的进展通常比遥远的历史更有用。

## 验收题

完成本课后，你应该能回答：

1. 为什么工具结果落盘后不能直接删掉？引用消息里必须包含哪些信息？
2. `validateToolPairing` 能检测出哪三种非法状态？每种对应什么场景？
3. micro 压缩时哪些字段必须保留、哪些可以替换？
4. 摘要请求为什么不携带工具定义？如果模型输出了工具调用会怎样？
5. 为什么 snip 压缩必须以消息组为单位，不能按字节位置切？
6. artifact 路径检查为什么要在写入后再跑一次 `toRealPath()`？
7. 批次预算的"最大优先"策略解决了什么问题？
8. 摘要后为什么要保留尾部几组消息，而不是只留摘要？
