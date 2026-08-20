# 第 4 章：Agent Hook 生命周期

本章是 TypeScript 第 4 章的 Python 完整迁移版。它在第三章权限策略之上增加四个固定 Hook：`UserPromptSubmit`、`PreToolUse`、`PostToolUse` 和 `Stop`。

```text
agent_ch04/
  core/hooks.py         # HookContext、HookResult、HookRegistry
  core/loop.py          # 在固定位置触发 Hook，并保持 tool_call_id 配对
  core/permissions.py   # 系统 deny 仍高于 Hook allow
  bootstrap.py          # 只有 P04 允许注入 HookRegistry
  cli.py                # 中文审批、审计和生命周期日志
tests/
  test_hooks.py         # 先读：Hook 自身契约
  test_ch04_integration.py # 后读：Hook 如何接入完整 Agent Loop
```

共享环境继续使用 `python/.venv` 和 `python/.env`：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch04_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch04.cli --prompt "读取 README.md 并概括运行方式"
```

建议考古顺序：`tests/test_hooks.py` -> `core/hooks.py` -> `tests/test_ch04_integration.py` -> `core/loop.py` -> `bootstrap.py`。Java 对照：`HookRegistry` 类似观察者注册中心，`HookContext/HookResult` 类似不可变 DTO，`AgentRunner` 是应用服务，`bootstrap.py` 是 Spring 配置类。
