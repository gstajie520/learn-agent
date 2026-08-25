# Java 后端转 Agent 开发工程师：完整学习路线

> 制定日期：2026-08-25
>
> 目标：从 Java/Spring Boot 后端，转成能够设计、实现、上线和解释 Agent 应用的工程师。

## 一、先定义岗位

Agent 开发工程师不是只会调用一个大模型 API，也不是只会背 LangChain 或 LangGraph API。实际工作通常包含四类职责：

1. **LLM 应用层**：消息、Prompt、Tool Calling、Structured Output、Token、Streaming、Embedding、RAG。
2. **Agent 流程层**：Agent Loop、工具注册、状态、记忆、Graph、暂停恢复、人工确认、重试。
3. **后端工程层**：Spring Boot、数据库、MQ、Redis、异步任务、幂等、权限、超时、可观测性。
4. **生产质量层**：安全边界、评估集、成本、延迟、日志、Trace、故障恢复和项目表达。

模型本身是不确定的，业务系统必须在模型外面建立确定性边界：

```text
用户请求
  -> 模型理解
  -> 结构化命令
  -> Schema 校验
  -> 业务校验
  -> 权限/确认
  -> 异步执行
  -> 幂等/重试/恢复
  -> 结果和审计
```

## 二、学习优先级

对于已有 Java 后端经验的人，建议按这个顺序投入时间：

| 能力 | 优先级 | 学习目标 |
|---|---:|---|
| LLM API 与结构化输出 | 最高 | 能稳定拿到可校验的模型结果 |
| Tool Calling 与 Agent Loop | 最高 | 能解释模型何时决定调用工具、程序如何执行工具 |
| RAG | 高 | 能做有来源、可追踪的知识查询 |
| 状态与工作流 | 高 | 能处理分支、暂停、恢复、人工确认 |
| Java/Spring AI 或 LangChain4j | 高 | 能把 Agent 接入 Java 后端 |
| LangGraph | 高 | 重点理解 State、Node、Edge、Checkpoint，不先死记 API |
| MQ、Redis、数据库 | 高 | 支撑异步任务、状态、幂等和恢复 |
| MCP、Skills、连接器 | 中高 | 扩展工具边界和动态能力 |
| 多 Agent | 中 | 先掌握单 Agent，确有协作需求再学 |
| 模型训练、微调、分布式推理 | 低 | 除非岗位明确要求，否则不作为转型主线 |

## 三、24 周主路线

每周都要有代码产出，不能只看文章。每个阶段的“完成标准”比学习时间更重要。

| 阶段 | 周期 | 主题 | 主要语言 | 产出 |
|---|---:|---|---|---|
| 0 | 1-2 | Java 后端补强 | Java | 能独立读写简单 Spring Boot 代码 |
| 1 | 3-4 | LLM 调用基础 | Java + 少量 Python | 模型调用、消息、Token、错误处理 |
| 2 | 5-6 | Structured Output 与 Tool Calling | Java | 可校验的领域命令 |
| 3 | 7-8 | 手写 Agent Loop | Java/Python | 不依赖框架的有限轮次 Agent |
| 4 | 9-11 | RAG 基础 | Python 为主，Java 接入 | 文档切分、Embedding、检索、引用 |
| 5 | 12-14 | Agent 状态与 LangGraph | Python | State、Node、Edge、Checkpoint、Interrupt |
| 6 | 15-17 | Java Agent 集成 | Java | Spring AI 或 LangChain4j 服务 |
| 7 | 18-19 | 分布式 Agent 后端 | Java | MQ、Redis、异步命令、WebSocket、幂等 |
| 8 | 20 | MCP、Skills、连接器 | Python/Java | 受权限控制的动态工具接入 |
| 9 | 21-22 | 评估、安全、可观测性 | Java/Python | 评估集、Trace、成本和安全策略 |
| 10 | 23-24 | 综合项目与求职表达 | Java + Python | 可运行作品、架构图、故障复盘、面试稿 |

## 阶段 0：Java 后端补强

