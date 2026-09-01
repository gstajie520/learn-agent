# Java Agent 学习工程

这是 Java 后端转向 Agent/LLM 应用后端的统一学习工程。以后不再为每一课在 `learning/` 根目录创建新项目，而是在本工程中按阶段增加目录。

## 阶段目录

```text
agent-java-learning/
  01-java-state-machine/       Java 状态机、封装、异常和测试
  02-java-concurrency/         线程池、Future、超时、队列和拒绝策略
  03-springboot-command-api/   Spring Boot 提交命令和查询状态
  04-redis/                    Redis 语义、SETNX、TTL 和幂等
  05-llm-client/               阶段 5：模型调用边界、Token、finishReason 和错误分类
  06-structured-output/        阶段 6 前半：模型输出结构化数据，Schema 与业务两层校验
  07-tool-calling/             阶段 6 后半：模型主动选工具，prepare/invoke 分离
  08-agent-loop/               阶段 7：多轮循环与上限、超时、幂等、归因四道工具边界
  09-agent-guardrails/         阶段 8：权限裁决与 Hook 生命周期
  10-context-engineering/      阶段 9：计划提醒、上下文压缩、子 Agent
  99-minimal-eval/             跨阶段回归基线，依赖全部上游模块，永远排在最后
```

前四个目录是 Java/Spring/Redis 基础，从 `05-llm-client` 起进入 LLM 与 Agent 主线。
目录号从阶段 6 开始不再与阶段号一一对应：阶段 6 拆成了 `06`、`07` 两个模块，
之后的目录号比阶段号大 1。每个模块的 README 第一行注明自己属于哪个阶段。

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

`-am` 是「把依赖的上游模块一起构建」，上游模块的测试也会跟着跑，所以输出里的测试总数
不是本模块自己的数量。想只看本模块，去掉 `-am`，或者用 `-Dtest=` 指定测试类。

阶段 4 的真实 Redis 测试需要 `$env:REDIS_PASSWORD`，未设置时会明确跳过。
阶段 5 只有 3 个真实调用测试需要密钥和网络，未配置时明确跳过；其余全部离线。

## 阅读顺序

1. 先看当前阶段目录的 `README.md`，理解为什么学；
2. 再运行该阶段的 `main()` 教学入口；
3. 然后看完整业务代码；
4. 最后阅读测试，确认成功和失败分支。
