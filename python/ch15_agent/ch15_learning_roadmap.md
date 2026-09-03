# 第 15 章：持久队友与 Mailbox 通信学习导航图

## 学习脑图

```mermaid
mindmap
  root((第 15 章<br/>持久队友与 Mailbox))
    学习路线（推荐顺序）
      第一步：理解 Mailbox 领域模型
        features/mailbox.py
        MailboxMessage 6 个字段
        四态状态机：ready/processing/done/quarantine
        message.id 同时是事件 ID 和幂等键
      第二步：原子持久化与状态迁移
        adapters/mailbox_json.py
        临时文件 + fsync + atomic rename
        目录名即状态，rename 即状态迁移
        processing 状态即租约
      第三步：队友生命周期管理
        features/teammates.py
        每个队友独立 AgentRunner + 独立历史
        spawn → running → idle → running (复用)
        工作循环：claim → run → send result → ack
      第四步：事件回合与 ack-after-processing
        core/loop.py 的 run_events()
        事件回合完成后才 ack
        ack 失败保存到 _pending_event_acks
        下次只补确认不重复调用模型
    核心文件清单
      features/mailbox.py（领域模型）
        MailboxMessage（不可变消息）
          6 个字段
            id, sender, recipient
            kind, content, created_at_utc
          3 个属性
            event_id
            context_identity
            idempotency_key
        MailboxStore Protocol（Repository 接口）
          send() - 原子写入 ready
          claim() - 原子迁移 ready → processing
          ack() - 原子迁移 processing → done
          release() - 重试回 ready
          quarantine() - 隔离坏消息
          recover_processing() - 恢复遗留租约
        工具函数
          canonical_agent_name() - 安全 slug 校验
          canonical_message_id() - UUID 格式校验
          messages_equal() - 完整快照比较
      adapters/mailbox_json.py（Repository 实现）
        FileMailboxStore 核心方法
          _atomic_write() - 临时文件 + fsync + rename
          _move() - 原子状态迁移
          _load() - 读取并校验 JSON
          _valid_entries() - 自动隔离坏文件
        目录结构
          .agent_tutorial/mailboxes/
          {recipient}/ready/*.json
          {recipient}/processing/*.json
          {recipient}/done/*.json
          {recipient}/quarantine/*.json
      features/teammates.py（运行时管理）
        TeammateRuntime 类
          spawn() - 注册队友 + 启动 worker
          send() - 发消息 + 唤醒 idle 队友
          state() - 查询队友状态
          _run_worker() - 工作循环
          _publish_lead() - Lead 消息发布到 EventInbox
        _Worker 内部状态
          teammate - 不可变快照
          runner - 独立 AgentRunner
          thread - 可复用线程
          current - 当前处理消息
      core/loop.py 的 run_events()
        优先处理 _pending_event_acks
        取下一条事件（deferred 或 drain）
        执行事件回合
        ack 成功 → 返回结果
        ack 失败 → 保存到 pending 字典
        模型失败 → release 租约
    Java 对照关系
      领域模型对照
        MailboxMessage = record MailboxMessage(...)
        MailboxStore = MailboxRepository 接口
        FileMailboxStore = 文件版 Repository 实现
        四态状态机 = 数据库状态字段
      运行时对照
        TeammateRuntime = ExecutorService + 队友注册表
        _Worker = Callable<Void> 或 Runnable
        EventInbox = BlockingQueue<RuntimeEvent>
        _run_worker 循环 = @Scheduled 或 Quartz Job
      持久化对照
        _atomic_write = Files.move(ATOMIC_MOVE)
        _move 状态迁移 = UPDATE WHERE state=?
        recover_processing = @EventListener(ContextRefreshedEvent)
        quarantine = Dead Letter Queue
      安全边界对照
        canonical_agent_name = @Pattern 校验注解
        ToolContext.identity = @AuthenticationPrincipal
        sender 保护 = Spring Security
        ack-after-processing = Kafka manual commit
    设计模式识别
      Repository 模式
        MailboxStore 定义存储接口
        FileMailboxStore 实现文件存储
        领域模型不依赖存储技术
      Worker 模式
        每个队友独立工作线程
        idle 状态可复用
        失败后报告 result 给 Lead
      租约模式
        processing 状态即租约
        只有租约持有者可 ack/release
        recover_processing 恢复遗留租约
      事件溯源
        message.id 同时是事件 ID
        done 目录保留完整历史
        可审计和重放
    关键概念理解
      四态状态机
        ready - 等待被消费
        processing - 正在处理（租约）
        done - 已完成
        quarantine - 隔离坏消息
      message.id 三重身份
        消息主键（全局唯一）
        事件去重 ID（_seen_event_ids）
        工具幂等键（ToolContext.idempotency_key）
      ack-after-processing 原则
        claim 后不立即 ack
        模型处理完成后才 ack
        ack 失败保留租约 + 保存到 pending
        模型失败 release 租约
      队友复用机制
        idle 队友保留 Runner 和历史
        收到消息时改状态 → running
        启动新线程，复用原 Runner
        历史自然延续
      sender 来源保护
        sender 只能来自 ToolContext.identity
        模型不能在 arguments 中传递 sender
        防止伪造发送者身份
        保证审计追踪可信
      故障恢复策略
        临时文件崩溃 → 无残留
        claim 后崩溃 → recover_processing
        ack 失败崩溃 → 保留租约补 ack
        模型失败 → release 重试
    面试题速查
      Q1: 为什么 message.id 同时充当事件 ID 和幂等键？
        事件去重 - _seen_event_ids 防止重复注入
        工具幂等 - idempotency_key 让工具副作用去重
        统一身份 - 一个消息一个稳定标识
        租约关联 - processing 文件名就是消息 ID
      Q2: FileMailboxStore 如何通过 rename 实现原子状态迁移？
        目录名即状态（ready/processing/done/quarantine）
        rename 原子性 - 文件系统保证
        条件更新 - 先检查目标不存在再 rename
        租约机制 - 只有 processing 可 ack/release
      Q3: 为什么事件回合完成后才 ack？
        at-least-once 语义 - claim 后立即 ack 会丢消息
        可重试性 - ack 前失败消息仍在 processing
        补确认机制 - ack 失败保存 pending 不重复调用模型
        租约保护 - 模型执行期间租约一直持有
      Q4: TeammateRuntime 如何复用 idle 队友的 Runner？
        状态转换 - 任务完成后 idle，线程退出
        唤醒机制 - send() 检测 idle 改状态 running
        历史保留 - _Worker.runner 不清空
        线程复用 - 新线程复用同一 Runner
      Q5: 为什么 sender 只能来自 ToolContext.identity？
        安全边界 - 防止模型伪造发送者
        审计追踪 - sender 由可信运行时提供
        身份传播 - Lead 回合是 lead，队友回合是队友名
        攻击场景 - 防止恶意 prompt 冒充身份
      Q6: recover_processing 在什么时机调用？
        启动时机 - TeammateRuntime.start() 和 spawn()
        故障场景 - claim 后、ack 前崩溃
        租约语义 - processing 即某消费者正在处理
        恢复策略 - 把所有 processing 退回 ready
      Q7: quarantine 目录的作用是什么？
        隔离坏消息 - JSON 损坏、字段缺失
        保留审计 - 不删除便于事后排查
        不阻塞队列 - 坏消息不卡住其他消息
        触发场景 - _valid_entries 自动隔离、主动调用
      Q8: _pending_event_acks 如何解决 ack 失败问题？
        问题场景 - 模型回合完成但 ack 失败
        租约状态 - 消息仍在 processing
        重复风险 - 直接 release 会重复调用模型
        解决方案 - 保存 (event, result) 下次只补 ack
```

