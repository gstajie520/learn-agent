# 第 18 章：Git Worktree 隔离与任务绑定学习导航图

## 学习脑图

```mermaid
mindmap
  root((第 18 章<br/>Git Worktree 隔离))
    学习路线（推荐顺序）
      第一步：读测试了解目标
        tests/test_ch18_worktrees.py
        看 Worktree 创建、claim 路由和删除流程
        理解失效 token 不能回退到主目录
      第二步：读领域模型
        features/worktrees.py
        WorktreeBinding 状态快照
        WorktreeRuntime 核心服务
        理解状态机转换规则
      第三步：理解持久化层
        adapters/task_sqlite.py
        _transition_worktree 方法
        状态迁移 + 审计事件原子性
      第四步：理解上下文解析
        core/loop.py
        _resolve_tool_context 方法
        每次工具调用前重新解析 cwd
      第五步：理解删除安全
        features/worktrees.py
        remove_worktree 方法
        先证明安全再删除的多重检查
    核心文件清单
      features/worktrees.py（领域模型）
        WorktreeBinding
          task_id（任务UUID）
          name/branch/relative_path（固定命名规则）
          integration_ref（合入目标）
          baseline_commit/branch_tip（Git对象ID）
          status（五态状态机）
          review_reason（人工审查原因）
        WorktreeRuntime
          validate_repository（仓库前置检查）
          create_worktree（reserve → active）
          keep_worktree（手动保留）
          remove_worktree（证明安全后删除）
          resolve（claim token → 可信 cwd）
        异常定义
          WorktreeRepositoryError（非法Git仓库）
          WorktreeStateError（状态不允许操作）
          WorktreeGitError（Git结果不满足约束）
          WorktreeContextError（不可信上下文）
      adapters/task_sqlite.py（持久化）
        _transition_worktree（状态迁移）
        _append_worktree_audit（审计事件）
        _resolve_worktree_by_task（查询绑定）
        事务原子性
          UPDATE worktree_bindings SET status
          INSERT INTO audit_events
          SQLite事务隔离
      adapters/git.py（Git适配器）
        SubprocessGitRunner
        GitCommandResult（退出码+双流）
        GitExecutionError（Git失败）
        只封装subprocess不解释业务
      core/loop.py（循环增强）
        _resolve_tool_context
          检查claim_token有效性
          调用WorktreeRuntime.resolve
          返回可信ToolContext
        每次工具执行前重新解析
    Java 对照关系
      数据结构对照
        WorktreeBinding = 不可变 record
        status 五态 = 状态机枚举
        frozenset = Set.of()
        dataclass frozen=True = 不可变性
      设计模式对照
        WorktreeRuntime = Domain Service
        WorktreeStore = Repository interface
        _transition_worktree = 事务脚本
        resolve = 请求拦截器
      Git 操作对照
        git worktree add = ProcessBuilder封装
        退出码检查 = result.returncode != 0
        stderr捕获 = ProcessBuilder.redirectError
      状态机对照
        reserved → active = 两阶段提交
        active → kept/needs_review/removed = 终态选择
        _ACTION_STATUS = Map.of("reserve", "reserved", ...)
      安全边界对照
        claim_token校验 = JWT验证
        路径安全检查 = Path.normalize + contains
        Git对象ID校验 = 正则表达式 + 40/64位十六进制
        fail-safe删除 = 多重断言 + 回滚到needs_review
    设计模式识别
      两阶段提交
        reserve预留状态
        create成功后迁移active
        失败时可以回滚或清理
      状态机模式
        五态：reserved/active/kept/needs_review/removed
        合法转换：reserved→active, active→kept/needs_review/removed
        不可逆终态：removed
      Repository + UnitOfWork
        _transition_worktree原子写入
        状态变更+审计事件同一事务
        SQLite自动提交保证一致性
      拦截器模式
        _resolve_tool_context
        工具执行前统一解析cwd
        类似Servlet Filter链
      Fail-Safe删除
        先证明：任务完成+路径受控+Git干净+提交已合并
        任何失败：转needs_review而非删除
        保护用户数据优先于清理成功
    关键概念理解
      为什么需要Worktree隔离
        文件锁只能排队，不能并发
        多个Agent同时改同一文件会覆盖
        Worktree给每个任务独立目录和分支
      claim token如何路由到Worktree
        claim_task返回token
        token绑定task_id
        task_id关联WorktreeBinding
        resolve方法查询并返回Worktree路径
      为什么路径必须固定规则
        防止模型传入任意路径
        branch固定wt/{name}
        相对路径固定.agent_tutorial/worktrees/{name}
        路径安全由领域层保证
      删除前的多重检查
        1. 任务必须completed
        2. 路径仍在.agent_tutorial/worktrees/下
        3. git status --porcelain为空
        4. 分支提交已在integration_ref
        任何失败→needs_review
      状态机转换规则
        reserve: 预留名称和路径
        create: Git执行成功后激活
        keep: 手动保留不删除
        needs_review: 证明失败转人工审查
        removed: 删除完成的终态
    面试题速查
      Q1：为什么WorktreeBinding是不可变的
        A：状态变更由Repository生成新快照，确保审计事件和状态迁移原子性
        Java类比：record确保不被意外修改，每次变更都是显式的
      Q2：为什么删除失败要转needs_review而非直接报错
        A：Worktree可能包含重要改动，直接失败会丢失现场；转needs_review保留证据供人工排查
        设计原则：保护用户数据优先于自动化清理
      Q3：resolve方法为什么每次工具调用都要执行
        A：claim token可能在运行中过期或被撤销，每次重新验证确保上下文可信
        类比JWT验证：不能假设token永久有效
      Q4：为什么branch和path不能让模型传入
        A：模型可能被注入恶意prompt，固定规则防止路径遍历攻击和分支污染
        安全边界：业务规则由代码强制，不信任外部输入
      Q5：_transition_worktree如何保证原子性
        A：UPDATE status和INSERT audit在同一SQLite事务，要么都成功要么都回滚
        Java类比：@Transactional确保状态和事件一致性
      Q6：Git stderr为什么只留在适配器边界
        A：stderr是不稳定的诊断信息，给模型和用户的错误应该是稳定的中文说明
        分层原则：领域层抛稳定异常，适配器层处理技术细节
      Q7：为什么要校验Git对象ID是40或64位十六进制
        A：防止命令注入和路径遍历，Git对象ID格式固定
        安全实践：严格校验外部输入格式
      Q8：WorktreeRuntime为什么同时实现TaskClaimService和ToolContextProvider
        A：任务认领和上下文解析是同一个领域边界，共享状态查询逻辑
        接口隔离：不同调用方看到不同接口，但实现可以统一
    可选阅读（周边组件）
      adapters/git.py
        SubprocessGitRunner实现
        命令构造和结果解析
      adapters/task_sqlite.py
        完整SQL schema
        索引和外键设计
      core/loop.py
        完整Hook生命周期
        权限策略集成
      tests/
        单元测试
        集成测试
        Fake对象实现
```

