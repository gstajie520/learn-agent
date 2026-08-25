# 第 5 课：缓存读写、穿透、击穿、雪崩

## 为什么学习

命令查询接口会被反复调用。第一次查询慢数据源，后续请求可以直接从 Redis 返回。缓存只负责加速，数据库仍是最终业务事实。

## 基本流程

```text
先查 Redis
  ├─ 有值：直接返回
  └─ 没值：查询数据源 → 写入 Redis → 返回
```

不存在的 commandId 也短暂缓存空值标记，避免无效请求持续打到数据库。单 JVM 示例用 `synchronized` 和二次检查降低热点 key 击穿；多个实例仍需要分布式锁或其他协调方案。

## 代码与测试

- `src/main/java/learn/agent/redis/lesson05/CommandCacheClient.java`
- `src/main/java/learn/agent/redis/lesson05/SpringRedisStringCacheClient.java`
- `src/main/java/learn/agent/redis/lesson05/CommandCacheService.java`
- `src/main/java/learn/agent/redis/lesson05/CommandCacheDemo.java`
- `src/test/java/learn/agent/redis/lesson05/CommandCacheServiceTest.java`

运行入口：

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 04-redis -am package -DskipTests
java -cp '04-redis/target/classes;04-redis/target/dependency/*' learn.agent.redis.lesson05.CommandCacheDemo
```

## 三个常见问题

- 穿透：查询不存在的数据，空值缓存、参数校验可以缓解；
- 击穿：热点 key 过期，大量请求同时回源，互斥或逻辑过期可以缓解；
- 雪崩：大量 key 同时过期或 Redis 故障，TTL 抖动、预热、限流和降级可以缓解。

写数据库成功后通常删除相关缓存，避免继续返回旧值。

## 常见面试题

### 1. 穿透、击穿、雪崩的区别是什么？

**参考答案：**穿透是大量请求查询本来不存在的数据；击穿是一个热点 key 过期后大量请求同时回源；雪崩是大量 key 同时失效或 Redis 故障，导致整体请求回源。

**项目解决方案：**本课用空值缓存缓解穿透，用单 JVM `synchronized` 和二次检查缓解击穿，并在概念上介绍 TTL 抖动、预热、限流和降级应对雪崩。

**风险边界：**单 JVM 锁无法保护多个服务实例；Redis 故障时还需要降级和数据源保护。

### 2. 为什么缓存空值？

**参考答案：**不存在的 id 如果不缓存，每次请求都会因为 Redis 没命中而访问数据库，形成缓存穿透；短 TTL 空值标记可以挡住重复无效请求。

**项目解决方案：**`CommandCacheService` 使用 `__CACHE_NULL__` 作为空值标记，并使用比正常数据更短的 TTL。

**风险边界：**空值 TTL 太长时，真实数据创建后仍可能被暂时认为不存在；还需要限制可疑参数和访问频率。

### 3. 为什么 `synchronized` 不能保护多个实例？

**参考答案：**每个 JVM 都有自己的锁对象，实例 A 加锁时实例 B 不会等待，因此多个实例仍可能同时回源。

**项目解决方案：**单实例学习代码用 `synchronized` 看懂二次检查；生产多实例使用 Redis 分布式锁、逻辑过期或提前刷新。

**风险边界：**分布式锁也需要 TTL、续期、故障释放和锁误删保护，不能只加一个 `SETNX` 就结束。

### 4. 为什么 TTL 要增加随机抖动？

**参考答案：**如果大量 key 在同一时间写入并设置相同 TTL，它们可能同时过期，把请求集中打到数据库；随机抖动可以把过期时间分散开。

**项目解决方案：**生产写缓存时在基础 TTL 上增加一个小随机值，并配合预热、限流和监控。

**风险边界：**TTL 抖动只能降低同时失效概率，不能解决 Redis 故障或单个热点 key 的击穿。
