# 第 20 章：完整 Agent Harness 学习导航图

## 学习脑图

```mermaid
mindmap
  root((第 20 章<br/>完整 Agent Harness))
    学习路线（推荐顺序）
      第一步：读验收测试理解目标
        tests/test_ch20_full_harness.py
        看完整 Harness 应该做什么
        理解跨能力整合的验收标准
        四条不变量同时成立
      第二步：读章节能力档案
        core/profiles.py
        理解增量表设计
        P20 是 P01-P19 的严格超集
        capability 累计推导
      第三步：读组合根装配逻辑
        bootstrap.py
        build_agent 函数
        共享关系对象身份校验
        运行态状态提供者
      第四步：理解真实运行入口
        cli.py
        参数解析与配置校验
        资源创建与逆序关闭
        统一错误处理
      第五步：浏览动态 Prompt 渲染
        features/prompting.py
        runtime_status 尾部段落
        状态提供者机制
    核心文件清单
      core/profiles.py（章节能力档案）
        ChapterProfile 数据类
          chapter: 章节号
          capabilities: 能力白名单
        增量表 _PROFILE_DELTAS
          每章只声明新增能力
          前缀累加成完整档案
        P01 到 P20 常量
          预定义单例对象
          对象身份校验
        profile_for_chapter 函数
          按章节号取固定档案
          拒绝非整数和越界输入
      bootstrap.py（唯一组合根）
        build_agent 函数
          接受 ChapterProfile 参数
          校验能力与依赖匹配
          对象身份而非类型校验
        _full_harness_runtime_status
          汇总 MCP 连接状态
          汇总异步工作状态
          lambda 捕获运行时引用
        共享关系校验
          同一个 EventInbox
          同一个 JobSupervisor
          同一个 SqliteTaskStore
          同一个 WorktreeRuntime
      cli.py（真实运行入口）
        LiveRuntime 数据类
          settings: 配置对象
          build_kwargs: 装配参数
          cron_runtime: 需要 start
          teammate_runtime: 需要 start
          closables: 逆序关闭列表
        create_live_runtime 函数
          按 P20 能力创建运行时
          建立共享关系
          validate_repository 前置校验
        execute 函数
          保证资源释放
          成功与失败路径统一
          ExceptionGroup 聚合错误
        main 函数
          解析命令行参数
          查找并校验 .env 配置
          返回统一错误码
      core/loop.py（Agent 主循环）
        AgentRunner 类
          run 方法（主循环）
          _inject_runtime_events
          _render_system_prompt
          close 逆序关闭资源
        SystemPromptProvider 接口
          render 方法
          每轮重新读取状态
        ToolContextProvider 接口
          resolve 方法
          workspace 信任根校验
        RuntimeEventPump 接口
          drain_events 批量取事件
          acknowledge_events 确认
      features/prompting.py（动态 Prompt）
        DynamicPromptRenderer 类
          render 方法
          缓存键与缓存值
          status 可选尾部段落
        DynamicPromptProvider 类
          绑定运行态对象
          status_provider 回调
          每轮重新调用
        DynamicPromptStatusProvider
          类型别名 Callable
          返回 Mapping[str, object]
          lambda 捕获运行时
    Java 对照关系
      数据结构对照
        ChapterProfile = 不可变 record
        frozenset = Set.copyOf
        tuple = List.copyOf
        LiveRuntime = 持有单例的 Context
      类型系统对照
        Protocol = interface
        @runtime_checkable = 允许 instanceof
        Callable[[],T] = Supplier<T>
        T | None = Optional<T>
      设计模式对照
        bootstrap.py = @Configuration 类
        cli.py = Spring Boot main
        profiles.py = enum 常量 + record
        对象身份校验 = 只接受 enum 常量
      资源管理对照
        try/finally + close = try-with-resources
        closables 逆序遍历 = 逆创建顺序释放
        ExceptionGroup = AggregateError
    设计模式识别
      唯一组合根
        bootstrap.build_agent
        所有跨能力共享在此建立
        能力越级注入在此拒绝
      对象身份校验
        is 而非 ==
        调用方不能伪造
        类似 enum 常量校验
      增量表推导
        _PROFILE_DELTAS 只记录增量
        _build_profiles 累计推导
        超集关系由结构保证
      状态提供者模式
        lambda 捕获运行时引用
        每轮重新读取
        而非构建期快照
      资源所有权
        成功时 Runner 统一关闭
        失败时 closables 兜底
        逆序关闭保证依赖
    关键概念理解
      完整 Harness 的本质
        不是新框架
        不是第二套 Loop
        是所有能力的整合验证
      四条核心不变量
        动态工具下一轮才可见
        tool call 必须恰好配对
        Prompt 不是授权边界
        资源关闭必须逆序
      能力累计推导
        第 N 章是第 N-1 章的严格超集
        由数据结构保证
        不靠人工核对
      共享关系的对象身份
        同一个 inbox
        同一个 supervisor
        同一个 task_store
        build_agent 用 is 校验
      运行态状态段落
        runtime_status 固定最后
        状态变化不移动前面段落
        每轮重新读取
        不替代 typed event
      资源关闭的两条路径
        成功：Runner.close 统一逆序
        失败：closables 兜底逆序
        任何路径都不遗留资源
    面试题速查（6-8 道）
      Q1: P20 为什么叫"完整 Harness"而不是"第二十章新能力"？
        A: 因为 P20 不发明新框架，也不增加独立运行时。它只做一件事：把 P01-P19 的全部能力接到同一个组合根，并用跨功能场景证明这些边界同时成立。full_harness 是验收标记能力，表示前十九章的 capability 已经在同一个 build_agent() 中连接并通过交叉验证。
        Java 类比：类似 Spring Boot 的 @SpringBootTest 集成测试——不 mock 内部协作者，只把最外层边界（模型、命令执行器、MCP 连接）换成可控 fake。
      Q2: 为什么 build_agent 用对象身份（is）而不是类型来校验 ChapterProfile？
        A: 因为调用方不能临时构造一个同字段 ChapterProfile 来冒充正式章节。profile_for_chapter 只返回模块内固定单例（P01-P20），build_agent 用 `is` 判断，类似 Java 只接受 enum 常量而不接受 new 出来的等值对象。这样能力越级注入（把 P19 的运行时偷偷传给 P03）会在装配阶段被拒绝。
        关键代码：`if profile_for_chapter(profile.chapter) is not profile: raise ValueError("必须传入固定的章节配置对象")`
      Q3: 增量表 _PROFILE_DELTAS 如何保证"第 N 章是第 N-1 章的严格超集"？
        A: 每章只声明本章新增的能力，_build_profiles() 用 extend 把前缀累加成完整档案。因为 accumulated 列表在循环中只追加不删除，所以下一轮天然包含所有历史能力。超集关系由数据结构保证，而不是靠人工核对 20 个 frozenset。
        Java 类比：等价于在循环里对 Set 反复 addAll 并每轮快照一次，tuple(_PROFILES) 再冻结外层序列。
      Q4: runtime_status 段落为什么固定排在 Prompt 最后？
        A: 因为它承载"频繁变化但必须与稳定段落分开"的运行态信息（MCP 连接、异步工作状态）。放在最后是为了让状态变化不移动、不重排前面的 identity、tools、workspace、skills、memory 段落，这样缓存键的稳定段落不会因为 MCP 连接状态变化而失效。
        实现细节：status 只在存在时才写入缓存键，保证 P01-P19 的缓存键与迁移前完全一致。
      Q5: 为什么 status_provider 是 lambda 而不是构建期的 JSON 快照？
        A: 因为 lambda 捕获运行时对象的引用，每轮渲染读到的都是当前状态，而不是构建期的过期快照。DynamicPromptProvider.render() 每次都调用 status_provider()，所以 MCP 连接和后台 pending work 的变化才能在下一轮 Prompt 中体现。
        Java 类比：类似注入一个 Supplier<Map<String, Object>>，而不是注入一份 Map 常量。
      Q6: 资源关闭为什么有"成功路径"和"失败路径"两条？
        A: 因为 build_agent 本身可能失败。成功时 AgentRunner 持有统一 resources，逆序关闭 MCP、Teammate、Cron 和 Supervisor；组装本身失败时没有 Runner，才按创建顺序用 closables 兜底。这样任何一条路径都不会遗留 stdio 子进程或后台线程。
        关键实现：failures 列表收集执行与清理阶段的全部异常，避免前一个错误掩盖后一个；多个异常用 ExceptionGroup 聚合。
      Q7: 为什么 Worktree、WorkStealing、TaskStore 必须共享同一实例？
        A: 因为它们操作同一份任务状态。TaskStore 持有 SQLite 连接，Worktree 创建 Git 工作树并声明任务，WorkStealing 认领并执行任务。如果不共享，Lead 看到的任务图和 Teammate 看到的任务图会分叉。build_agent 用对象身份校验：`if task_store is not worktree_runtime.store: raise ValueError(...)`
        Java 类比：类似 Spring 保证 @Transactional 方法拿到同一个 EntityManager。
      Q8: 为什么 MCP 连接、Cron、Teammate 必须共享同一个 EventInbox？
        A: 因为 typed event 必须进入统一收件箱，才能在请求前批量消费。如果 Cron 完成事件进一个 inbox、Teammate 消息进另一个 inbox，AgentRunner 就要轮询多个来源，顺序也无法保证。create_live_runtime 在开头创建单一 inbox，后续运行时全部复用这个引用。
        验证方式：build_agent 校验 `cron_runtime.event_inbox is not background_supervisor.inbox` 时抛出 ValueError。
```

