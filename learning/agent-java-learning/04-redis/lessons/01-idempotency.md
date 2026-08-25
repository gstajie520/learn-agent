# 第 1 课：SETNX、TTL 与幂等抢占

## 为什么学习

RabbitMQ 可能重新投递同一条消息。两个消费者如果只看各自 JVM 的内存，都会认为自己是第一次处理。Redis 的共享 key 加上 `SET NX EX` 可以让第一个消费者抢到执行权，重复消费者识别为重复消息。

## 最小示例

```java
RedisLikeStore store = new RedisLikeStore();
boolean first = store.setIfAbsent("claim:cmd-001", "PROCESSING", 600000);
boolean second = store.setIfAbsent("claim:cmd-001", "PROCESSING", 600000);
```

第一次返回 `true`，第二次返回 `false`。TTL 防止消费者宕机后锁永久存在。

## 代码与测试

- `src/main/java/learn/agent/redis/lesson01/RedisLikeStore.java`
- `src/main/java/learn/agent/redis/lesson01/IdempotencyService.java`
- `src/main/java/learn/agent/redis/lesson01/RedisIdempotencyDemo.java`
- `src/test/java/learn/agent/redis/lesson01/`

运行：

```powershell
Set-Location '.\learning\agent-java-learning'
mvn -o -pl 04-redis -am test
java -cp '04-redis/target/classes' learn.agent.redis.lesson01.RedisIdempotencyDemo
```

## 常见面试题

### 1. `SETNX` 成功和失败代表什么？

**参考答案：**成功表示当前消费者第一次写入这个幂等 key，获得继续执行业务的资格；失败表示 key 已经存在，通常说明消息被其他消费者处理过或正在处理。

**项目解决方案：**`IdempotencyService` 用 `agent:command:claim:{commandId}` 作为固定 key，调用 `RedisLikeStore.setIfAbsent()`；返回 `CLAIMED` 才执行后续业务，返回 `ALREADY_CLAIMED` 就直接 ACK 或结束处理。

**风险边界：**抢占成功不等于业务最终成功；消费者拿到锁后宕机，需要 TTL、重试和最终状态恢复策略。

### 2. 为什么必须设置 TTL？

**参考答案：**消费者可能在写入 `PROCESSING` 后宕机，如果没有 TTL，这个命令会永久被认为正在处理，后续重试无法恢复。

**项目解决方案：**写入幂等 key 时同时设置 TTL，并根据任务最长耗时选择时间；异常状态过期后，新的消费者可以再次抢占。

**风险边界：**TTL 太短会导致旧任务还在执行时锁已经过期，产生重复执行；TTL 太长则会延迟故障恢复。

### 3. 为什么 Java `ConcurrentHashMap` 不能做跨实例幂等？

**参考答案：**它只存在当前 JVM 的堆内存中，消费者 A 和消费者 B 即使使用相同 key，也看不到彼此的内存记录。

**项目解决方案：**把幂等 claim 放到所有实例都能访问的 Redis，并使用 `SET NX` 的原子条件写入。

**风险边界：**Redis 本身也可能故障或发生网络分区，因此生产系统还要设计超时、降级、监控和最终业务校验。
