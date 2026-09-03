# 第 13 章：后台任务系统学习导航图

## 学习脑图

```mermaid
mindmap
  root((第 13 章<br/>后台任务系统))
    学习路线（推荐顺序）
      第一步：理解后台需求
        tests/test_ch13_integration.py
        tests/test_background.py
        看后台任务应该做什么
        理解成功标准
      第二步：读核心领域模型
        features/background.py
        BackgroundJob 状态机
        JobSupervisor 线程管理
        BackgroundJobEvent 事件发布
      第三步：理解工具分流机制
        core/loop.py _execute_tool
        ToolDispatcher 接口
        dispatch 返回 None 继续同步执行
      第四步：集成到 Profile
        core/profiles.py P13
        bootstrap.py 组装逻辑
        P13 = P12 + background
    核心文件清单
      features/background.py（后台领域）
        BackgroundJob（状态快照）
          id: canonical UUID
          source_tool_call_id: 原始调用 ID
          status: 6 种状态
          result: 终态携带结果
        JobSupervisor（线程池）
          capacity: 并发容量
          timeout: 超时控制
          _recover: 启动恢复
          submit: 提交后台任务
          cancel: 取消运行任务
          close: 关闭并等待
        BackgroundJobEvent（事件）
          to_payload: 发布给模型
        BackgroundDispatcher（分流器）
          dispatch: 判断是否后台执行
          _should_background: 启发式识别
      core/loop.py（循环集成）
        ToolDispatcher 接口
          dispatch 返回 None = 同步执行
          dispatch 返回 ToolResult = 立即返回
        _execute_tool 调用链
          prepare → Pre Hook → permission
          → dispatch → invoke → Post Hook
      adapters/background_json.py（持久化）
        JsonBackgroundJobStore
          create_running: 创建运行任务
          finish_running: 标记终态
          interrupt_running: 恢复中断
          _safe_read: 容错读取
          _atomic_write: 原子写入
      core/events.py（事件泵）
        RuntimeEvent 接口
        EventInbox（内存队列）
        RuntimeEventPump 接口
          drain_events: 非阻塞取事件
          wait_for_events: 阻塞等待
    Java 对照关系
      并发模型对照
        threading.Thread = Thread
        threading.Event = CountDownLatch
        threading.RLock = ReentrantLock
        queue.Queue = BlockingQueue
      状态管理对照
        BackgroundJob frozen = 不可变状态 DTO
        JobSupervisor _controls = ConcurrentHashMap
        状态机迁移 = 状态模式
      异常处理对照
        BackgroundError = 领域异常
        error_code 字段 = 错误码枚举
        Protocol = 依赖倒置接口
      持久化对照
        BackgroundJobStore = Repository 接口
        JsonBackgroundJobStore = 文件实现
        原子写入 = 临时文件 + rename
    设计模式识别
      状态模式
        6 种状态：running/completed/failed/timed_out/cancelled/interrupted
        状态迁移规则强校验
        __post_init__ 检查状态一致性
      观察者模式
        JobSupervisor 发布事件到 EventInbox
        AgentRunner 通过 RuntimeEventPump 消费
        事件去重（_seen_event_ids）
      策略模式
        ToolDispatcher 决定执行策略
        启发式识别（BACKGROUND_MARKERS）
        run_in_background 参数显式控制
      线程池模式
        容量控制（capacity）
        超时管理（timeout）
        优雅关闭（close_timeout）
    关键概念理解
      为什么需要后台任务
        长时间操作（编译、部署）
        避免阻塞 Agent 循环
        超时保护（120 秒默认）
      工具分流机制
        ToolDispatcher.dispatch 返回值语义
        None = 继续同步执行
        ToolResult = 立即返回给模型
        后台任务返回 job_id 作为 ToolResult
      状态机设计原则
        running 状态不携带 result
        终态必须携带 result
        completed 必须是成功结果
        失败终态必须是错误结果
      事件发布与去重
        BackgroundJobEvent 封装终态
        event_id 用于去重
        _seen_event_ids 防止重复注入
      恢复机制
        启动时调用 _recover
        interrupt_running 标记遗留任务
        发布 interrupted 事件通知模型
      原子写入保证
        写临时文件 .tmp
        rename 原子替换
        防止并发读到半写状态
    面试题速查
      Q1：后台任务的状态迁移规则
        A：6 种状态 running → (completed | failed | timed_out | cancelled | interrupted)
        running 不携带 result，终态必须携带 result
        completed 必须是成功结果，其他终态必须是错误结果
        __post_init__ 强校验防止非法状态
      Q2：ToolDispatcher 的返回值语义
        A：dispatch 返回 None 表示继续同步执行工具（fallback）
        返回 ToolResult 表示立即返回给模型（短路后续 invoke）
        后台场景：返回包含 job_id 的成功 ToolResult
        同步场景：返回 None，让 loop 调用 tools.invoke
      Q3：为什么需要 source_tool_call_id
        A：关联后台任务与原始工具调用，用于事件回填时的上下文追踪
        模型可以通过 source_tool_call_id 理解哪个调用进入了后台
        查询后台任务时可以定位到原始请求
      Q4：并发容量控制如何实现
        A：JobSupervisor 维护 _controls 字典（job_id → (Thread, Event)）
        submit 前检查 len(_controls) >= capacity，满则拒绝
        worker 完成后从 _controls 删除，释放槽位
        RLock 保护 _controls 的并发修改
      Q5：为什么启动时要调用 _recover
        A：上次进程可能异常退出，留下 running 状态的孤儿任务
        interrupt_running 把所有 running 标记为 interrupted
        发布 interrupted 事件让模型知道这些任务已失败
        _ready 标志表示恢复完成，防止重复恢复
      Q6：事件去重机制
        A：每个 BackgroundJobEvent 有唯一 event_id（UUID）
        AgentRunner 维护 _seen_event_ids 集合
        _inject_runtime_events 过滤已见事件
        防止同一终态事件重复注入历史
      Q7：超时检测如何实现
        A：worker 线程开始时记录 start_time
        while 循环每 0.1 秒检查 time.time() - start_time > timeout
        超时时设置 cancel_event，operation 可以感知取消
        超时后标记为 timed_out 状态
      Q8：优雅关闭流程
        A：close 设置 _closed = True，拒绝新任务
        设置所有 cancel_event，通知 worker 取消
        join(close_timeout) 等待线程完成
        超时未完成的线程被标记为 interrupted
        保证所有任务都有终态事件
```

