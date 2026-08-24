# 第 15 章：持久队友与 Mailbox 通信（Python 版）

本章在第 14 章 Cron 事件回合之上增加持久队友：每名队友拥有独立 `AgentRunner`、独立历史和独立身份，消息通过 Mailbox 文件可靠保存，再由共享 `EventInbox` 回到 Lead。

Java 对照：`MailboxStore` 类似 Repository，`TeammateRuntime` 类似受管 WorkerService，`EventInbox` 类似 `BlockingQueue<RuntimeEvent>`。

## 本章新增边界

- `MailboxMessage`：不可变消息 record，`id` 同时是事件 ID 和幂等键。
- `FileMailboxStore`：四态目录 `ready/processing/done/quarantine`，使用临时文件、`fsync` 和原子重命名。
- `TeammateRuntime`：管理 `spawn -> running -> idle/failed -> shutdown` 生命周期。
- `spawn_teammate` / `send_message`：Lead 和队友通过工具通信，sender 只能来自 `ToolContext.identity`。
- `AgentRunner.run_events()`：普通用户回合不被 mailbox 抢占；事件回合完成模型处理后才 ack，ack 失败只补确认。

## 推荐阅读顺序

1. `agent_ch15/features/mailbox.py`：先看消息字段和状态机。
2. `agent_ch15/adapters/mailbox_json.py`：再看 Repository 的原子写入与状态迁移。
3. `agent_ch15/features/teammates.py`：最后看 WorkerService 如何复用独立 Runner。
4. `agent_ch15/core/loop.py`：重点阅读 `run_events()` 的 ack-after-processing 逻辑。

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch15_agent'
& ..\.venv\Scripts\python.exe -m pytest tests/test_mailbox.py
& ..\.venv\Scripts\python.exe -m pytest tests/test_teammates.py
& ..\.venv\Scripts\python.exe -m pytest tests/test_ch15_loop.py
```

本章在第 13 章后台任务之上增加定时触发。核心不是 `threading.Timer`，而是四个边界：

1. `schedule_cron` 工具保存五段 Cron 计划。
2. `JsonCronStore` 持久化 durable job 和 durable outbox。
3. `CronRuntime` 定期 tick，只产生事件，不直接调用模型。
4. `AgentRunner.run_events()` 在空闲时使用计划身份执行独立事件回合。

## Java 对照

| Python | Java 类比 |
| --- | --- |
| `CronJob` | Java `record CronJob(...)` |
| `CronStore` | `CronJobRepository` 接口 |
| `JsonCronStore` | 文件版 Repository + 原子快照 |
| `CronRuntime` | `ScheduledExecutorService` 外层领域服务 |
| `EventInbox` | `BlockingQueue<RuntimeEvent>` |
| `run_events()` | 消费领域事件并启动独立应用服务回合 |

## 运行

继续共享 `python/.venv` 和 `python/.env`：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch14_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch15.cli --prompt "每天上海时间 9 点检查 CI，周期执行并持久化"
```

Cron 使用 Python `zoneinfo`，Windows 环境需要 `tzdata` 依赖。项目已经声明该依赖，
不需要在每个章节重新创建虚拟环境。

## schedule_cron 输入

工具只接受五个字段，身份、ID、下一次时间都由可信运行时提供：

```json
{
  "cron": "0 9 * * *",
  "prompt": "检查 CI",
  "timezone": "Asia/Shanghai",
  "recurring": true,
  "durable": true
}
```

`cron` 严格为五段，支持列表、范围、步进和星期。DOM 与 DOW 同时受限时采用标准 OR
语义，不是 AND。真实节假日和“第一个工作日”不能靠五段 Cron 表达式解决。

## durable outbox

持久化文件：

```text
workspace/
  .agent_tutorial/
    cron/
      state.json
      leader.lock
```

`state.json` 同时保存 durable jobs 和 pending outbox。one-shot 到期时先把事件写入
outbox，再删除计划定义；Agent 成功处理并确认后才删除 outbox。进程在两步之间崩溃，
下一次启动仍能恢复事件。

session-only 计划只保存在当前进程内，不写入 durable 快照。多个调度实例通过
`leader.lock` 争夺 durable leader，只有 leader 推进 durable 计划；leader 退出后，
下一个实例可以重新投递尚未确认的事件。

## 事件回合

Cron 事件包含 `context_identity` 和 `idempotency_key`。普通用户回合正在执行时，事件
先暂存，不抢占用户请求；空闲时调用：

```python
runner.run_events()
```

事件回合使用计划创建者身份，工具仍然经过同一套 Hook、权限和 ToolRegistry。处理成功
后 ack；模型或工具失败时释放内存去重标记，durable outbox 保留，下一次 tick 可以重试。

## 阅读顺序

1. `tests/test_cron.py`：先看五段表达式、时区和 DST。
2. `features/cron.py`：理解 Job、Event、Runtime 的职责边界。
3. `adapters/cron_json.py`：观察单快照、原子写和 outbox ack。
4. `core/loop.py`：理解为什么 Cron 事件必须回到独立 Agent 回合。
5. `bootstrap.py`：确认 P14 与 P13 Supervisor/EventInbox 共享资源。

## 验证

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch15
& ..\.venv\Scripts\python.exe -m ruff check agent_ch15 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch15 --no-incremental
```
