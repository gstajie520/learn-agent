# 第 3 课：Redis Hash 保存命令状态

## 为什么学习

命令状态有 `commandId`、`instruction`、`status`、`result` 多个字段。把它们放进 Redis Hash 后，Java 服务和多个消费者都能根据 commandId 查询共享状态。

## Redis 结构

```text
agent:command:state:cmd-001
  commandId   = cmd-001
  instruction = 生成预览
  status      = PENDING
  result      =
```

## 代码与测试

- `src/main/java/learn/agent/redis/lesson03/RedisCommandState.java`
- `src/main/java/learn/agent/redis/lesson03/RedisCommandStateStore.java`
- `src/main/java/learn/agent/redis/lesson03/RedisCommandStateDemo.java`
- `src/test/java/learn/agent/redis/lesson03/RedisCommandStateStoreTest.java`

核心命令是 `HSET`、`HGETALL`、`EXPIRE`。Hash 适合一组字段；整个对象整体读写时也可以使用 String + JSON。

## 常见面试题

### 1. Hash 和 String 怎么选？

**参考答案：**多个字段需要单独读取或更新时使用 Hash；整个对象整体序列化、整体读写时可以使用 String 加 JSON。选择取决于访问方式和字段更新粒度。

**项目解决方案：**命令状态用 Hash 保存 `commandId`、`instruction`、`status`、`result`，查询时用 `HGETALL` 还原 Java 对象。

**风险边界：**Hash 不是自动的对象版本控制；并发更新多个字段时仍需条件更新、Lua 或版本号。

### 2. 为什么状态也设置 TTL？

**参考答案：**命令可能长期停在 `PENDING` 或 `RUNNING`，TTL 可以清理无效状态，避免 Redis 内存无限增长。

**项目解决方案：**保存 Hash 时同时设置 24 小时 TTL，并在最终结果需要长期保存时写入数据库。

**风险边界：**TTL 到期后查询不到状态，不能把 Redis 过期当成业务历史归档；重要结果必须有可靠持久化。

### 3. Redis 能替代数据库吗？

**参考答案：**不能。Redis 适合快速状态、缓存和服务协调，数据库更适合长期业务事实、事务和审计。

**项目解决方案：**Redis 保存当前命令状态和短期查询数据，最终业务结果、操作记录和审计信息由数据库保存。

**风险边界：**只写 Redis 不写数据库会造成 Redis 过期或故障后业务事实丢失。