## Java 开发者 3 步速通指南

### 第 1 步：从测试开始理解目标（10 分钟）
```bash
# 阅读测试文件，看 Worktree 的三个核心场景
cat tests/test_ch18_worktrees.py

# 关注点：
# - test_create_claim_and_route_to_worktree：完整流程
# - test_failed_claim_never_falls_back：安全边界
# - test_remove_requires_completed_task：删除前置条件
```

**Java 对照**：这就像先读 `WorktreeServiceTest.java`，理解业务需求再看实现。

### 第 2 步：读领域模型和核心服务（20 分钟）
```bash
# 阅读带详细注释的核心文件
cat features/worktrees.py

# 阅读顺序：
# 1. WorktreeBinding（数据模型和状态机）
# 2. WorktreeRuntime.__init__（依赖注入）
# 3. create_worktree（两阶段提交）
# 4. resolve（claim token → 可信 cwd）
# 5. remove_worktree（多重安全检查）
```

**关键理解**：
- `WorktreeBinding` = Java 的不可变 `record`
- `WorktreeStore` = Repository `interface`
- `status` 五态 = 状态机枚举
- `resolve` = 请求拦截器，每次工具调用前执行

### 第 3 步：理解持久化和循环集成（15 分钟）
```bash
# 快速浏览持久化层
cat adapters/task_sqlite.py | grep -A 20 "_transition_worktree"

# 快速浏览循环集成
cat core/loop.py | grep -A 30 "_resolve_tool_context"
```

**不要深入细节**：重点理解事务原子性和上下文解析时机。

---

## 核心类比速查表

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `WorktreeBinding` | `record WorktreeBinding(...)` | 不可变状态快照 |
| `WorktreeRuntime` | `@Service class WorktreeService` | 领域服务 |
| `WorktreeStore` | `interface WorktreeRepository` | 持久化接口 |
| `_transition_worktree` | `@Transactional void transition()` | 事务脚本 |
| `resolve` | `Filter.doFilter()` | 请求拦截器 |
| `frozenset` | `Set.of()` | 不可变集合 |
| `status` 五态 | `enum Status { RESERVED, ... }` | 状态机 |
| `GitCommandResult` | `record ProcessResult(int, String, String)` | 进程结果 |

---

## 学完本章你会理解

