# 第 4 课：Spring Redis 与 Lua 条件更新

## 为什么学习

“先查状态，再在 Java 中判断，再写回 Redis”存在并发空隙。两个消费者可能同时读到 `PENDING`，导致旧判断覆盖新状态。本课使用 `StringRedisTemplate` 和 Lua，把检查与更新放在 Redis 内一次执行。

## 最小示例

```text
如果 status == PENDING
    更新为 RUNNING，返回 1
否则
    不更新，返回 0
```

返回 `false` 通常表示另一个消费者已经先完成更新，不一定是系统异常。

## 代码与测试

- `src/main/java/learn/agent/redis/lesson04/SpringRedisConfig.java`
- `src/main/java/learn/agent/redis/lesson04/SpringRedisCommandStateStore.java`
- `src/main/java/learn/agent/redis/lesson04/SpringRedisCommandStateService.java`
- `src/main/java/learn/agent/redis/lesson04/SpringRedisCommandDemo.java`
- `src/test/java/learn/agent/redis/lesson04/`

运行入口：

```powershell
Set-Location '.\learning\agent-java-learning'
mvn -o -pl 04-redis -am package -DskipTests
java -cp '04-redis/target/classes;04-redis/target/dependency/*' learn.agent.redis.lesson04.SpringRedisCommandDemo
```

## 常见面试题

### 1. 为什么用 Lua？

**参考答案：**单独的 `HGET` 和 `HSET` 各自原子，但两条命令之间可能被其他消费者插入。Lua 把检查旧状态和写入新状态放在 Redis 内连续执行，避免旧状态覆盖新状态。

**项目解决方案：**`SpringRedisCommandStateService` 只有在当前状态等于 `expectedStatus` 时才更新，并用返回值 `1/0` 告诉业务是否成功。

**风险边界：**脚本逻辑过长会阻塞 Redis；复杂流程应拆分或使用更合适的状态协调方案。

### 2. `StringRedisTemplate` 和 Lettuce 的关系是什么？

**参考答案：**Lettuce 是底层 Redis 客户端；`StringRedisTemplate` 是 Spring Data Redis 的常用封装，管理序列化、连接工厂和 Spring 生命周期。

**项目解决方案：**Spring 配置创建 `LettuceConnectionFactory` 和 `StringRedisTemplate`，业务类通过构造方法注入模板。

**风险边界：**模板不能自动保证业务幂等和数据库一致性；底层客户端仍可能用于特殊命令或性能调优。

### 3. Lua 能替代数据库事务吗？

**参考答案：**不能。Lua 只保证 Redis 内部脚本的连续执行，不包含数据库写入，也不能自动回滚跨系统操作。

**项目解决方案：**Redis 只负责状态条件更新，数据库事务负责最终业务事实；跨系统失败需要补偿、重试或消息最终一致性。

**风险边界：**如果 Redis 更新成功、数据库更新失败，仍然需要业务恢复流程，不能只依赖 Lua。
