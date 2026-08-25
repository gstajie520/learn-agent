# 第 17 章：SQLite 任务认领与自驱队友（Python 版）

本项目是 TypeScript 第 17 章的完整 Python 学习快照，代码位于 `agent_ch17/`，测试位于 `tests/`。你是 Java 后端开发时，可以把它按下面的 Spring 分层理解：

* `adapters/task_sqlite.py`：类似 JDBC `TaskRepository`，负责 SQLite 事务、DAG、lease 和 claim token。
* `features/work_stealing.py`：类似任务认领领域 Service，负责 owner 身份绑定、工具 schema 和自动认领提示。
* `features/teammates.py`：类似受管 `WorkerService`，负责 mailbox 优先、空闲轮询、执行和关闭。
* `bootstrap.py`：类似 Spring `@Configuration`，要求 Lead、子 Agent、Teammate 共享同一个 SQLite store。

## 先看什么

建议按测试驱动的“考古法”阅读：

1. `tests/test_task_sqlite.py`：看任务依赖、原子认领、租约过期和旧 token 拒绝。
2. `agent_ch17/features/tasks.py`：理解 `Task` 三态和领域异常。
3. `agent_ch17/adapters/task_sqlite.py`：只追踪 `claim_next -> _transaction -> _claim`。
4. `tests/test_work_stealing.py`：比较 Lead 五工具和 Teammate 四工具。
5. `tests/test_ch17_runtime.py`：看 idle 队友如何自动认领并完成任务。
6. `agent_ch17/features/teammates.py`：最后阅读 `_run_worker` 的优先级顺序。

## 安装与测试

章节复用上级目录的 `python/.venv` 和 `python/.env`，不会重复创建虚拟环境或密钥文件：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch17_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch17
& ..\.venv\Scripts\python.exe -m ruff check agent_ch17 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch17 --no-incremental
```

真实运行需要共享 `.env` 中的 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL` 和 `OPENAI_FALLBACK_MODEL`：

```powershell
& ..\.venv\Scripts\python.exe -m agent_ch17.cli --prompt "建立任务图并让空闲队友自动认领"
```

离线测试使用 fake model，不访问网络，也不需要 API key。日志、工具错误和异常说明尽量使用中文；协议字段、状态值和错误码保留英文，便于程序稳定判断。

## 本章核心

SQLite 使用 `BEGIN IMMEDIATE` 把“扫描 ready 任务、检查依赖、写入 owner/token/lease”放进一个事务。`claim_token` 是一次性完成凭证；租约到期后任务回到 `pending`，旧 token 仍不能完成重新认领的任务。队友的顺序是 mailbox/protocol -> plan gate -> `claim_next` -> 运行模型 -> 模型调用 `complete_task` -> 通知 Lead。

持续队友不能调用 `create_task`，防止空闲轮询无限扩张任务图。空闲也不是 shutdown；收到新消息会唤醒等待器并复用原 Runner。
