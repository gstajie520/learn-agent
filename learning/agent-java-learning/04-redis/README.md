# Redis 第三课：使用 Redis Hash 保存命令状态

## 这课到底是干什么的

上一课解决的是“同一条消息只能抢到一次执行权”。这一课解决另一个实际问题：命令执行到一半时，其他服务或另一台机器如何查询它现在是什么状态。

阶段 3 里的状态原来放在：

```java
ConcurrentHashMap<String, CommandRecord>
```

这只能被当前 Java 进程看到。程序重启后状态会丢失，第二台机器也查不到第一台机器的命令。现在把一条命令保存为 Redis Hash：

```text
agent:command:state:cmd-001
  commandId   = cmd-001
  instruction = 生成机场场景预览
  status      = PENDING
  result      =
```

这样，Java 服务、MQ 消费者和查询接口都可以通过同一个 `commandId` 访问共享状态。

## 为什么使用 Hash

一条命令有多个相关字段。Hash 可以把这些字段放在同一个 Redis key 下，读取时一次拿回：

```text
HSET agent:command:state:cmd-001 commandId cmd-001 instruction "生成预览" status PENDING result ""
HGETALL agent:command:state:cmd-001
EXPIRE agent:command:state:cmd-001 86400
```

这里不要把 Hash 误解成 Java 的 `HashMap`：

- Java `HashMap` 只存在当前进程内；
- Redis Hash 存在独立 Redis 服务中，多个 Java 进程可以访问；
- Hash 适合一组字段，`SET` 更适合一个完整字符串或 JSON；
- 重要业务结果仍建议写数据库，Redis 更适合当前状态、缓存和短期协调。

## 完整业务流程

```text
POST /commands
      ↓
Java 生成 commandId，Redis Hash 保存 PENDING
      ↓
后台任务执行并更新 RUNNING / SUCCEEDED / FAILED
      ↓
GET /commands/{commandId}
      ↓
从 Redis HGETALL 读取最新状态
```

## 概念示例：先看懂 15 行

```java
RedisCommandState state = new RedisCommandState(
        "cmd-001", "生成机场预览", "PENDING", "");

try (RedisCommandStateStore store = new RedisCommandStateStore()) {
    store.save(state);
    RedisCommandState saved = store.find("cmd-001");
    System.out.println(saved.getStatus());
}
```

逐行理解：

1. `RedisCommandState` 是一条命令的四个字段，不是复杂框架对象。
2. `save` 把字段写入 Redis Hash，并设置 24 小时 TTL。
3. `find` 执行 `HGETALL`，把 Redis 返回的 Map 还原成 Java 对象。
4. `try` 结束时关闭 Redis 连接，避免连接泄漏。

## 为什么保存时使用 MULTI/EXEC

保存状态需要做三件事：删除旧 Hash、写入新字段、设置 TTL。如果只完成前两步，key 可能没有过期时间；如果只写入部分字段，查询结果也可能不完整。本课用 Redis 事务把这些命令放到同一批次提交：

```java
commands.multi();
commands.del(key);
commands.hset(key, fields);
commands.expire(key, 24 * 60 * 60);
commands.exec();
```

这不是数据库那种“失败自动回滚”的完整事务，而是让命令按顺序排队后一次提交。更复杂的并发更新还需要 Lua、条件更新或数据库事务。

## 可运行入口

如果 Redis 开启认证，先在当前 PowerShell 设置密码；不要把真实密码写进代码：

```powershell
$env:REDIS_PASSWORD = '你的本机 Redis 密码'
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 04-redis -am test
java -cp '04-redis/target/classes;04-redis/target/dependency/*' learn.agent.redis.RedisCommandStateDemo
```

如果没有认证密码但 Redis 没有开启认证，可以删除环境变量后运行。当前机器如果没有提供正确密码，真实连接测试会显示 `Blocked, not run`（测试跳过），这是环境未提供凭据，不代表代码已经验证通过。

主代码位于：

```text
04-redis/src/main/java/learn/agent/redis/RedisCommandState.java
04-redis/src/main/java/learn/agent/redis/RedisCommandStateStore.java
04-redis/src/main/java/learn/agent/redis/RedisCommandStateDemo.java
```

测试位于：

```text
04-redis/src/test/java/learn/agent/redis/RedisCommandStateStoreTest.java
```

测试按 Arrange / Act / Assert 阅读：

- Arrange：准备 Redis 连接和一条 `PENDING` 命令；
- Act：调用 `save`，再调用 `find` 和 `ttl`；
- Assert：验证四个字段一致，并确认 TTL 大于 0。

## 本课验收问题

1. 为什么阶段 3 的 `ConcurrentHashMap` 不能作为多实例命令状态？
2. Redis Hash 和普通 Redis String 分别适合保存什么？
3. 为什么命令状态也要设置 TTL？
4. `MULTI/EXEC` 在本课中解决了什么问题？它是不是失败自动回滚？
5. 为什么最终业务结果不能只放 Redis？

## 常见面试题

### 1. Redis Hash 和 String 怎么选择？

答题要点：多个字段需要单独读取或更新时用 Hash；整个对象整体读写时可以序列化成 JSON 放 String。选择要看访问方式，不是看到 Redis 就固定一种结构。

### 2. Redis Hash 能不能保证业务状态更新绝对正确？

答题要点：单条 Redis 命令通常是原子的，但“读取旧状态、判断、再写新状态”是多步操作时仍可能并发冲突。需要条件更新、Lua、版本号或数据库事务来保护关键状态。

### 3. 为什么保存命令状态时要设置 TTL？

答题要点：命令可能永远停在 `PENDING` 或 `RUNNING`，TTL 可以清理长期无效状态，控制 Redis 内存；TTL 不是业务历史数据的替代品。

### 4. Redis 的 `MULTI/EXEC` 是回滚事务吗？

答题要点：不是完整数据库事务。它把命令排队后按顺序执行，不能像数据库一样对执行中错误自动回滚；复杂条件逻辑需要 Lua 或其他持久化方案。

### 5. 命令状态为什么还要写数据库？

答题要点：Redis 适合快速查询、短期状态和协调，数据库更适合长期保存、审计和最终业务事实。Redis 过期或故障后，不能丢失已经成功的业务结果。

---

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

## 常见面试题

### 1. Redis 为什么可以用来做幂等？

答题要点：Redis 是多个服务实例都能访问的共享存储，并且 `SET NX` 可以原子地判断并写入 key；第一个消费者成功，重复消费者失败。

### 2. `SETNX` 和普通 `SET` 有什么区别？

答题要点：普通 `SET` 可能覆盖旧值；`SETNX` 只有 key 不存在时才写入，适合做抢占和去重。

### 3. 为什么幂等 key 需要 TTL？

答题要点：消费者可能在写入处理中状态后宕机；TTL 能让异常留下的锁最终释放，避免命令永久无法处理。TTL 太短又可能导致任务仍在执行时锁提前过期，需要按任务最长耗时设计。

### 4. Redis 能完全替代数据库吗？

答题要点：不能。Redis 适合快速状态、缓存和协调；数据库更适合长期业务事实、事务和审计。最终结果通常不能只放 Redis。

### 5. Redis 端口能连通，但客户端仍然报 `NOAUTH`，原因是什么？

答题要点：网络连通和身份认证是两件事；Redis 开启了密码或 ACL，需要通过安全配置提供凭据，不能把密码硬编码进代码。
