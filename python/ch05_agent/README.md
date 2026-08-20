# 第 5 章：会话级 TODO 与长任务提醒

本章是 TypeScript 第 5 章的 Python 完整迁移版。它保留前四章的文件工具、权限策略和四类 Hook，只增加会话级 `todo_write`、完整计划快照和连续三轮未更新计划后的临时提醒。

```text
agent_ch05/
  core/hooks.py         # HookContext、HookResult、HookRegistry
  core/loop.py          # 在固定位置触发 Hook，并保持 tool_call_id 配对
  core/permissions.py   # 系统 deny 仍高于 Hook allow
  bootstrap.py          # 只有 P04 允许注入 HookRegistry
  features/todos.py     # TodoTracker 和 todo_write
  cli.py                # 中文审批、审计和生命周期日志
tests/
  test_hooks.py         # 先读：Hook 自身契约
  test_ch05_integration.py # 后读：TODO 如何接入完整 Agent Loop
```

共享环境继续使用 `python/.venv` 和 `python/.env`：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch05_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch05.cli --prompt "先建立完整 TODO，再读取 README.md 并总结运行和验证步骤"
```

建议考古顺序：`tests/test_todos.py` -> `features/todos.py` -> `tests/test_ch05_integration.py` -> `core/loop.py` -> `bootstrap.py`。Java 对照：`TodoTracker` 类似会话级领域 Service，`ToolRoundObserver` 类似扩展 interface，`AgentRunner` 是应用服务，`bootstrap.py` 是 Spring 配置类。共享环境仍然使用 `python/.venv` 和 `python/.env`，本章不会重新创建它们。
