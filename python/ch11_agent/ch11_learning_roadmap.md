# 第 11 章：模型 API 恢复策略学习导航图

## 学习脑图

```mermaid
mindmap
  root((第 11 章<br/>模型 API 恢复策略))
    学习路线（推荐顺序）
      第一步：读测试了解故障场景
        tests/test_recovery.py
        理解三种故障类型
        观察每种故障的恢复策略
      第二步：读恢复管理器
        features/recovery.py
        RecoveryManager.complete() 方法
        理解升级→续写→压缩→退避流程
      第三步：理解异常映射
        adapters/openai_chat.py
        core/model.py
        供应商错误如何归一化
      第四步：理解接入点
        core/loop.py
        bootstrap.py
        哪些请求使用恢复层
    核心文件清单
      features/recovery.py（恢复层）
        RecoveryManager 类
          begin_turn() 重置状态
          complete() 主恢复循环
          _retry_transient() 退避逻辑
        RecoveryConfig
          primary_model / fallback_model
          initial_max_tokens / escalated_max_tokens
          max_continuations / max_transient_attempts
        RecoveryState
          current_model / current_max_tokens
          has_escalated / recovery_count
          consecutive_529
        CancellationToken
          is_cancelled 属性
          cancel() 方法
          subscribe() 监听器
      core/model.py（异常定义）
        ModelClient 接口
        ModelRateLimitError（429）
        ModelOverloadedError（529）
        ModelPromptTooLongError（输入过长）
      adapters/openai_chat.py（适配器）
        _map_api_status_error()
        把 OpenAI/DeepSeek 错误转换为内部异常
        读取 Retry-After 头
      core/loop.py（接入点）
        ModelRequestExecutor 接口
        AgentRunner 使用 executor
        begin_turn() / complete() 调用
    Java 对照关系
      核心概念对照
        RecoveryManager = Resilience Service
        CancellationToken = AtomicBoolean + listeners
        ModelRequestExecutor = Strategy 接口
        异常映射 = Adapter 层职责
      设计模式对照
        适配器模式（供应商错误归一化）
        策略模式（可插拔恢复层）
        状态模式（RecoveryState）
        装饰器模式（包装 ModelClient）
      技术对照
        指数退避 = Exponential Backoff
        Retry-After = HTTP 标准头
        Jitter = 随机抖动避免惊群
        Deadline = 总超时时限
      异常处理对照
        RecoveryError = 恢复层基础异常
        RecoveryCancelledError = 取消异常
        RecoveryRetriesExhausted = 重试耗尽
        RecoveryDeadlineExceeded = 超时异常
    设计模式识别
      适配器模式
        供应商异常 → 内部异常
        _map_api_status_error() 映射函数
        核心层不依赖 OpenAI SDK
      策略模式
        ModelRequestExecutor 接口
        raw model 或 RecoveryManager
        Bootstrap 决定使用哪个策略
      状态模式
        RecoveryState 可变状态
        has_escalated / recovery_count
        每个 turn 重置状态
      装饰器模式
        RecoveryManager 包装 ModelClient
        透明增加恢复能力
        外层感知不到内部重试
    关键概念理解
      三种故障类型
        输出截断：finish_reason == 'length'
        输入过长：ModelPromptTooLongError
        临时故障：429/529 错误
      输出截断恢复
        第一次：升级 max_tokens 到 64000
        第二次：追加片段并续写
        成功后合并所有片段
      输入过长恢复
        保留首条 system message
        调用 CompactionManager 压缩
        一次请求只压缩一次
      临时故障恢复
        429：优先遵守 Retry-After
        529：连续 3 次切换 fallback
        指数退避 + 随机抖动
      取消与超时
        CancellationToken 通知机制
        每次边界检查取消状态
        总 deadline 保护
    面试题速查
      Q1: 为什么需要恢复层？
        A: 真实生产环境存在三类故障
        输出截断、输入过长、临时 API 错误
        恢复层统一处理，避免每个调用点重复实现
      Q2: 为什么供应商错误要归一化？
        A: 核心层不应依赖 OpenAI SDK
        适配器层负责转换为领域异常
        切换供应商时只改适配器
      Q3: 输出截断为什么分两步处理？
        A: 第一次可能只是预算设小了
        直接升级到 64000 更经济
        仍截断才启动续写机制
      Q4: 为什么摘要请求不能套恢复层？
        A: 避免递归：输入过长→摘要→输入过长
        摘要请求使用 raw ModelClient
        摘要本身应该足够短
      Q5: 指数退避为什么要加 Jitter？
        A: 避免惊群效应
        多个客户端同时重试会再次过载
        随机抖动分散请求时间
      Q6: 为什么连续 3 次 529 才切 fallback？
        A: 偶发性过载应该重试
        连续失败说明主模型持续不可用
        3 次是经验值，可配置
      Q7: CancellationToken 和 Python 的区别？
        A: Python 同步 SDK 无法中断运行中调用
        只能在调用边界和等待阶段检查
        TypeScript AbortSignal 可强制中止
      Q8: 为什么外层历史不包含续写消息？
        A: 续写发生在局部 request_messages
        成功后合并为一条完整回复
        外层只看到最终结果，不知道内部重试
```

