# Java Agent 学习工程

这是 Java 后端转向 Agent/LLM 应用后端的统一学习工程。以后不再为每一课在 `learning/` 根目录创建新项目，而是在本工程中按阶段增加目录。

## 阶段目录

```text
agent-java-learning/
  01-java-state-machine/       Java 状态机、封装、异常和测试
  02-java-concurrency/         线程池、Future、超时、队列和拒绝策略
  03-springboot-command-api/   Spring Boot 提交命令和查询状态
  04-redis/                    Redis 语义、SETNX、TTL 和幂等
  05-llm-client/               模型调用边界、Token、finishReason 和错误分类
```

RabbitMQ 不在这里。路线重审后，MQ 归入阶段 14「分布式 Agent 后端」，
先掌握模型调用和 Agent 机制，再把它生产化。完整顺序见
[agent-engineer-roadmap.md](../../agent-engineer-roadmap.md)。

每个阶段目录包含自己的源码、测试和 README，但都属于同一个学习路线。

## 验证全部已学阶段

在 PowerShell 中执行：

```powershell
Set-Location '.\learning\agent-java-learning'
$env:JAVA_HOME = 'C:\Program Files\Java\jdk-17.0.18'
mvn -o test
```

只跑当前阶段：

```powershell
mvn -o -pl 05-llm-client -am test
```

阶段 4 的真实 Redis 测试需要 `$env:REDIS_PASSWORD`，未设置时会明确跳过。
阶段 5 全部离线，不需要密钥和网络。

## 阅读顺序

1. 先看当前阶段目录的 `README.md`，理解为什么学；
2. 再运行该阶段的 `main()` 教学入口；
3. 然后看完整业务代码；
4. 最后阅读测试，确认成功和失败分支。