你已经完成一部分：状态机、线程池、Spring Boot API、Redis 基础。后续只补 Agent 后端真正会用到的内容：

- Java 集合、异常、接口、泛型和 IO；
- Spring Boot Controller/Service/Repository 分层；
- 参数校验、统一异常、日志和配置；
- 线程池、Future、超时、优雅关闭；
- 数据库事务、乐观锁、状态机；
- Redis 的状态、缓存、幂等；
- RabbitMQ 的 ACK、重试、死信和幂等。

不需要在这个阶段深挖 JVM 源码、并发包所有工具或复杂设计模式。目标是能读懂和修改 Agent 后端，而不是成为 JVM 专家。

**完成标准：**能写一个异步命令 API，命令状态可查询，重复消息不重复执行，失败可以重试。

## 阶段 1：LLM 调用基础

要掌握的概念：

- System、User、Assistant、Tool 消息；
- Prompt 和业务规则的区别；
- Token、上下文窗口、输入输出成本；
- Temperature、超时、重试、限流；
- Streaming 与普通请求；
- 模型错误、空结果、格式错误和服务不可用。

**代码产出：**Java 调用模型完成场景描述总结；把模型客户端封装成接口，测试使用 Fake 客户端，不依赖真实密钥。

**不要急着学：**多 Agent、复杂 Prompt 模板、自动规划。先知道一次模型请求到底传了什么、返回了什么。

## 阶段 2：Structured Output 与 Tool Calling

这是从“聊天机器人”转到“Agent 应用”的关键阶段。

学习顺序：

1. 让模型输出 JSON；
2. 用 JSON Schema 校验格式；
3. 再做业务校验，例如对象是否存在、版本是否匹配、坐标是否越界；
4. 学习 Tool Calling 的名称、参数、调用 id 和工具结果；
5. 规定工具失败时模型是否重试，哪些错误必须直接返回用户。

**核心原则：**结构正确不代表业务合法。模型生成的 `{"action":"delete"}` 即使 JSON 正确，也必须经过权限、对象存在性和危险操作校验。

**代码产出：**自然语言“在北侧生成雷达”转换成 `SceneOperation`，经过 Schema 校验和业务校验后只生成预览，不直接修改真实数据。

## 阶段 3：手写 Agent Loop

先不用 LangGraph，手写最小循环，理解框架到底替你做了什么：

```text
messages = [system, user]
for round in 1..N:
    response = model(messages, tools)
    if 没有 tool_calls:
        return response
    for tool_call in response.tool_calls:
        result = execute_tool(tool_call)
        messages.add(tool_result)
return 超过最大轮次
```

必须实现：

- 最大轮次；
- 工具白名单；
- 工具参数校验；
- 工具超时；
- 工具异常回传；
- 重复 tool call 的幂等；
- 每轮日志和 trace id。

**完成标准：**你能回答“谁决定调用工具、谁真正执行工具、工具结果如何回到模型、什么时候结束”。

## 阶段 4：RAG

RAG 的目标不是“把一堆文本塞给模型”，而是让模型基于可追踪的外部知识回答。

学习顺序：

1. 文档清洗和切分；
2. Embedding 和向量相似度；
3. Top-K 检索和 Metadata 过滤；
4. 关键词检索与向量检索的区别；
5. 混合检索、重排和引用来源；
6. 召回失败、知识过期和权限过滤。

**代码产出：**知识库问答服务，答案必须返回引用文档 id；先用内存向量或本地向量库学习，再接真实向量数据库。

**不应混淆：**RAG 是知识检索，不等于 Agent；Agent 可以调用检索工具，但 RAG 本身不负责复杂流程编排。

## 阶段 5：Agent 状态与 LangGraph

LangGraph 的学习顺序：

- State：节点之间传递什么数据；
- Node：一个节点只做一个清晰动作；
- Edge：固定流转和条件分支；
- Loop：工具调用后回到模型；
- Checkpoint：保存 Agent 会话状态；
- Interrupt/Resume：人工确认后继续；
- Retry/Timeout：节点失败如何恢复；
- Thread ID：如何区分会话和任务。

