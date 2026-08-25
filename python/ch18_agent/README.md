# 第 18 章：Git Worktree 隔离与任务绑定（Python 版）

本目录是 TypeScript 第 18 章的 Python 累计快照，代码在 `agent_ch18/`，测试在 `tests/`。
本章只在第 17 章基础上增加 Git Worktree，但它把“任务归谁”和“文件写到哪里”真正连起来。

## 用 Java 眼光看目录

* `adapters/git.py`：类似只封装 `ProcessBuilder` 的 Git Adapter，只返回退出码和双流。
* `adapters/task_sqlite.py`：类似 JDBC Repository，同时保存 Task、claim、Worktree binding 和审计事件。
* `features/worktrees.py`：类似 Spring Domain Service，管理 `reserved -> active -> kept/needs_review -> removed`。
* `core/loop.py`：类似请求拦截器链，每次工具调用前重新解析可信 `ToolContext`。
* `bootstrap.py`：类似 Spring `@Configuration`，强制 Worktree、SQLite 和自动认领共用同一实例。

`WorktreeBinding` 可以理解为 Java 的不可变 `record`。字段不是给模型随意填写的：
`branch` 固定为 `wt/{name}`，路径固定为 `.agent_tutorial/worktrees/{name}`。

## 建议考古顺序

1. 先看 `tests/test_ch18_worktrees.py`，确认创建、claim 路由和失效 token 的结果。
2. 阅读 `agent_ch18/features/worktrees.py` 的 `create_worktree`，观察为什么先 `reserve` 再执行 Git。
3. 阅读 `agent_ch18/adapters/task_sqlite.py` 的 `_transition_worktree`，对应 JDBC 的事务状态迁移。
4. 阅读 `agent_ch18/core/loop.py` 的 `_resolve_tool_context`，看每个工具为什么都要重新解析 cwd。
5. 最后看 `remove_worktree`，按“先证明能删，再真正删除”的顺序追踪每个 Git 检查。

## 安装、测试与运行

所有章节共享上级目录的 `python/.venv` 和 `python/.env`，不要重复创建：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch18_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch18
& ..\.venv\Scripts\python.exe -m ruff check agent_ch18 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch18 --no-incremental
```

真实运行必须在 Git 仓库根目录执行，并使用共享 `.env`：

```powershell
& ..\.venv\Scripts\python.exe -m agent_ch18.cli --prompt "为一个任务创建 alice Worktree，然后列出任务状态"
```

非 Git 目录会在创建 `.agent_tutorial` 状态前直接失败。工具错误和运行日志尽量使用中文，
`active`、`needs_review`、`claim_token` 等协议值保留英文，方便程序判断。

## 本章核心

文件锁只能让覆盖动作排队，不能保存两份独立改动。Worktree 给每个任务独立目录和分支；
claim token 决定当前执行者，`ToolContextProvider` 决定当前工具 cwd。一个 Agent 回复中，
先 `claim_task` 再 `write_file` 时，第二个工具会自动路由到 Worktree，而不会写进主目录。

删除前必须证明：Task 已完成、路径仍受管、Git 状态干净、分支提交已进入 integration ref。
任何证明失败都保留现场并转 `needs_review`，不会为了“清理成功”丢掉用户改动。