## Java 开发者 4 步速通指南

### 第 1 步：从测试理解故障场景（10 分钟）
```bash
# 阅读测试文件，看三种故障如何触发和恢复
cat tests/test_recovery.py

# 关注点：
# - 输出截断（finish_reason == "length"）如何升级预算和续写
# - 输入过长（ModelPromptTooLongError）如何触发压缩
# - 临时故障（429/529）如何退避和切换模型
```

**Java 对照**：这就像先读 `ResilienceServiceTest.java`，理解三类故障的预期行为。

### 第 2 步：读恢复管理器核心循环（20 分钟）
```bash
# 阅读带详细注释的恢复层
cat features/recovery.py

# 阅读顺序：
# 1. RecoveryConfig（不可变配置）
# 2. RecoveryState（可变状态）
# 3. RecoveryManager.complete()（主恢复循环）
# 4. _retry_transient()（退避逻辑）
```

**关键理解**：
- `RecoveryManager` = Java 的 Resilience Service（Hystrix/Resilience4j）
- `CancellationToken` = `AtomicBoolean` + 监听器集合
- `while True` 循环 = 一次逻辑请求内部的多次物理重试
- 外层 `AgentRunner` 只调用一次 `executor.complete()`

### 第 3 步：理解异常映射机制（10 分钟）
```bash
# 看供应商错误如何归一化
cat adapters/openai_chat.py | grep -A 20 "_map_api_status_error"
cat core/model.py | grep "class Model.*Error"
```

**重点理解**：
- 适配器层捕获 `APIStatusError`，转换为 `ModelRateLimitError` 等
- 核心层只依赖领域异常，不依赖 OpenAI SDK
- 这是"Adapter 层把第三方异常转换成领域异常"的标准做法

### 第 4 步：理解如何接入 Agent Loop（5 分钟）
```bash
# 看恢复层如何被使用
cat core/loop.py | grep -A 5 "ModelRequestExecutor"
cat bootstrap.py | grep -A 10 "RecoveryManager"
```

**关键点**：
- `ModelRequestExecutor` 接口 = Strategy 模式
- 第 1-10 章用 raw model，第 11 章用 `RecoveryManager`
- 记忆/压缩/子 Agent 的模型请求继续用 raw model（避免递归）

---

## 核心类比速查表

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `RecoveryManager` | Resilience Service | 请求恢复编排器 |
| `CancellationToken` | `AtomicBoolean` + listeners | 取消通知机制 |
| `ModelRequestExecutor` | Strategy 接口 | 可插拔请求执行器 |
| `RecoveryConfig` | `record` 不可变配置 | 恢复策略参数 |
| `RecoveryState` | 可变状态对象 | 当前回合状态 |
| `_map_api_status_error` | Adapter 映射方法 | 异常转换 |
| 指数退避 | Exponential Backoff | 重试延迟策略 |
| Jitter | 随机抖动 | 避免惊群效应 |

---

## 学完本章你会理解

✅ **三种故障的恢复策略**：输出截断、输入过长、临时 API 错误  
✅ **供应商错误归一化**：适配器层转换异常，核心层供应商无关  
✅ **指数退避与 Jitter**：避免惊群效应的重试策略  
✅ **Fallback 模型切换**：连续 529 自动切换备用模型  
✅ **取消与超时机制**：CancellationToken + 总 deadline 保护  
✅ **续写与压缩协同**：输出截断续写、输入过长压缩  
✅ **接入点设计**：ModelRequestExecutor 策略接口  
✅ **递归避免**：摘要请求不能套恢复层  

---

## 常见问题 FAQ

### Q1: 为什么需要恢复层？
**A**: 真实生产环境存在三类故障：输出截断（token 上限）、输入过长（上下文超限）、临时 API 错误（429/529）。恢复层统一处理这些故障，避免每个调用点重复实现重试逻辑。

### Q2: 为什么供应商错误要归一化？
**A**: 核心层不应依赖 OpenAI SDK 的具体错误类型。适配器层负责把 `APIStatusError` 转换为 `ModelRateLimitError` 等领域异常。切换供应商（如改用 Anthropic）时，只需修改适配器层。

### Q3: 输出截断为什么分两步处理？
**A**: 第一次截断可能只是 `max_tokens` 设小了（8000），直接升级到 64000 更经济。如果升级后仍截断，说明回答确实很长，才启动续写机制（追加片段 + CONTINUATION_PROMPT）。

