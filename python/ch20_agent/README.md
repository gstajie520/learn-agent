# 第 20 章：完整 Agent Harness（Python 版）

这是第 20 章的 Python 累计快照，代码位于 `agent_ch20/`，测试位于 `tests/`。

本章不发明新框架，也不复制第二套 Loop。它只做一件事：**把前十九章已经实现的能力接到同一个组合根，并用跨功能场景证明这些边界同时成立**。

`full_harness` 是一个验收标记能力，不对应任何新的业务模块。它表示 P1-P19 的全部 Capability 已经在同一 `build_agent()` 中连接并通过交叉验证。

## 本章唯一的主线能力

一个可运行的 Agent 不是"模型 + 几十个工具"，而是一组**可验证的所有权和状态边界**：

* 模型只提议下一步动作，Harness 拥有真正的决策权；
* Prompt 负责指导，`PermissionPolicy` 负责授权；
* Hook 只能在硬边界允许的范围内扩展，不能放宽系统拒绝；
* 每个 tool call 必须恰好配一个同 ID 的 tool result；
* 每条状态线都有权威存储，重建时不猜测；
* 每个长期资源都有 owner，关闭时能回收。

P20 在代码上只新增两处连接点：`core/profiles.py` 的 `full_harness` 标记，以及 `features/prompting.py` 的可选 `runtime_status` 尾部段落（由 `bootstrap.py` 只为 P20 安装）。

## Python 项目结构

```text
python/ch20_agent/
├─ agent_ch20/
│  ├─ core/            # 领域契约：loop、messages、tools、permissions、hooks、profiles
│  ├─ adapters/        # 外部边界：OpenAI、PowerShell、文件系统、Git、SQLite、JSON、MCP stdio
│  ├─ features/        # 各章能力：todo、skills、memory、compaction、recovery、tasks、
│  │                   # background、cron、teammates、protocol、work_stealing、worktrees、mcp_tools
│  ├─ mcp_servers/     # 可运行的演示 MCP Server
│  ├─ bootstrap.py     # 唯一组合根（Spring @Configuration 类比）
│  ├─ config.py        # 四项 OpenAI 配置读取
│  └─ cli.py           # 真实运行入口与资源生命周期
└─ tests/              # 42 个离线测试文件，共 215 个用例
```

## Java / Spring 概念对照

| 本章 Python 位置 | Java / Spring 类比 | 职责 |
| --- | --- | --- |
| `bootstrap.build_agent()` | `@Configuration` + 构造器注入 | 唯一组合根，校验跨运行时的共享关系 |
| `core/profiles.py` | 只读配置 record + enum 常量 | 每章能力白名单，按增量累加推导 |
| `core/loop.AgentRunner` | 应用层 Service | 唯一 Agent 循环，编排全部接口 |
| `core/tools.ToolRegistry` | 只读 Bean 容器 + `snapshot()` | 一次回复只使用一个密封快照 |
| `core/permissions.PermissionPolicy` | Spring Security 决策链 | handler 之前的硬权限判断 |
| `core/hooks.HookRegistry` | AOP 切面 | 生命周期扩展，不能放宽硬拒绝 |
| `adapters/*` | `@Repository` / 外部 Client | Protocol 的基础设施实现 |
| `features/*` | 领域 Service + Repository 接口 | 各章能力的状态机 |
| `cli.py` | `main()` + 应用启动装配 | 参数解析、真实资源创建与统一关闭 |

## Python 语法对照（面向 Java 后端）

| Python 写法 | Java 对照 | 本章出现位置 |
| --- | --- | --- |
| `typing.Protocol` | `interface`（结构化，无需显式 implements） | `McpSchemaValidator`、`ProtocolMailboxStore` |
| `@runtime_checkable` | 允许对 interface 做 `instanceof` | `ProtocolMailboxStore` 类型收窄 |
| `@dataclass(frozen=True, slots=True)` | 不可变 `record` | `ChapterProfile`、`ToolResult` |
| `frozenset[Capability]` | `Set.copyOf(...)` 只读集合 | `ChapterProfile.capabilities` |
| `Callable[[], Mapping[str, object]]` | `Supplier<Map<String, Object>>` | `DynamicPromptStatusProvider` |
| `T \| None` | `Optional<T>` / 可空引用 | 全部可选依赖 |
| `capability in profile.capabilities` | `set.contains(...)` | 组合根的能力判断 |
| `isinstance(x, bool)` 单独排除 | Java 中 `boolean` 与 `int` 无继承关系 | `profile_for_chapter` 参数校验 |
| `try/finally` + `close()` | try-with-resources | `cli.py` 统一资源回收 |

