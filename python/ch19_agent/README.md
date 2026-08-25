# 第 19 章：MCP 动态工具池（Python 版）

这是第 19 章的 Python 累计快照，代码位于 `agent_ch19/`，测试位于 `tests/`。本章在第 18 章 Worktree 隔离之上增加 MCP：远程 Server 的工具只有通过本地 allowlist、名称隔离和 JSON Schema 校验后，才会动态出现在 Lead 的下一轮模型请求中。

## Java 对照

* `features/mcp_tools.py`：类似领域 Service，管理连接、allowlist、动态注册和撤销。
* `adapters/mcp_client.py`：类似 `ProcessBuilder` + JSON-RPC Client 的外部 Adapter。
* `core/tools.py`：`ToolRegistry.register_many/unregister_many` 类似原子批量注册和按对象身份撤销。
* `mcp_servers/demo.py`：本地一行一条 JSON-RPC 的演示 Server。
* `bootstrap.py`：只把 MCP 管理工具安装给 Lead；子 Agent 和队友不继承 MCP 工具。

`McpServerSpec` 可以按 Java 配置 record 理解，`McpConnection` 是 Port，`SubprocessMcpConnection` 是 Adapter。动态工具名形如 `mcp__demo__lookup`，远端 effect 不会覆盖本地 policy。

## 建议考古顺序

1. `tests/test_ch19_mcp.py`：看连接、发布、撤销、schema 和远程调用。
2. `features/mcp_tools.py`：追踪 `connect -> _build_definitions -> register_many`。
3. `core/tools.py`：理解为什么动态注册必须整批成功，断开必须按对象身份撤销。
4. `adapters/mcp_client.py`：看 stdio 子进程和 JSON-RPC 的最小边界。
5. `bootstrap.py`：确认 MCP 只属于 Lead，且 Runner.close 会关闭连接。

## 安装与验证

章节复用 `python/.venv` 和 `python/.env`：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch19_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch19
& ..\.venv\Scripts\python.exe -m ruff check agent_ch19 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch19 --no-incremental
```

在 Git 仓库根目录运行：

```powershell
& ..\.venv\Scripts\python.exe -m agent_ch19.cli --prompt "连接 demo MCP，然后调用 lookup 查询 needle"
```

离线测试使用 fake connection，不访问网络；日志、工具错误和异常尽量使用中文，`mcp__...`、`mcp_timeout` 等协议字段保留英文。
