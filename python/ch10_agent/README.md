# 第 10 章：动态模块化 System Prompt

本章在第九章长期记忆之上，把不断增长的一整段 system prompt 拆成固定顺序的 section。
每次模型请求前，Provider 都从真实运行态读取工具、workspace、Skill 目录和已选记忆。

## Java 开发者阅读顺序

| Python 文件 | Java/Spring 类比 | 重点 |
| --- | --- | --- |
| `tests/test_prompting.py` | Renderer/Service 单元测试 | 先看输入状态如何变成固定 Prompt |
| `features/prompting.py` | View Renderer + `Supplier<String>` | section、严格 JSON、实例缓存 |
| `core/loop.py` 的 `SystemPromptProvider` | Java interface | Agent Loop 只依赖零参数 `render()` |
| `bootstrap.py` | `@Configuration` | P10 如何绑定工具、Skill 和 Memory |
| `tests/test_ch10_integration.py` | `@SpringBootTest` | 工具多轮中记忆只注入一次 |

## 固定顺序

```text
identity -> tools -> workspace -> skills -> memory
```

前三个 section 始终存在；没有 Skill 或没有选中记忆时，对应 section 整段省略。
工具列表为空时明确显示 `(none)`。

## 运行

继续复用共享的 `python/.venv` 和 `python/.env`：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch10_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch10.cli --prompt "列出当前 Agent 的可用工具"
```

完整检查：

```powershell
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch10
& ..\.venv\Scripts\python.exe -m ruff check agent_ch10 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch10 --no-incremental
```

## Java 对照

`DynamicPromptRenderer` 不负责发现工具或选择记忆，类似只负责展示 DTO 的模板层。
`DynamicPromptProvider` 在 Bootstrap 中绑定依赖，类似构造器注入后的 Service Adapter。
`AgentRunner` 每轮只调用 `provider.render()`，不需要知道 Prompt 内部有几个 section。

第十章关闭 `MemorySession.before_model()` 的独立消息注入，但仍保留选择、提取和整理生命周期。
已选记忆改由动态 Prompt 的 `memory` section 输出，因此正文只出现一次。