## Java 开发者 4 步速通指南

### 第 1 步：从 Mailbox 领域模型开始（10 分钟）
```bash
# 阅读领域模型，理解消息字段和状态机
cat agent_ch15/features/mailbox.py

# 关注点：
# - MailboxMessage 的 6 个字段（id, sender, recipient, kind, content, created_at_utc）
# - 四态状态机（ready → processing → done/quarantine）
# - message.id 同时是事件 ID 和幂等键
# - canonical 校验函数（Agent 名和 UUID 格式）
```

**Java 对照**：这就像先读 `MailboxMessage` record 和 `MailboxRepository` 接口，理解领域模型再看实现。

### 第 2 步：理解原子持久化机制（15 分钟）
```bash
# 阅读 Repository 实现，理解原子操作
cat agent_ch15/adapters/mailbox_json.py

# 阅读顺序：
# 1. _atomic_write() - 临时文件 + fsync + rename 三段式
# 2. _move() - 原子状态迁移（目录名即状态）
# 3. send/claim/ack/release/quarantine - 六个核心操作
# 4. recover_processing() - 启动时恢复租约
```

**关键理解**：
- 目录名即状态，`rename` 即原子状态迁移
- `processing` 状态即租约，只有租约持有者可以 `ack` 或 `release`
- 全工作区锁防止并发写入冲突