✅ **Worktree 隔离原理**：每个任务独立目录和分支，避免并发覆盖  
✅ **两阶段提交**：先 reserve 预留，再 create 激活  
✅ **状态机设计**：五态转换规则和不可逆终态  
✅ **claim token 路由**：从 token 查询 task_id，再关联 Worktree 路径  
✅ **Fail-Safe 删除**：多重证明失败时转 needs_review 而非直接删除  
✅ **上下文拦截器**：每次工具调用前重新解析可信 cwd  
✅ **事务原子性**：状态迁移和审计事件同一事务  
✅ **安全边界**：固定路径规则防止注入攻击  

---

## 常见问题 FAQ

### Q1: 为什么不直接在主目录工作，而要创建 Worktree？
**A**: 文件锁只能让写操作排队，无法让两个 Agent 同时修改同一文件并保留各自版本。Worktree 给每个任务独立目录和分支，真正实现并发隔离。

### Q2: 为什么 `branch` 和 `relative_path` 不让模型传入？
**A**: 模型可能被 prompt 注入攻击，传入 `../../etc/passwd` 或恶意分支名。固定规则（`wt/{name}` 和 `.agent_tutorial/worktrees/{name}`）由代码强制，安全边界不依赖模型行为。

### Q3: 为什么删除失败要转 `needs_review` 而不是直接报错？
**A**: Worktree 可能包含重要改动，直接失败会丢失现场。转 `needs_review` 保留目录和分支，供人工排查。**保护用户数据优先于自动化清理**。

### Q4: `resolve` 方法为什么每次工具调用都要执行？
**A**: claim token 可能在运行中过期或被撤销（任务完成、超时、手动释放）。每次重新验证确保上下文可信，类似 JWT 验证不能假设 token 永久有效。

### Q5: `_transition_worktree` 如何保证状态和审计事件一致性？
**A**: `UPDATE worktree_bindings` 和 `INSERT INTO audit_events` 在同一 SQLite 事务中，要么都成功，要么都回滚。类似 Java 的 `@Transactional` 注解。

### Q6: 为什么 Git stderr 只留在适配器层？
**A**: stderr 是不稳定的诊断信息（不同 Git 版本可能不同）。给模型和用户的错误应该是稳定的中文说明。**分层原则**：领域层抛稳定异常，适配器层处理技术细节。

### Q7: 为什么要校验 Git 对象 ID 是 40 或 64 位十六进制？
**A**: 防止命令注入。Git 对象 ID 格式固定（SHA-1 40 位，SHA-256 64 位），严格校验外部输入避免传入 `; rm -rf /` 等恶意字符串。

### Q8: `WorktreeRuntime` 为什么同时实现多个 Protocol？
**A**: 任务认领（`TaskClaimService`）和上下文解析（`ToolContextProvider`）是同一个领域边界，共享状态查询逻辑。**接口隔离原则**：不同调用方看到不同接口，但实现可以统一。

---

## 下一步学习建议

1. **动手运行测试**：`pytest tests/test_ch18_worktrees.py -v`
2. **查看 SQLite schema**：`sqlite3 .agent_tutorial/tasks.db ".schema worktree_bindings"`
3. **实验路径注入防御**：尝试传入 `../../` 看是否被拒绝
4. **阅读删除检查链**：追踪 `remove_worktree` 的每个 `if` 分支
5. **理解状态机转换**：画出五态的所有合法转换路径

---

## 文件依赖关系图

```
WorktreeRuntime (features/worktrees.py)
    ├── depends on → WorktreeStore (Protocol)
    │       └── implemented by → SqliteTaskStore (adapters/task_sqlite.py)
    ├── depends on → GitRunner (Protocol)
    │       └── implemented by → SubprocessGitRunner (adapters/git.py)
    ├── depends on → LeasedTaskStore (work_stealing.py)
    └── provides → ToolContextProvider (core/tools.py)

AgentRunner (core/loop.py)
    ├── depends on → ToolContextProvider (可选)
    │       └── provided by → WorktreeRuntime
    └── calls → _resolve_tool_context()
            └── calls → runtime.resolve(claim_token)

SqliteTaskStore (adapters/task_sqlite.py)
    ├── implements → WorktreeStore
    ├── implements → LeasedTaskStore
    └── provides → _transition_worktree (事务方法)
```

---

## 总结：Worktree 隔离的三个核心职责

1. **并发隔离**：每个任务独立目录和分支，避免文件覆盖
2. **上下文路由**：从 claim token 查询绑定，解析可信 cwd
3. **安全清理**：多重证明后删除，失败时保留现场供人工审查

**记住**：`WorktreeRuntime` 是领域服务，不是基础设施。它定义业务规则（什么时候可以删除、路径必须符合什么格式），而 `SubprocessGitRunner` 只负责执行 Git 命令。
