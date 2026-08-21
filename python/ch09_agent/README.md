# 第 9 章：文件级长期记忆

本章在第八章上下文压缩之上增加跨会话记忆。Agent 会把长期有价值的偏好、反馈、
项目事实和参考入口保存到 workspace 的 `.memory/`，下次创建新的 Agent 实例时再按需选择。

## Java 开发者阅读顺序

| Python 文件 | Java/Spring 类比 | 重点 |
| --- | --- | --- |
| `tests/test_memory.py` | Repository/Service 单元测试 | 先看一条记忆如何写入、选择和整理 |
| `features/memory.py` 的 `MemoryRecord` | Java `record`/值对象 | 字段含义、slug、类型和大小校验 |
| `features/memory.py` 的 `MemoryStore` | Repository + 本地事务 | manifest、目录、正文如何一致提交 |
| `features/memory.py` 的 `MemorySession` | Spring 拦截器 | 回合前选择、请求前注入、结束后提取 |
| `core/loop.py` 的 `TurnLifecycle` | 生命周期 interface | 记忆在哪三个时间点接入主循环 |
| `bootstrap.py` | `@Configuration` | P09 如何装配 Store、策略和 Session |
| `tests/test_ch09_integration.py` | `@SpringBootTest` | 两个 Agent 实例如何共享文件记忆 |

## 先记住三个文件

| 文件 | 用途 |
| --- | --- |
| `.memory/manifest.json` | 当前有效记忆集合的唯一权威指针 |
| `.memory/MEMORY.md` | 供 selector 阅读的轻量目录，可重新生成 |
| `.memory/<name>-<id>.md` | 单条记忆的 YAML frontmatter 和完整正文 |

不要把 `MEMORY.md` 当数据库表。Java 类比中，`manifest.json` 更像事务提交后的主表，
`MEMORY.md` 更像可重建的查询视图。

## 运行

继续复用共享的 `python/.venv` 和 `python/.env`，不要在本章重新创建：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch09_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch09.cli --prompt "记住：本项目的示例只使用 PowerShell"
& ..\.venv\Scripts\python.exe -m agent_ch09.cli --prompt "这个项目的命令示例有什么约束？"
```

第一次真实运行会在当前 workspace 下生成 `.memory/`。第二次命令会创建新的 Agent，
但它仍能从文件中选择上一轮保存的规则。实际是否成功提取取决于所配置模型的输出。

完整检查：

```powershell
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch09
& ..\.venv\Scripts\python.exe -m ruff check agent_ch09 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch09 --no-incremental
```

## 一轮的时序

```text
MemorySession.begin_turn(query)
-> 从 manifest 当前集合选择相关记忆
-> MemorySession.before_model() 临时注入选中正文
-> Agent Loop 正常调用模型和工具
-> MemorySession.complete(canonical_history)
-> 提取新记忆；达到阈值时整理并一次提交
```

记忆上下文只进入本次模型请求，不追加到 canonical history。记忆 side-query 或文件写入
失败时，只在 `last_error` 留下中文说明，主 Agent 的回答仍然正常返回。