### 第 3 步：掌握队友生命周期（15 分钟）
```bash
# 阅读运行时管理，理解 Worker 模式
cat agent_ch15/features/teammates.py

# 阅读顺序：
# 1. TeammateRuntime.__init__ - 依赖注入
# 2. spawn() - 注册队友 + 启动 worker
# 3. send() - 发消息 + 唤醒 idle 队友
# 4. _run_worker() - 工作循环（claim → run → send result → ack）
# 5. _publish_lead() - Lead 消息发布到 EventInbox
```

**重点理解**：
- 每个队友独立 `AgentRunner` + 独立历史
- idle 状态可复用（保留 Runner 和历史）
- 失败后报告 result 给 Lead

### 第 4 步：理解事件回合与 ack-after-processing（15 分钟）
```bash
# 阅读核心循环的事件处理
cat agent_ch15/core/loop.py

# 重点查看 run_events() 方法：
# 1. 优先处理 _pending_event_acks（补确认）
# 2. 取下一条事件（deferred 或 drain）
# 3. 执行事件回合
# 4. ack 成功 → 返回结果
# 5. ack 失败 → 保存到 pending 字典（保留租约）
# 6. 模型失败 → release 租约
```

**不要深入其他方法**：这一步只关注 `run_events()` 的 ack-after-processing 逻辑。

---

## 核心类比速查表

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `MailboxMessage` | `record MailboxMessage(...)` | 不可变消息 |
| `MailboxStore` | `MailboxRepository` 接口 | Repository 契约 |
| `FileMailboxStore` | 文件版 Repository | 实现类 |
| `TeammateRuntime` | `ExecutorService` + 注册表 | 受管 WorkerService |
| `_Worker` | `Callable<Void>` | 可复用的工作线程 |
| `EventInbox` | `BlockingQueue<RuntimeEvent>` | 线程安全队列 |
| `_atomic_write` | `Files.move(ATOMIC_MOVE)` | 原子文件操作 |
| `_move` (状态迁移) | `UPDATE WHERE state=?` | 条件更新 |
| `canonical_agent_name` | `@Pattern` 校验注解 | Bean Validation |
| `ToolContext.identity` | `@AuthenticationPrincipal` | 安全上下文 |
| `recover_processing` | `@EventListener(ContextRefreshedEvent)` | 启动时恢复 |
| ack-after-processing | Kafka `enable.auto.commit=false` | 手动确认 |

---

## 学完本章你会理解

