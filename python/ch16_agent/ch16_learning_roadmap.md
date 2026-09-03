# 第 16 章：计划审批协议与优雅关机 学习导航图

## 学习脑图

```mermaid
mindmap
  root((第 16 章<br/>计划审批协议<br/>与优雅关机))
    学习路线（推荐顺序）
      第一步：理解协议需求
        tests/test_ch16_protocol.py
        看计划审批和关机的完整流程
        理解 pending→approved/rejected 状态机
      第二步：读协议领域模型
        features/protocol.py
        ProtocolRequest 不可变快照
        ProtocolRuntime 协调 Store 和 Mailbox
        submit_plan / review_plan / request_shutdown
      第三步：理解持久化层
        adapters/protocol_json.py
        JsonProtocolStore 原子快照
        状态迁移与唯一 resolution
      第四步：理解依赖关系
        features/mailbox.py（消息传递）
        features/teammates.py（队友运行时）
        core/loop.py 的 run_events（事件消费）
    核心文件清单
      features/protocol.py（协议核心）
        ProtocolRequest 数据类
          id / kind / sender / target
          status（pending/approved/rejected）
          resolution（终态决议）
        ProtocolRuntime 领域服务
          submit_plan（队友提交计划）
          review_plan（Lead 审批）
          request_shutdown（Lead 请求关机）
          PlanApprovalGate（权限拦截器）
        ProtocolStore 接口
          save_request / get_request
          resolve_request（状态迁移）
      adapters/protocol_json.py（持久化）
        JsonProtocolStore
          state.json 单文件快照
          原子写入与 fsync
          pending 过期检查
      features/mailbox.py（消息传递）
        MailboxMessage 不可变消息
        ProtocolMailboxMessage（typed）
        MailboxStore 四态目录
          ready/processing/done/quarantine
      features/teammates.py（队友管理）
        TeammateRuntime
          spawn / send_message
          生命周期管理
          事件泵集成
      core/loop.py（事件消费）
        AgentRunner.run_events
          消费运行时事件
          ack-after-processing
          幂等键防重
    Java 对照关系
      数据结构对照
        ProtocolRequest = 不可变 record
        MailboxMessage = record with id
        ProtocolResolution = 终态 VO
        Literal 类型 = 枚举约束
      接口对照
        ProtocolStore = Repository<ProtocolRequest>
        MailboxStore = MessageQueueRepository
        ProtocolRuntime = ProtocolService
        TeammateRuntime = WorkerPoolService
      持久化对照
        state.json = 单文件快照
        原子写入 = temp + fsync + rename
        四态目录 = 状态机目录结构
      并发对照
        EventInbox = BlockingQueue<RuntimeEvent>
        run_events = 消费者线程
        ack-after-processing = 事务性确认
    设计模式识别
      Repository 模式
        ProtocolStore 抽象持久化
        JsonProtocolStore 文件实现
        状态迁移在 Repository 内部
      状态机模式
        pending → approved/rejected
        唯一 resolution 记录终态
        过期自动拒绝
      发件箱模式（Outbox Pattern）
        请求先保存到 ProtocolStore
        再投递到 Mailbox
        保证至少一次传递
      事件驱动架构
        协议事件通过 EventInbox 传递
        run_events 消费事件并调用模型
        ack 成功后事件才标记完成
      策略模式
        PlanApprovalGate 作为 PermissionRule
        pending 计划自动 deny 工具
        approved 后放行
    关键概念理解
      为什么需要结构化协议
        第 15 章用自然语言猜状态
        模型可能理解错审批结果
        结构化协议提供明确状态机
        机器可读的 approved 字段
      ProtocolRequest 的三个状态
        pending：等待审批
        approved：Lead 批准
        rejected：Lead 拒绝或过期
      为什么 resolution 是唯一的
        防止重复审批
        保证状态机单向迁移
        提供审计追溯
      ack-after-processing 语义
        事件处理完才确认
        避免消息丢失
        ack 失败只补确认，不重复处理
      计划门控（PlanApprovalGate）
        pending 计划自动拦截工具调用
        approved 后放行
        队友不能绕过审批执行危险操作
      优雅关机流程
        Lead 发送 shutdown 请求
        队友收到立即确认
        不再调用模型，直接返回文本
        队友进程标记 failed 状态
    面试题速查
      Q1：为什么 ProtocolRequest 需要 expires_at_utc
        A：pending 请求不能无限期等待。过期后自动拒绝，避免队友永久阻塞在审批等待状态。
        Java 对照：类似 CompletableFuture 的超时机制。
      Q2：为什么协议消息使用 ProtocolMailboxMessage 而不是普通消息
        A：typed 消息携带结构化字段（request_id/protocol_kind），模型不需要解析自然语言就能识别协议类型。
        Java 对照：类似领域事件的 EventType 字段。
      Q3：为什么 submit_plan 先保存请求再投递消息
        A：Outbox 模式保证至少一次传递。保存成功但投递失败时，下次启动可以重试投递，避免请求丢失。
        Java 对照：类似事务性发件箱表。
      Q4：为什么 review_plan 需要检查 status == pending
        A：防止重复审批。状态机保证 pending → approved/rejected 是单向的，已终态的请求不能再次审批。
        Java 对照：类似订单状态机的幂等检查。
      Q5：为什么 shutdown 请求不需要审批
        A：shutdown 是 Lead 的主动指令，不是队友请求。队友收到后立即确认并停止，不需要反向审批流程。
        Java 对照：类似线程的 interrupt 信号。
      Q6：ack-after-processing 如何防止消息丢失
        A：事件处理完成、模型调用成功后才 ack。ack 失败时保留 pending_event_acks，下次只补确认，不重复处理。
        Java 对照：类似消息队列的手动 ack 模式。
      Q7：PlanApprovalGate 在哪个阶段生效
        A：PermissionPolicy 阶段，在工具执行前。pending 计划返回 deny，approved 返回 passthrough 让其他规则决策。
        Java 对照：类似 Spring Security 的 AccessDecisionVoter。
      Q8：为什么 JsonProtocolStore 使用单文件快照而不是每个请求一个文件
        A：请求总数不大（通常 < 100），单文件原子写避免目录一致性问题，简化过期清理和全量查询。
        Java 对照：类似 Spring Session 的内存模式。
```

