# 第 12 章：持久化 JSON Task DAG（Python 版）

本章在第 11 章恢复层之上增加 workspace 级任务图。它不是第五章的 `todo_write`，也不是第六章的一次性 `task` 子 Agent 工具，而是可以跨进程恢复、按依赖阻塞、由可信 owner 认领和完成的项目任务。

## Java 开发者阅读顺序

| Python 文件 | Java/Spring 类比 | 先看什么 |
| --- | --- | --- |
| `tests/test_tasks.py` | Repository/Service 单测 | 先看状态迁移、DAG 校验和并发认领 |
| `agent_ch12/features/tasks.py` | `Task` record、领域异常、Command Handler | 字段不变量和五个工具的严格输入 |
| `agent_ch12/adapters/task_json.py` | JSON Repository + 文件锁 | 整图重建、锁内读改写、原子替换 |
| `agent_ch12/core/profiles.py` | Spring profile/feature flag | P12 在 P11 上增加什么能力 |
| `agent_ch12/bootstrap.py` | `@Configuration` | TaskStore 如何注入主 Agent 和子 Agent |
| `tests/test_ch12_integration.py` | `@SpringBootTest` | P12 工具列表和能力边界 |

## Java 对照

- `Task` 是不可变 `dataclass`，类似 Java `record Task(...)`。
- `TaskStore` 是 `Protocol`，类似 Java `interface TaskRepository`。
- `JsonTaskStore` 是基础设施 Adapter，不让核心工具依赖 JSON 细节。
- `TaskError.code` 类似业务异常里的稳定错误码。
- `build_agent()` 类似 Spring 组合根，负责构造和依赖注入。

## 运行环境

继续共享 `python/.venv` 和 `python/.env`，不要在本章目录新建虚拟环境或密钥：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch12_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
```

真实运行需要共享 `python/.env` 中的四个配置：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_FALLBACK_MODEL`。

```powershell
& ..\.venv\Scripts\python.exe -m agent_ch12.cli --prompt "建立 schema、endpoints、tests 和 docs 的任务依赖"
```

任务文件会保存到当前 workspace：

```text
当前目录/
  .agent_tutorial/
    .tasks.lock
    .tasks/
      <canonical-uuid>.json
```

## TODO、子 Agent 和 Task 的区别

| 能力 | 生命周期 | 存储 | owner | 依赖 |
| --- | --- | --- | --- | --- |
| `todo_write` | 当前会话 | 内存 | 当前 Agent session | 无 |
| `task` | 一次性委派 | 子 Agent 内部轨迹 | 运行中的子 Agent | 无 |
| JSON Task DAG | workspace/跨进程 | `.agent_tutorial/.tasks/*.json` | 认领者 identity | `blocked_by` |

三者不会自动同步。TODO 负责提醒当前 Agent 怎么做，Task DAG 负责项目中哪些任务可以开始。

## 三态状态机

```text
pending --claim--> in_progress --complete--> completed
```

没有单独的 `blocked` 状态。一个 pending 任务是否 blocked，是由 `blocked_by` 中是否存在未完成任务计算出来的。这样完成上游时不需要批量改写下游 JSON。

`pending` 必须没有 owner；`in_progress` 和 `completed` 必须有 owner。第 12 章没有 `unclaim`、`delete`、自动回退或 release。

## 五个工具

| 工具 | 作用 | 副作用 |
| --- | --- | --- |
| `create_task` | 创建带依赖的新任务 | 写入一个 JSON |
| `get_task` | 读取单个任务 | 只读 |
| `list_tasks` | 返回完整稳定排序的任务图 | 只读 |
| `claim_task` | 认领 ready pending 任务 | pending -> in_progress |
| `complete_task` | owner 完成任务 | in_progress -> completed |

所有工具参数都拒绝额外字段。特别是 `claim_task` 和 `complete_task` 不接受模型传入的 owner；owner 只能来自 `ToolContext.identity`，防止模型伪造其他身份。

## 学习重点

1. 先读 `tests/test_tasks.py`，找到一个行为测试。
2. 再读 `features/tasks.py`，理解 `Task` 字段和异常码。
3. 再读 `adapters/task_json.py`，观察锁内如何重新加载完整 DAG。
4. 最后读 `bootstrap.py`，确认 P12 和子 Agent 共享同一个 TaskStore。

## 验证命令

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch12
& ..\.venv\Scripts\python.exe -m ruff check agent_ch12 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch12 --no-incremental
```

离线测试不需要密钥或网络。真实模型调用只验证 Agent Loop，Task DAG 的持久化、锁、原子写和错误分支都由离线测试覆盖。