## Java 开发者 3 步速通指南

### 第 1 步：从测试看目标（15 分钟）

```bash
# 阅读集成测试，理解后台任务的完整流程
cat tests/test_ch13_integration.py
cat tests/test_background.py

# 关注点：
# - 后台任务如何提交（run_in_background 参数）
# - 状态如何查询（query_background_job）
# - 事件如何回填（BackgroundJobEvent）
```

**Java 对照**：这就像 `ExecutorServiceTest.java`，理解异步任务的生命周期。

### 第 2 步：读核心领域模型（25 分钟）

```bash
# 阅读后台任务的核心实现
cat features/background.py

# 阅读顺序：
# 1. BackgroundJob 数据类（状态快照）
# 2. JobSupervisor.__init__（线程池初始化）
# 3. JobSupervisor.submit（提交任务）
# 4. JobSupervisor._worker（工作线程）
# 5. JobSupervisor.close（优雅关闭）
```

**关键理解**：
- `threading.Thread` = Java 的 `Thread`
- `threading.Event` = Java 的 `CountDownLatch`
- `threading.RLock` = Java 的 `ReentrantLock`
- `queue.Queue` = Java 的 `BlockingQueue`

### 第 3 步：理解集成到 Loop（15 分钟）

```bash
# 理解工具分流机制
cat core/loop.py  # 查找 _execute_tool 和 _tool_dispatcher

# 理解事件注入
grep -n "_inject_runtime_events" core/loop.py

# 理解 Profile 组装
cat core/profiles.py | grep -A 5 "P13"
```

**不要深入细节**：先理解后台任务如何插入现有 Agent 循环，细节后续再看。

---