## Java 开发者 3 步速通指南

### 第 1 步：从验收测试看整合目标（15 分钟）
```bash
# 阅读完整 Harness 的核心验收测试
cat tests/test_ch20_full_harness.py

# 关注点：
# - 一次回复同时做哪几件事（连接 MCP + 越界写入）
# - 四条不变量如何同时验证（动态工具、配对、权限、关闭）
# - 共享关系如何建立（_Harness 夹具）
```

**Java 对照**：这就像先读 `@SpringBootTest` 集成测试，理解"把所有能力装配到同一个 ApplicationContext"的验收标准。

### 第 2 步：读组合根装配逻辑（20 分钟）
```bash
# 阅读唯一组合根
cat bootstrap.py

# 阅读顺序：
# 1. _full_harness_runtime_status（运行态状态汇总）
# 2. build_agent 开头的 profile 身份校验
# 3. 能力与依赖的 if-raise 校验块
# 4. 共享关系的对象身份校验（is 判断）
```

**关键理解**：
- `profile_for_chapter(profile.chapter) is not profile` = 只接受固定单例
- `"capability" in profile.capabilities` = 能力白名单判断
- `task_store is not worktree_runtime.store` = 对象身份而非类型校验
- lambda 捕获运行时引用 = 每轮重新读取状态