**推荐语言：**Python。LangGraph 生态、资料和实际项目采用率目前明显高于 Java 图编排方案。Java 后端通过 HTTP/MQ 调用 Python Agent 服务，不代表 Java 能力降低，而是按生态边界分工。

**完成标准：**实现一个“生成预览 -> 人工确认 -> 应用修改”的小图，并能从 checkpoint 恢复。

## 阶段 6：Java Agent 集成

Java 侧建议只选一个主框架：

- **Spring AI：**如果目标岗位是 Spring Boot 企业应用，优先学习；配置、模型客户端、Tool、结构化输出、向量存储与 Spring 生态更自然。
- **LangChain4j：**适合学习 Java Agent/RAG 的另一种抽象，面试中了解即可，除非岗位明确使用。
- **Koog：**JetBrains 的 Kotlin/JVM Agent 框架，可作为 JVM 生态观察对象，不作为当前 Java 主线。
- **Agents-Flex：**Java Agent 开源项目，适合阅读其 RAG、MCP、Skill、Sub-agent 设计，不建议在基础阶段直接依赖。

不要同时深入 Spring AI、LangChain4j、Koog、Agents-Flex。先用手写 Loop 理解机制，再用 Spring AI 完成一个 Java 项目。

## 阶段 7：分布式 Agent 后端

把 Agent 当成一个不稳定、耗时、可能重试的外部服务：

```text
Java API
  -> 写入命令状态
  -> MQ 投递 Agent 任务
  -> Python Agent / LangGraph
  -> MQ 返回结构化结果
  -> Java 校验、持久化、通知前端
```

必须掌握：

- MQ ACK/NACK、重试、死信和消费幂等；
- Redis 命令状态、claim key、TTL、checkpoint 边界；
- 数据库事务和乐观锁；
- WebSocket/SSE 状态通知；
- 超时、取消、重试和补偿；
- 多实例部署下不能依赖 JVM 内存。

这部分正是你目前正在学习的 Java 基础，但它应该服务于 Agent 链路，而不是独立成为学习终点。

## 阶段 8：MCP、Skills 和连接器

学习重点不是协议名，而是工具边界：

- 工具发现和注册；
- 参数 Schema；
- 权限、租户和资源范围；
- 超时、审计和限流；
- 动态 Skill 加载；
- 外部 MCP 服务断开和恢复。

**完成标准：**实现一个只能读取指定目录、只能调用白名单 API 的 MCP/Tool 服务，并能记录每次调用。

## 阶段 9：评估、安全、可观测性

生产 Agent 必须能回答“为什么这次错了”：

- 评估集：输入、期望工具、期望结构、业务结果；
- 质量指标：任务成功率、工具调用正确率、Schema 通过率、引用准确率；
- 成本指标：Token、模型费用、平均轮次；
- 性能指标：首 token 延迟、总延迟、工具耗时、队列积压；
- 安全：Prompt Injection、越权工具、敏感数据、危险操作确认；
- 观测：trace id、conversation id、command id、model request id。

## 阶段 10：综合项目与求职

最终项目建议做一个“智能场景命令系统”或“智能任务执行系统”，必须包含：

- Java Spring Boot API；
- Python Agent/LangGraph；
- Structured Output + Schema/业务双重校验；
- MQ 异步任务和结果；
- Redis 状态、幂等、缓存；
- 数据库最终结果；
- WebSocket/SSE 通知；
- 人工确认和可恢复 checkpoint；
- 测试、评估集、日志、架构图和故障复盘。

求职表达使用：

```text
问题 -> 设计 -> 权衡 -> 故障 -> 验证
```

不要说“我调用了 LangGraph API”，要说“模型输出存在不确定性，我在 Java/Python 边界增加了 Schema、业务校验、幂等、版本控制和人工确认”。

## 四、fw 项目是否适合学习

结论：**适合做后半程综合项目，不适合做前半程教材。**

### fw 已经包含的能力