### Q4: 为什么摘要请求不能套恢复层？
**A**: 避免递归：输入过长 → 调用压缩 → 摘要请求也过长 → 又调用压缩 → 无限递归。摘要请求使用 raw `ModelClient`，不走恢复层。摘要本身应该足够短。

### Q5: 指数退避为什么要加 Jitter？
**A**: 避免惊群效应。如果多个客户端同时遇到 429，按固定间隔重试（0.5s、1s、2s...），会在相同时刻再次涌入，导致二次过载。加随机抖动（Jitter）能分散请求时间。

### Q6: 为什么连续 3 次 529 才切 fallback？
**A**: 偶发性过载（单次 529）应该重试，不应立即放弃主模型。连续 3 次失败说明主模型持续不可用，此时切换到 fallback 模型。3 次是经验值，可通过 `overload_fallback_threshold` 配置。

### Q7: CancellationToken 和异步框架有什么区别？
**A**: Python 当前 `ModelClient.complete()` 是同步接口，无法像 TypeScript `AbortSignal` 那样强制中止运行中的 HTTP 请求。只能在调用边界（请求前后）和可取消的等待阶段（`Event.wait`）检查取消状态。

### Q8: 为什么外层历史不包含续写消息？
**A**: 续写发生在局部 `request_messages`，不会修改 `AgentRunner` 的 canonical history。成功后，`_merge_fragments` 把所有片段合并为一条完整 `AssistantMessage`。外层只看到最终结果，感知不到内部重试。

### Q9: 为什么 429 成功后清零 consecutive_529？
**A**: `consecutive_529` 只统计连续的 529 错误。429（限流）和成功响应都会重置计数，因为它们说明主模型可用，不需要切换 fallback。

### Q10: Retry-After 为什么支持 HTTP-date 格式？
**A**: HTTP 标准允许 `Retry-After: 120`（秒数）或 `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT`（绝对时间）。后者在跨时区场景更精确。`parsedate_to_datetime` 负责解析 RFC 2822 日期格式。

---

## 下一步学习建议

1. **运行单元测试**：`pytest tests/test_recovery.py -v`，观察每种故障的恢复路径
2. **打断点调试**：在 `RecoveryManager.complete()` 的 `while True` 循环设断点
3. **修改配置**：改 `max_continuations=1`，看续写次数用尽时抛出什么异常
4. **阅读集成测试**：`tests/test_ch11_integration.py`，看真实章节装配后的完整行为
5. **对比第 10 章**：看 `CompactionManager` 如何被恢复层调用

---

## 三种故障恢复流程图

### 输出截断恢复
```
finish_reason == "length"
    ↓
第一次？→ 升级 max_tokens: 8000 → 64000，重试
    ↓
仍截断？→ 追加片段 + CONTINUATION_PROMPT，续写
    ↓
成功 → 合并所有片段，返回完整回复
```

### 输入过长恢复
```
ModelPromptTooLongError
    ↓
分离首条 system message
    ↓
调用 CompactionManager.compact_on_prompt_too_long()
    ↓
拼接：(system, *压缩后的历史)
    ↓
重试（一次请求只压缩一次）
```

### 临时故障恢复
```
429 / 529
    ↓
429？→ 优先遵守 Retry-After 头
    ↓        ↓（没有头）
    ↓    指数退避 + Jitter
    ↓
529？→ consecutive_529 += 1
    ↓
达到阈值（3 次）？→ 切换 fallback_model
    ↓
等待后重试
```

---

## 文件依赖关系图

```
AgentRunner (core/loop.py)
    ├── depends on → ModelRequestExecutor (接口)
    │       ├── raw ModelClient (第 1-10 章)
    │       └── RecoveryManager (第 11 章)
    │
RecoveryManager (features/recovery.py)
    ├── depends on → ModelClient (adapters/openai_chat.py)
    ├── depends on → CompactionManager (features/compaction.py)
    ├── uses → RecoveryConfig (不可变配置)
    └── uses → RecoveryState (可变状态)

ModelClient (接口)
    └── implemented by → OpenAIChatClient (adapters/openai_chat.py)
            └── maps → APIStatusError → ModelRateLimitError / ModelOverloadedError / ModelPromptTooLongError
```

---

## 总结：恢复层的三个核心职责

1. **故障识别**：区分输出截断、输入过长、临时故障三类问题
2. **透明恢复**：内部升级预算、续写、压缩、退避，外层无感知
3. **供应商隔离**：核心层只依赖领域异常，不依赖 OpenAI SDK

**记住**：`RecoveryManager` 是装饰器，不是替代品。它包装 `ModelClient`，透明增加恢复能力，让 `AgentRunner` 感觉自己只调用了一次模型。
