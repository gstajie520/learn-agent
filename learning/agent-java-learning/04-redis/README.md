# Redis 学习目录

本模块继续使用一个 Maven 项目，但每一课都有独立文档、Java 子包和测试子包。学习时只打开当前课，不需要在一个大文件里搜索。

## 学习顺序

| 课次 | 内容 | 文档 | Java 包 | 测试包 |
|---|---|---|---|---|
| 1 | SETNX、TTL、幂等抢占 | [01-idempotency.md](lessons/01-idempotency.md) | `learn.agent.redis.lesson01` | `learn.agent.redis.lesson01` |
| 2 | Lettuce 连接真实 Redis | [02-real-redis.md](lessons/02-real-redis.md) | `learn.agent.redis.lesson02` | `learn.agent.redis.lesson02` |
| 3 | Redis Hash 保存命令状态 | [03-hash-state.md](lessons/03-hash-state.md) | `learn.agent.redis.lesson03` | `learn.agent.redis.lesson03` |
| 4 | Spring Redis 与 Lua 条件更新 | [04-spring-state.md](lessons/04-spring-state.md) | `learn.agent.redis.lesson04` | `learn.agent.redis.lesson04` |
| 5 | 缓存读写、穿透、击穿、雪崩 | [05-cache.md](lessons/05-cache.md) | `learn.agent.redis.lesson05` | `learn.agent.redis.lesson05` |

## 统一运行

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o -pl 04-redis -am test
```

真实 Redis 测试需要环境变量：

```powershell
$env:REDIS_PASSWORD = '你的本机 Redis 密码'
```

没有密码时，离线测试仍然执行，真实 Redis 测试会明确跳过，不把环境问题伪装成通过。

## 本课代码怎么找

每课都按同样方式组织：

```text
lessons/05-cache.md
src/main/java/learn/agent/redis/lesson05/
src/test/java/learn/agent/redis/lesson05/
```

先读当前课文档的“为什么学”和概念示例，再打开同名子包里的 `Demo`，最后看测试。

## Redis 和其他组件的边界

- RabbitMQ：移动消息，负责异步投递和确认；
- Redis 状态：保存命令当前状态、幂等 claim 和短期协调信息；
- Redis 缓存：加速查询，不是最终业务事实；
- 数据库：保存长期业务结果、审计和最终事实。