| fw 部分 | 对应 Agent 能力 | 学习价值 |
|---|---|---|
| `agent_service/agent/` | LangGraph State、Node、Tool Loop | 学阶段 5 |
| `agent_service/services/skill_rag.py` | Skill 检索和 RAG | 学阶段 4 |
| `agent_service/services/smart_scene.py` | Agent 结果提取、结构化协议 | 学阶段 2/5 |
| `agent_service/skills/smart_scene/tools/` | 工具实现和业务校验 | 学阶段 2/8 |
| `agent_control_app` | Java Spring Boot 控制面 | 学阶段 0/6/7 |
| `RabbitMQConfig`、消息消费者 | 异步任务和服务边界 | 学阶段 7 |
| `RedisConfig`、命令总线 | 状态、幂等、多实例 | 学阶段 7 |
| WebSocket | 前端实时通知 | 学阶段 7 |
| `智能场景Graph说明.md` | 项目执行图和消息时序 | 总结复习 |

### 学习时先看什么

按这个顺序阅读 `fw`：

1. 只读 `智能场景Graph说明.md`，画出 Java -> MQ -> Python -> MQ -> Java；
2. 读 `agent_service/agent/node_state.py`，理解 Graph State；
3. 读 `agent_service/agent/__init__.py`，理解节点和边；
4. 读 `agent_service/agent/agent_node.py` 与 `tool_node.py`，理解模型和工具的边界；
5. 读 `smart_scene_contract.py` 与 `skills/smart_scene/tools/scene_operations.py`，理解结构校验；
6. 再读 Java `SmartSceneCommandController`、命令 Service、RabbitMQ 和 Redis；
7. 最后看 WebSocket、前端应用和完整日志。

### 现在不要先看的内容

- 语音、视频、轨迹、TTS、ONNX 等旁支能力；
- 前端三维渲染细节；
- 所有数据库表和管理后台；
- 完整部署脚本和历史兼容代码。

这些内容不是没有价值，而是会遮住 Agent 主链路。

## 五、GitHub 参考项目怎么用

这些仓库用于比较能力覆盖和工程做法，不是要求全部照着学：

| 仓库 | 适合借鉴什么 |
|---|---|
| [NirDiamant/agents-towards-production](https://github.com/NirDiamant/agents-towards-production) | 从 Agent 基础到生产化、RAG、评估和部署的案例 |
| [Prompthon-IO/agent-systems-handbook](https://github.com/Prompthon-IO/agent-systems-handbook) | Agent 系统设计和生产工程视角 |
| [Haozhe-Xing/agent_learning](https://github.com/Haozhe-Xing/agent_learning) | Agent、RAG、工具、记忆、MCP 的系统化学习目录 |
| [Annyfee/agent-craft](https://github.com/Annyfee/agent-craft) | LangChain、RAG、LangGraph、MCP 的入门实战组织方式 |
| [JetBrains/koog](https://github.com/JetBrains/koog) | JVM/Kotlin Agent 框架和企业级 Agent 抽象 |
| [agents-flex/agents-flex](https://github.com/agents-flex/agents-flex) | Java Agent、RAG、MCP、Skills、Sub-agent 的 JVM 生态参考 |

参考原则：先看目录和架构，再挑一个主题复现；不要因为仓库 star 高就同时学习所有框架。

## 六、当前学习路线调整

你已经完成或正在完成：

- Java 状态机、线程池、Spring Boot API；
- Redis 幂等、真实客户端、Hash 状态、Spring 条件更新、缓存基础；

接下来不再继续无限扩展 Redis。路线切换为：

1. Redis 阶段做一次串联验收；
2. 进入 LLM 调用、消息、Token 和 Structured Output；
3. 手写 Tool Calling 和 Agent Loop；
4. 再进入 Python/LangGraph；
5. 最后回到 MQ/Redis，把它们接到 Agent 异步链路；
6. 用 `fw` 做按模块拆解和综合项目。

这样学习的主线是“先理解 Agent，再用后端工程把 Agent 生产化”，而不是“先学完所有中间件才开始 Agent”。
