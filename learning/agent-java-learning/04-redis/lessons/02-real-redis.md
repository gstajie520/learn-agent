# 第 2 课：使用 Lettuce 连接真实 Redis

## 为什么学习

上一课只是模拟 Redis 语义。本课用 Lettuce 连接独立 Redis 服务，理解 Java 客户端如何发送 `SET NX EX`、`GET`、`TTL` 和 `DEL`。

## 代码与测试

- `src/main/java/learn/agent/redis/lesson02/RealRedisIdempotencyStore.java`
- `src/main/java/learn/agent/redis/lesson02/RealRedisIdempotencyDemo.java`
- `src/test/java/learn/agent/redis/lesson02/RealRedisIdempotencyStoreTest.java`

密码只从环境变量读取：

```powershell
$env:REDIS_PASSWORD = '你的本机 Redis 密码'
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 04-redis -am test
```

没有密码时，真实连接测试标记为跳过；不能把端口可达当成认证成功。

## 生产边界

Redis 客户端使用完必须关闭连接。密码不能写入源代码。最终业务结果不能只放 Redis，数据库仍负责长期事实。

## 常见面试题

### 1. Lettuce 是什么？

**参考答案：**Lettuce 是 Java 连接 Redis 的客户端，负责把 Java 方法调用转换成 Redis 协议命令，并提供同步、异步等访问方式。

**项目解决方案：**`RealRedisIdempotencyStore` 创建 `RedisClient` 和连接，发送 `SET NX EX`、`GET`、`TTL`、`DEL`，业务层不直接拼 Redis 协议。

**风险边界：**客户端只是访问工具，不会自动解决幂等、事务、重试和业务状态一致性。

### 2. 端口可达但报 `NOAUTH` 为什么？

**参考答案：**端口可达只说明网络连接成功，Redis 仍可能要求密码或 ACL 身份认证；客户端没有凭据时会被拒绝。

**项目解决方案：**代码从 `REDIS_PASSWORD` 环境变量读取密码，不把真实凭据写入源码或 Git；测试在凭据缺失时明确跳过。

**风险边界：**环境变量也需要由部署平台安全管理，生产中应使用密钥服务、轮换和最小权限账号。

### 3. 为什么连接要关闭？

**参考答案：**Redis 连接会占用网络连接、线程和客户端资源，不关闭可能造成连接泄漏，最终影响服务稳定性。

**项目解决方案：**直接 Lettuce 客户端使用 `try-with-resources` 和 `close()`；Spring 场景交给容器销毁 `LettuceConnectionFactory`。

**风险边界：**每次请求都新建连接也会有性能问题，生产应使用连接工厂和连接池，而不是频繁创建客户端。
