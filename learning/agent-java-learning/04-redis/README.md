# Redis 第二课：使用真实 Redis 保存幂等状态

## 这课到底是干什么的

上一课的 `RedisLikeStore` 只是为了看懂 SETNX 和 TTL。这一课真正连接本机 Redis，学习 Java 客户端如何发送 Redis 命令。

真实链路是：

```text
Java 消费者
    ↓ Lettuce 客户端
Redis 服务（127.0.0.1:6379）
    ↓
多个 Java 进程共享同一条 commandId 幂等记录
```

上一课的命令状态保存在：

```java
ConcurrentHashMap<String, CommandRecord>
```

它只能在当前 JVM 内可见。如果 Java 服务部署了两个实例：

```text
消费者 A 的内存：没有 cmd-001
消费者 B 的内存：也没有 cmd-001
```

同一个 RabbitMQ 消息重新投递时，两个实例都可能认为自己是第一次处理。

Redis 提供一个共享的、支持原子写入的边界。常用的幂等动作是：

```text
SET key value NX EX 600
```

含义：只有 key 不存在时才写入，并设置 600 秒过期时间。

```text
第一次消费者：SETNX 成功 → 可以执行
第二次消费者：SETNX 失败 → 识别为重复消息
```

本课保留 `RedisLikeStore` 离线模拟，同时新增 `RealRedisIdempotencyStore` 连接真实 Redis。

## 概念示例：先看懂 15 行

```java
RedisLikeStore store = new RedisLikeStore();
String key = "agent:command:claim:cmd-001";

boolean first = store.setIfAbsent(key, "PROCESSING", 600000);
boolean second = store.setIfAbsent(key, "PROCESSING", 600000);

System.out.println(first);  // true：第一次抢占成功
System.out.println(second); // false：重复消息被拦截
```

逐行理解：

1. `store`：本课对 Redis 的最小模拟。
2. `key`：使用固定前缀和 `commandId` 生成幂等 key。
3. 第一次 `setIfAbsent`：key 不存在，写入成功。
4. 第二次 `setIfAbsent`：key 已存在，写入失败。
5. `600000`：600 秒 TTL，防止服务异常后锁永久存在。

## 完整业务流程

```text
RabbitMQ 投递 commandId=cmd-001
        ↓
Java 消费者生成 agent:command:claim:cmd-001
        ↓
Redis SETNX + TTL
        ├─ 成功：当前消费者执行业务
        └─ 失败：重复消息，直接 ACK，不重复执行
```

## 运行教学入口

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 04-redis -am test
java -cp '04-redis/target/classes' learn.agent.redis.RedisIdempotencyDemo
```

预期输出：

```text
第一次消费消息：CLAIMED
Redis 中记录的状态：PROCESSING
重复消费消息：ALREADY_CLAIMED
结论：同一个 commandId 只有第一次消费可以继续执行
```

## RedisLikeStore 和真实 Redis 的差异

| 本课模拟 | 真实 Redis |
|---|---|
| 当前 JVM 的对象 | 独立 Redis 服务，多个 JVM 共享 |
| `synchronized` 保证本进程原子性 | Redis 命令本身提供原子执行 |
| 进程重启数据丢失 | 可配置持久化和高可用 |
| 只用于理解 SETNX/TTL | 可用于状态、幂等、缓存和 checkpoint |

本课使用 Lettuce 直接连接 Redis，先看懂客户端如何执行命令；后续 Spring Boot 集成课再使用 `StringRedisTemplate`。业务规则不变：幂等 key、原子抢占、TTL 和失败恢复必须同时设计。

## 真实 Redis 示例

```java
try (RealRedisIdempotencyStore store = new RealRedisIdempotencyStore()) {
    // 第一次 SET NX 成功，表示抢到执行权。
    boolean first = store.setIfAbsent(
            "agent:command:claim:cmd-001",
            "PROCESSING",
            60
    );

    // 第二次 SET NX 失败，表示重复消息。
    boolean second = store.setIfAbsent(
            "agent:command:claim:cmd-001",
            "PROCESSING",
            60
    );
}
```

`RealRedisIdempotencyStore` 内部执行的就是：

```text
SET agent:command:claim:cmd-001 PROCESSING NX EX 60
```

## 真实 Redis 教学入口

确认本机 `127.0.0.1:6379` 已启动。如果 Redis 开启了密码认证，先在当前 PowerShell 设置环境变量：

```powershell
$env:REDIS_PASSWORD = '你的本机 Redis 密码'
```

密码只放在运行环境中，不能写入 Java 源码、README 示例真实值或 Git。

然后执行：

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 04-redis -am test
```

真实连接测试会自动使用 Lettuce：

- Redis 不可用：跳过真实连接测试；
- Redis 开启认证但没有设置 `REDIS_PASSWORD`：跳过并提示；
- Redis 和密码均可用：执行真实 `SET NX EX` 测试。

离线模拟测试始终执行。

## 重要风险

- 只写 Redis、业务写数据库可能出现两边不一致；
- TTL 太短，锁过期后同一命令可能再次执行；
- TTL 太长，消费者崩溃后任务可能长时间无法恢复；
- `PROCESSING` 不能永远代表成功，最终结果仍应保存到数据库或可靠业务存储；
- 重复消息被识别后要 ACK，否则 MQ 会一直重复投递。

## 验收问题

1. 为什么两个 Java 实例各自的 `ConcurrentHashMap` 不能做幂等？
2. `SETNX` 的成功和失败分别代表什么？
3. 为什么幂等 key 需要 TTL？
4. Redis 记录为 `PROCESSING` 后，Java 进程突然宕机，恢复时需要考虑什么？
5. 为什么真实 Redis 连接使用完必须关闭？