✅ **Mailbox 四态状态机**：ready/processing/done/quarantine 的流转规则  
✅ **原子状态迁移**：通过文件系统 rename 实现无锁条件更新  
✅ **租约机制**：processing 状态即租约，防止重复消费  
✅ **队友复用机制**：idle 状态保留 Runner 和历史，收到消息时唤醒  
✅ **ack-after-processing 原则**：模型处理完成后才 ack，ack 失败只补确认  
✅ **sender 来源保护**：ToolContext.identity 保证审计追踪可信  

---

## 常见问题 FAQ

### Q1: 为什么需要四态状态机而不是两态（待处理/已完成）？
**A**: 四态提供了更精细的控制：
- `ready`: 等待被消费
- `processing`: 正在处理（租约），防止重复消费
- `done`: 已完成，保留历史用于审计
- `quarantine`: 隔离坏消息，不阻塞其他消息

### Q2: 为什么 `_atomic_write` 需要 fsync？
**A**: `fsync` 确保数据真正写入磁盘，而不是停留在操作系统缓存。否则进程崩溃时，已经 `close()` 的临时文件可能丢失数据。这是文件系统持久化的标准做法。

### Q3: 为什么 `claim` 后不立即 `ack`？
**A**: 如果 `claim` 后立即 `ack`，模型执行失败时消息已被标记为 `done`，无法重试。`ack-after-processing` 保证了 at-least-once 语义：只有模型处理成功后才确认。

### Q4: `_pending_event_acks` 和 `recover_processing` 有什么区别？
**A**: 
- `_pending_event_acks`: 模型处理完成但 `ack` 失败，保留租约，下次只补确认
- `recover_processing`: 进程崩溃后启动时，把所有遗留租约退回 `ready`

前者是同一进程内的补偿，后者是跨进程的恢复。

### Q5: 为什么队友失败后要发送 result 给 Lead？
**A**: Lead 需要知道队友失败了，否则会一直等待回复。发送 result（包含错误信息）让 Lead 可以决定是否重试、换个队友或者放弃任务。

### Q6: `messages_equal` 为什么需要完整快照比较？
**A**: 防止只凭 ID 错误确认不同正文的消息。例如：
1. 消息 A 写入 `processing`
2. 进程崩溃，`recover_processing` 退回 `ready`
3. 消息 A 被重新处理，写入新的 `processing`
4. 旧进程恢复，尝试 `ack` 旧消息

完整快照比较确保 `ack` 的是当前正在处理的消息，而不是历史版本。

---

## 下一步学习建议

1. **动手运行测试**：`pytest tests/test_mailbox.py tests/test_teammates.py -v`
2. **修改状态机**：尝试添加 `retrying` 状态，限制重试次数
3. **实现数据库版 Repository**：用 SQLite 替换文件存储
4. **追踪一次完整通信**：在 `spawn/send/claim/ack` 处打断点，观察消息流转

---

## 文件依赖关系图

```
TeammateRuntime (teammates.py)
    ├── depends on → MailboxStore (mailbox.py)
    ├── depends on → EventInbox (events.py)
    ├── depends on → AgentRunner (loop.py)
    └── owns → _Worker (内部类)
        └── owns → AgentRunner (独立实例)

MailboxStore (接口)
    └── implemented by → FileMailboxStore (mailbox_json.py)

AgentRunner (loop.py)
    ├── has → run_events() 方法
    └── uses → _pending_event_acks (字典)

FileMailboxStore
    ├── uses → _atomic_write (原子写入)
    ├── uses → _move (原子迁移)
    └── manages → 四态目录结构
```

---

## 总结：Ch15 的三个核心职责

1. **可靠消息投递**：通过四态状态机和租约机制保证 at-least-once
2. **队友生命周期管理**：独立 Runner + 复用机制 + 失败报告
3. **事件回合隔离**：ack-after-processing + pending 补确认 + 身份切换

**记住**：`TeammateRuntime` 是编排者，不是执行者。它不知道如何调用 OpenAI API，也不知道如何处理 PowerShell，它只负责把消息路由到正确的队友、管理生命周期、处理失败恢复。