### 第 3 步：理解真实运行入口（10 分钟）
```bash
# 阅读命令行入口与资源管理
cat cli.py

# 快速浏览这两个文件，了解能力档案与动态 Prompt
cat core/profiles.py
cat features/prompting.py
```

**不要深入细节**：cli.py 负责装配与关闭，profiles.py 负责能力推导，prompting.py 负责状态渲染。先知道有什么就行。

---

## 核心类比速查表

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `ChapterProfile` | 不可变 `record` | 章节号 + 能力白名单 |
| `frozenset[Capability]` | `Set.copyOf()` | 只读能力集合 |
| `bootstrap.build_agent()` | `@Configuration` | 唯一组合根 |
| `cli.LiveRuntime` | `ApplicationContext` | 持有单例与关闭顺序 |
| `profile_for_chapter()` | 返回 enum 常量 | 固定单例对象 |
| `is` 判断 | 对象身份校验 | 拒绝临时构造的冒充对象 |
| `Callable[[], T]` | `Supplier<T>` | 零参数回调 |
| `status_provider()` | lambda 捕获引用 | 每轮重新读取状态 |
| `try/finally + close()` | try-with-resources | 保证资源释放 |
| `ExceptionGroup` | `AggregateError` | 聚合多个异常 |

---

## 调试断点速查（VSCode/PyCharm 适用）

如果你想单步调试理解完整 Harness 的装配与执行，按优先级打以下断点：

### 【必打断点】理解装配流程（5 个）
**[1]** `bootstrap.py:108` → `build_agent()` 函数开始  
观察：`profile.chapter`、`profile.capabilities`  
目的：确认传入的是哪个章节档案

**[2]** `bootstrap.py:112` → profile 对象身份校验  
观察：`profile_for_chapter(profile.chapter) is not profile` 的结果  
目的：理解为什么只接受固定单例

**[3]** `bootstrap.py:364` → 运行态状态提供者创建  
观察：lambda 捕获的 `background_supervisor`、`cron_runtime`、`mcp_runtime`  
目的：确认状态提供者绑定了哪些运行时引用

**[4]** `cli.py:196` → `build_agent()` 调用成功  
观察：`runtime.build_kwargs` 的内容  
目的：检查传给组合根的所有依赖是否完整

**[5]** `cli.py:206` → `runner.close()` 开始  
观察：`runner._resources` 的顺序  
目的：确认资源逆序关闭的顺序

### 【可选断点】深入理解（3 个）
**[6]** `core/profiles.py:98` → `_build_profiles()` 累计推导循环  
观察：每轮 `accumulated` 列表的增长  
目的：理解增量表如何累加成完整档案

**[7]** `features/prompting.py:175` → `DynamicPromptProvider.render()`  
观察：`self._status_provider()` 的返回值  
目的：确认每轮读取的状态是否变化

**[8]** `core/loop.py:298` → `AgentRunner.close()` 逆序遍历  
观察：`reversed(self._resources)` 的顺序  
目的：理解为什么 MCP 最先关闭、Supervisor 最后关闭

一次完整运行的调用链：  
`[4] → [1] → [2] → [3] → [7]（每轮）→ [5] → [8]`

---

## 学完本章你会理解