## 建议考古顺序（从一个聚焦测试出发）

1. `tests/test_ch20_full_harness.py::test_full_harness_combines_dynamic_context_mcp_policy_and_pairing`
   —— 一个测试同时压测四条边界，是理解本章最快的入口。
2. `core/profiles.py`：看 `_PROFILE_DELTAS` 如何用增量表保证"第 N 章是第 N-1 章的严格超集"。
3. `bootstrap.py`：从 `_validate_build_dependencies` 读到 `_full_harness_runtime_status`，
   确认组合根用对象身份而不是类型来校验共享关系。
4. `features/prompting.py`：看 `runtime_status` 如何作为尾部段落参与缓存键。
5. `core/loop.py`：确认只有一个 Loop、一个 Registry 快照、严格成对的消息。
6. `cli.py`：看真实运行时的创建顺序与逆序关闭。

## 适配器、核心服务、注册表与组合根的区别

* **适配器**（`adapters/`）：把外部世界（进程、文件、HTTP、SQLite、stdio）翻译成 core 的 Protocol。可替换，不含业务规则。
* **核心服务**（`features/`、`core/`）：拥有业务规则和状态机，只依赖 Protocol，不知道具体适配器。
* **注册表**（`ToolRegistry`）：模型可见能力的唯一来源。`snapshot()` 密封一次回复的工具集合。
* **组合根**（`bootstrap.py`）：唯一知道"谁和谁必须共享同一实例"的地方，并在启动阶段验证。

## 运行时状态段落

P20 的 system prompt 末尾追加一段由组合根每轮重新读取的状态：

```text
## runtime_status
{"mcp_connections":["fake"],"pending_work":false}
```

它固定排在全部稳定段落之后，因此状态变化不会移动或重排前面的内容。它不替代 `EventInbox`：typed event 仍在请求前消费，状态只回答"当前是否仍有异步工作、MCP 已连接哪些 alias"这两个模型决策问题。这里只读取同步 getter，不等待后台任务、不查询远端，也**不把运行态 JSON 当作授权依据**。

## 安装与验证

章节复用 `python/.venv` 和 `python/.env`：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch20_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch20
& ..\.venv\Scripts\python.exe -m ruff check agent_ch20 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch20 --no-incremental
```

只运行本章新增的整合验收：

```powershell
& ..\.venv\Scripts\python.exe -m pytest tests/test_ch20_full_harness.py
```

## 真实运行的前提与安全边界

第 18 章起必须**从目标 Git 仓库根目录**运行：

```powershell
Set-Location 'E:\workspace\demo-repo'
& E:\cj\study\learn-agent\python\.venv\Scripts\python.exe -m agent_ch20.cli --prompt "分析仓库并先给出计划"
```

* `.env` 需要四项配置：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_FALLBACK_MODEL`。
* 缺少配置时，入口在创建模型和任何 `.agent_tutorial` 状态**之前**退出并返回 `2`。
* cwd 不是 Git 仓库根时，同样在创建持久状态前失败并返回 `1`。
* 文件写入需要终端审批；**非 TTY 环境默认拒绝**，避免无人值守时自动放行。
* 工作区外写入由 `PermissionPolicy` 硬拒绝，与 Prompt 内容无关。
* MCP 远程工具的 effect 只由本地 `McpToolPolicy` 决定，远端 description 不能提权。

离线测试全部注入 fake 模型、fake 时钟和 fake MCP 连接，不访问网络也不需要凭据。日志、工具错误和异常说明使用中文；`mcp__...`、`permission_denied`、`mcp_timeout`、`finish_reason` 等机器可读字段保留英文。