## 核心类比速查表

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `threading.Thread` | `Thread` | 工作线程 |
| `threading.Event` | `CountDownLatch` | 取消信号 |
| `threading.RLock` | `ReentrantLock` | 可重入锁 |
| `queue.Queue` | `BlockingQueue` | 线程安全队列 |
| `BackgroundJob` | 不可变状态 DTO | 任务快照 |
| `JobSupervisor` | `ExecutorService` | 线程池管理器 |
| `ToolDispatcher` | 策略接口 | 执行策略分发 |
| `RuntimeEvent` | 事件接口 | 异步通知 |

---

## 学完本章你会理解

✅ **后台任务状态机**：6 种状态及迁移规则  
✅ **工具分流机制**：ToolDispatcher 的返回值语义  
✅ **线程池模式**：容量控制、超时管理、优雅关闭  
✅ **事件发布与去重**：RuntimeEvent 如何注入 Agent 循环  
✅ **恢复机制**：启动时如何处理遗留任务  
✅ **原子写入**：临时文件 + rename 保证一致性  

---

## 常见问题 FAQ

### Q1: 为什么 `dispatch` 返回 `None` 表示继续同步执行？
**A**: 因为 `ToolDispatcher` 是可选的策略层，返回 `None` 表示"我不处理，继续默认流程"。只有明确返回 `ToolResult` 才会短路后续的 `invoke` 调用。

### Q2: 为什么后台任务返回 `job_id` 而不是真实结果？
**A**: 因为任务是异步的，提交时结果还不存在。返回 `job_id` 让模型知道"任务已提交"，后续通过事件获取真实结果。

### Q3: 为什么需要 `source_tool_call_id`？
**A**: 关联后台任务与原始工具调用。事件回填时，模型可以通过这个 ID 理解"之前哪个调用的结果现在到了"。

### Q4: 为什么 `running` 状态不携带 `result`？
**A**: 因为任务还在执行中，结果不存在。只有终态（completed/failed/...）才有结果。这是状态一致性约束。

### Q5: 为什么启动时要调用 `_recover`？
**A**: 上次进程可能异常退出，留下 `running` 状态的孤儿任务。恢复时把它们标记为 `interrupted`，并发布事件通知模型。

### Q6: 为什么用 `RLock` 而不是 `Lock`？
**A**: `RLock`（可重入锁）允许同一线程多次获取锁。`JobSupervisor` 内部方法可能相互调用，需要可重入性。

---

## 下一步学习建议

1. **动手运行测试**：`pytest tests/test_background.py -v`
2. **修改 `capacity`**：改成 2，提交 3 个任务看拒绝行为
3. **实现自定义 Dispatcher**：练习启发式识别逻辑
4. **观察超时行为**：用 `time.sleep` 模拟慢工具，看超时检测

---

## 文件依赖关系图

```
AgentRunner (loop.py)
    ├── optional → ToolDispatcher (loop.py Protocol)
    │   └── implemented by → BackgroundDispatcher (background.py)
    └── optional → RuntimeEventPump (loop.py Protocol)
        └── implemented by → EventInbox (events.py)

BackgroundDispatcher (background.py)
    ├── depends on → JobSupervisor (background.py)
    └── depends on → ToolRegistry (tools.py)

JobSupervisor (background.py)
    ├── depends on → BackgroundJobStore (background.py Protocol)
    │   └── implemented by → JsonBackgroundJobStore (adapters/background_json.py)
    └── depends on → EventInbox (events.py)

BackgroundJob (background.py)
    └── contains → ToolResult (tools.py)
```

---

## 总结：后台任务系统的三个核心职责

1. **任务提交与执行**：通过 `JobSupervisor` 管理线程池，控制并发和超时
2. **状态持久化**：通过 `BackgroundJobStore` 原子写入任务状态，支持恢复
3. **事件回填**：通过 `EventInbox` 发布终态事件，注入 Agent 循环让模型感知结果

**记住**：`JobSupervisor` 是编排者，`BackgroundDispatcher` 是策略决策者，`JsonBackgroundJobStore` 是持久化实现者。它们通过接口解耦，测试时可以用 Fake 替换。