## Java 开发者 3 步速通指南

### 第 1 步：从测试理解协议流程（15 分钟）

```bash
# 阅读测试文件，理解完整协议流程
cat tests/test_ch16_protocol.py

# 关注点：
# - submit_plan 如何提交计划
# - review_plan 如何审批（approved=True/False）
# - request_shutdown 如何触发关机
# - 事件如何通过 wait_event 和 acknowledge_events 消费
```

**Java 对照**：
- `submit_plan` = 创建审批单并发送消息
- `review_plan` = 审批单状态迁移
- `wait_event` = `BlockingQueue.take()`
- `acknowledge_events` = 消息确认（commit）

**核心流程**：
```
队友调用 submit_plan
  ↓
保存 pending 请求到 ProtocolStore
  ↓
投递 ProtocolMailboxMessage 到 Lead
  ↓
Lead 调用 review_plan(approved=True/False)
  ↓
状态迁移到 approved/rejected
  ↓
投递响应消息到队友
  ↓
队友收到事件继续执行
```

### 第 2 步：读协议核心代码（20 分钟）

```bash
# 按顺序阅读三个核心文件
cat features/protocol.py           # 领域模型和服务
cat adapters/protocol_json.py      # 持久化实现
cat features/mailbox.py             # 消息传递（快速浏览）

# 重点理解：
# 1. ProtocolRequest 的三个状态
# 2. ProtocolRuntime 的三个方法
# 3. PlanApprovalGate 的拦截逻辑
# 4. JsonProtocolStore 的原子写入
```

**关键理解**：

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `ProtocolStore` | `Repository<ProtocolRequest>` | 持久化接口 |
| `ProtocolRuntime` | `ProtocolService` | 领域服务 |
| `ProtocolResolution` | 终态值对象（VO） | 不可变审批结果 |
| `PlanApprovalGate` | `PermissionRule` | 权限拦截器 |
| `ProtocolMailboxMessage` | 领域事件 | 类型化消息 |

### 第 3 步：理解事件消费机制（10 分钟）

```bash
# 快速浏览事件驱动部分
cat core/loop.py                    # 找 run_events 方法
cat features/teammates.py           # 找 drain_events 和 acknowledge_events

# 理解：
# - 事件如何从 Mailbox 流向 EventInbox
# - run_events 如何消费事件
# - ack-after-processing 的保证
```

**不要深入细节**：这些是基础设施层，知道协议如何通过事件传递即可。

---

## 调试断点速查（VSCode/PyCharm 适用）

### 【必打断点】理解协议流程（5 个）

**[1] protocol.py:submit_plan 方法开始**
```python
# 观察：sender（队友名）、content（计划内容）
# 目的：确认队友提交了什么计划
```

**[2] protocol_json.py:save_request 原子写入前**
```python
# 观察：request.status（应该是 pending）、expires_at_utc
# 目的：确认请求正确保存
```

**[3] protocol.py:review_plan 方法开始**
```python
# 观察：request_id、approved（True/False）
# 目的：确认 Lead 做出了什么决策
```

**[4] protocol_json.py:resolve_request 状态迁移**
```python
# 观察：resolution.approved、resolution.content
# 目的：确认状态正确迁移到终态
```

