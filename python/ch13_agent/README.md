# 第 13 章：后台任务与运行时事件（Python 版）

本章在第 12 章持久化 Task DAG 之上增加后台 Job。它解决的是：一个慢的
`npm install` 或 `pytest` 正在运行时，Agent 是否还能继续处理快工具，并在慢任务
结束后把完整结果送回同一个 Agent Loop。

## Java 开发者阅读顺序

| Python 文件 | Java 类比 | 先看什么 |
| --- | --- | --- |
| `tests/test_background.py` | Service/Repository 单测 | 先看状态不变量、容量、取消和事件 |
| `agent_ch13/features/background.py` | 受管线程池服务 | Job 状态机、Supervisor、Dispatcher |
| `agent_ch13/core/events.py` | `BlockingQueue<RuntimeEvent>` | typed event 如何进入主循环 |
| `agent_ch13/adapters/background_json.py` | JSON Repository | 先落盘 running，再启动 worker |
| `agent_ch13/core/loop.py` | 应用主循环 | 占位 tool result 与 runtime event 的区别 |
| `agent_ch13/bootstrap.py` | Spring `@Configuration` | P13 依赖和工具边界 |

## 共享环境

继续使用共享的 `python/.venv` 和 `python/.env`，本章目录不创建新的虚拟环境或密钥：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch13_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
```

真实运行：

```powershell
& ..\.venv\Scripts\python.exe -m agent_ch13.cli --prompt "后台运行 npm install，同时读取 README.md；拿到结果后再总结"
```

## 关键概念

### 三态参数

P13 的主 Agent shell 额外支持 `run_in_background`：

| 值 | 含义 |
| --- | --- |
| `true` | 强制提交后台 |
| `false` | 强制同步执行 |
| `null` 或省略 | 根据 `npm install`、`pytest`、`compile` 等关键词启发式判断 |

P01-P12 和一次性 subagent 的 shell 仍然只有 `{ "command": "..." }`，避免旧章节
的工具契约悄悄变化。

### 占位结果与完成事件

后台提交后，当前 tool call 立即得到唯一的占位结果：

```text
后台任务已提交: job_id=<uuid>; status=running
```

真实结果不会再次伪装成同一个 `tool_call_id` 的 tool message，而是包装成
`BackgroundJobEvent`，由 `EventInbox` 在下一次模型请求前注入普通 `user` 消息：

```json
{
  "runtime_event": {
    "kind": "background_job",
    "status": "completed",
    "job_id": "<uuid>"
  },
  "batch": {"index": 0, "total": 1}
}
```

Java 类比：占位结果是当前 Service 调用的返回值，完成事件是另一个线程通过事件总线
发回的领域事件。两者不能混成第二条 tool result，否则消息配对会失效。

### Job 状态机

```text
running -> completed
        -> failed
        -> timed_out
        -> cancelled
restart: running -> interrupted
```

`running` 一定没有 result；每个终态一定有 `ToolResult`。Supervisor 通过 Repository
的条件迁移保证只有第一个竞争写者能把 running 改成终态并发布事件，后到写者得到
`None`，因此不会重复通知模型。

### Supervisor 与 Repository

`JobSupervisor.submit()` 的顺序固定为：

```text
容量检查 -> 持久化 running -> 登记 worker -> 启动线程
```

这相当于 Java 服务先写事务记录，再提交线程池任务。进程重启时，
`JsonBackgroundJobStore.interrupt_running()` 将遗留 running Job 迁移为 interrupted，
第二次启动不会重复发布中断事件。

默认边界：并发容量 4，单 Job 超时 120 秒，关闭等待 10 秒。Python 版使用受控线程，
取消通过 `threading.Event` 协作完成；不能把它描述成可以强制杀死任意 Python 线程。

### 查询与取消

P13 主 Agent 新增两个工具：

- `query_background_job({"job_id": "..."})`：返回当前持久化快照，running 时 `result` 为 `null`。
- `cancel_background_job({"job_id": "..."})`：先发出取消信号，等待 worker 收束，再读取并返回最终状态。

这两个工具不会注册给 subagent，也不会出现在 P01-P12 profile 中。

## 建议阅读顺序

1. 先看 `tests/test_background.py`，理解每一个状态和错误分支。
2. 再看 `features/background.py`，把它当成 Java 的后台任务 Service。
3. 再看 `adapters/background_json.py`，观察 Repository 如何做原子替换。
4. 最后看 `core/loop.py` 的 `_inject_runtime_events()`，确认事件为什么是普通 user 消息。

## 验证

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch13
& ..\.venv\Scripts\python.exe -m ruff check agent_ch13 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch13 --no-incremental
```

本章离线测试不需要 API Key 或网络。真实模型 smoke test 只用于检查 OpenAI 适配器，
不是后台状态机正确性的唯一证据。
