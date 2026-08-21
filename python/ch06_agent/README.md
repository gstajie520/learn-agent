# 第 6 章：一次性子 Agent

本章在前五章累计能力上增加 `task` 工具：父 Agent 将一个自包含任务交给一次性子 Agent，子 Agent 使用全新消息历史，父 Agent 只收到最终结论。

Java 开发者阅读顺序建议：先看 `tests/test_subagents.py`，再看 `agent_ch06/features/subagents.py`，然后看 `tests/test_ch06_integration.py` 和 `agent_ch06/bootstrap.py`。`SubagentTool` 类似委派另一个应用 Service 的 facade，`AgentRunner` 是复用的 Agent Loop，`build_agent()` 类似 Spring `@Configuration`。

```text
agent_ch06/
  features/subagents.py   # task、子 Agent 工厂和 30 轮上限
  features/todos.py       # 每个父/子会话自己的 TODO 状态
  core/loop.py            # 复用模型、工具、Hook、权限循环
  bootstrap.py            # P06 组合根
tests/
  test_subagents.py
  test_ch06_integration.py
```

共享环境继续使用 `python/.venv` 和 `python/.env`，本章不会重新创建它们：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch06_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch06.cli --prompt "调用 task 独立检查本项目使用的测试框架，只返回有文件证据的结论"
```

子 Agent 不继承父消息历史，也不能调用 `task`；但父子共享 Hook、权限策略、workspace 和 identity。它是上下文隔离，不是操作系统安全沙箱。