✅ **完整 Harness 的本质**：整合验证而非新框架  
✅ **能力累计推导**：增量表保证严格超集关系  
✅ **对象身份校验**：拒绝能力越级注入  
✅ **状态提供者模式**：lambda 捕获引用而非快照  
✅ **共享关系的对象身份**：同一个 inbox、store、runtime  
✅ **资源关闭的两条路径**：成功与失败都保证回收  

---

## 常见问题 FAQ

### Q1: P20 新增了哪些代码？
**A**: 只新增两处连接点：`core/profiles.py` 的 `full_harness` 标记，以及 `features/prompting.py` 的可选 `runtime_status` 尾部段落（由 `bootstrap.py` 只为 P20 安装）。所有其他代码都是 P01-P19 已有的。

### Q2: runtime_status 和 typed event 的区别是什么？
**A**: typed event 是主动推送的异步事件（Cron 完成、Teammate 消息），在请求前批量消费并作为 user 消息进入历史；runtime_status 是每轮重新读取的同步状态（MCP 已连接哪些 alias、是否仍有异步工作），只给模型决策提示，不进入历史，也不替代事件通知。

### Q3: 为什么增量表比逐章手写能力集合好？
**A**: 因为"第 N 章是第 N-1 章的严格超集"由数据结构保证。增量表只记录本章新增的能力，_build_profiles() 自动累加。如果手写 20 个 frozenset，很容易漏掉某一章的某个能力，导致超集关系被破坏。

### Q4: 为什么 closables 是逆创建顺序？
**A**: 因为后创建的对象可能依赖先创建的对象。例如 Teammate 依赖 Supervisor，Cron 依赖 Supervisor，MCP 不依赖其他运行时。逆序关闭保证 MCP 最先关闭（释放子进程），Supervisor 最后关闭（确保所有后台任务已结束）。

### Q5: 为什么 MCP 连接状态放在 runtime_status 而不是单独工具？
**A**: 因为 MCP 连接状态是"模型需要知道当前有哪些远程工具可用"的上下文，而不是"模型主动查询"的行为。放在 Prompt 末尾让模型无成本地看到，而不需要每次都调用 `query_mcp_status` 工具。

### Q6: 为什么 build_agent 拒绝能力越级注入？
**A**: 因为低章节没有对应的测试覆盖。如果允许把 P19 的 mcp_runtime 传给 P03，就绕过了 P04-P18 的渐进校验，可能暴露未经测试的组合。对象身份校验保证调用方只能传 profile_for_chapter() 返回的固定单例。

---

## 下一步学习建议

1. **动手运行完整测试**：`pytest tests/test_ch20_full_harness.py -v`
2. **修改增量表**：在 `_PROFILE_DELTAS` 的第 20 行删掉 `"full_harness"`，看 `profile_for_chapter(20)` 是否还包含它
3. **观察状态变化**：在测试里打断点，看两次模型请求的 `runtime_status` 是否不同
4. **阅读 cli.py 错误处理**：看 `ExceptionGroup` 如何聚合执行与清理的多个异常

---

## 文件依赖关系图

```
cli.main()
    ├── create_live_runtime() → 创建全部运行时与共享关系
    │   ├── EventInbox (单例)
    │   ├── JobSupervisor (共享 inbox)
    │   ├── CronRuntime (共享 supervisor & inbox)
    │   ├── TeammateRuntime (共享 mailbox & inbox)
    │   ├── ProtocolRuntime (共享 teammate)
    │   ├── SqliteTaskStore (单例)
    │   ├── WorktreeRuntime (共享 task_store)
    │   ├── WorkStealingRuntime (共享 worktree)
    │   └── McpRuntime (独立)
    └── execute() → 运行并保证资源释放
        ├── build_agent(P20, ...) → 组合根装配
        │   ├── 校验 profile 对象身份
        │   ├── 校验能力与依赖匹配
        │   ├── 校验共享关系对象身份
        │   ├── 创建 DynamicPromptProvider
        │   └── 返回 AgentRunner
        ├── runner.run() → 主循环
        └── runner.close() → 逆序关闭资源
            ├── MCP (最先)
            ├── Teammate
            ├── Cron
            └── Supervisor (最后)
```

---

## 总结：完整 Harness 的三个核心职责

1. **整合验证**：把 P01-P19 的全部能力接到同一个 AgentRunner，用跨功能场景证明边界同时成立
2. **共享关系**：用对象身份校验保证跨能力对象（inbox、task_store、runtime）共享同一实例
3. **资源管理**：成功与失败路径都保证逆序关闭，不遗留子进程或后台线程

**记住**：P20 不是新框架，是验收标记。它证明前十九章的能力可以在同一个 Loop、同一个 Registry、同一个 PermissionPolicy 上协同工作。