**[5] loop.py:run_events 方法开始**
```python
# 观察：next_event.event_id、event.prompt
# 目的：确认队友收到了响应事件
```

### 【可选断点】深入理解（3 个）

**[6] protocol.py:PlanApprovalGate.evaluate**
```python
# 观察：request.status、决策结果（deny/passthrough）
# 目的：理解计划门控如何拦截工具
```

**[7] mailbox_json.py:post 方法**
```python
# 观察：消息如何写入 ready 目录
# 目的：理解 Mailbox 的四态迁移
```

**[8] teammates.py:acknowledge_events**
```python
# 观察：事件如何从 processing 移到 done
# 目的：理解 ack-after-processing 语义
```

---

## 核心概念速记

**协议状态机**：pending（等待） → approved（批准） / rejected（拒绝）

**Outbox 模式**：先保存请求，再投递消息（保证至少一次传递）

**ack-after-processing**：处理完才确认，ack 失败只补确认（防止消息丢失）

**计划门控**：pending 计划自动 deny 工具调用（approved 后放行）

**优雅关机**：Lead 发送 shutdown → 队友确认 → 不再调用模型

---

## 核心类比速查表

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `ProtocolRequest` | 不可变 record | 协议请求快照 |
| `ProtocolStore` | `Repository<T>` | 持久化接口 |
| `ProtocolRuntime` | 领域 Service | 协议编排服务 |
| `MailboxMessage` | 领域事件 | 消息传递 DTO |
| `EventInbox` | `BlockingQueue<Event>` | 事件队列 |
| `run_events()` | 消费者线程 | 事件驱动循环 |
| `PlanApprovalGate` | `PermissionRule` | 权限拦截器 |
| `ProtocolResolution` | 终态值对象 | 不可变审批结果 |

---

## 学完本章你会理解

✅ **结构化协议的必要性**：为什么需要明确状态机代替自然语言  
✅ **Outbox 模式**：如何保证协议请求至少一次传递  
✅ **ack-after-processing 语义**：如何防止事件消息丢失  
✅ **计划门控机制**：如何用权限规则拦截未审批的危险操作  
✅ **优雅关机流程**：Lead 如何安全停止队友进程  
✅ **状态机唯一终态**：为什么 resolution 只能设置一次  

---

## 常见问题 FAQ

### Q1: 为什么需要 expires_at_utc？
**A**: pending 请求不能无限期等待。Lead 可能忘记审批或进程崩溃，过期后自动拒绝避免队友永久阻塞。类似 CompletableFuture 的超时机制。

### Q2: 为什么 submit_plan 先保存再投递消息？
**A**: Outbox 模式保证至少一次传递。保存成功但投递失败时，可以重试投递而不会丢失请求。类似事务性发件箱表。

### Q3: 为什么 review_plan 需要检查 status == pending？
**A**: 防止重复审批。状态机保证 pending → approved/rejected 是单向的，已终态请求不能再次审批，类似订单状态机的幂等检查。

### Q4: ack 失败后如何保证不重复处理？
**A**: ack 失败时事件身份保存到 `_pending_event_acks`，下次 run_events 只补 ack，不重新调用模型。history 和模型调用已完成，只是确认失败。

### Q5: PlanApprovalGate 返回 passthrough 是什么意思？
**A**: passthrough 表示"我不做决策，交给其他规则"。approved 计划不应被门控拒绝，但仍需其他权限规则（如沙箱检查）评估。

---

## 下一步学习建议

1. **运行测试**：`pytest tests/test_ch16_protocol.py -v`
2. **修改过期时间**：改成 1 秒，观察 pending 请求自动拒绝
3. **实现 FakeProtocolStore**：练习 Repository 接口的内存实现
4. **追踪消息流转**：在 mailbox ready/processing/done 目录观察文件迁移

---

## 文件依赖关系图

```
ProtocolRuntime (protocol.py)
    ├── depends on → ProtocolStore (protocol.py 接口)
    │   └── implemented by → JsonProtocolStore (protocol_json.py)
    ├── depends on → TeammateRuntime (teammates.py)
    │   ├── depends on → MailboxStore (mailbox.py 接口)
    │   │   └── implemented by → FileMailboxStore (mailbox_json.py)
    │   └── depends on → EventInbox (events.py)
    └── provides → PlanApprovalGate (PermissionRule)

AgentRunner (loop.py)
    └── run_events() → 消费 EventInbox 中的协议事件
```

---

## 总结：协议系统的三个核心职责

1. **状态管理**：维护 pending → approved/rejected 状态机
2. **消息传递**：通过 Mailbox 和 EventInbox 传递结构化协议消息
3. **权限拦截**：PlanApprovalGate 防止队友绕过审批执行危险操作

**记住**：结构化协议不是为了限制队友，而是为了让 Lead 和队友有明确的协作契约，避免自然语言理解歧义导致的错误执行。
