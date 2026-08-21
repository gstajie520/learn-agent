# 第 8 章：上下文压缩与 Artifact 落盘

本章在第七章完整能力之上增加上下文压缩。大工具结果不会一直完整塞在模型历史中，
而是先保存到 `.agent_tutorial/artifacts/`，消息里只留下路径、字节数和有界预览。

## Java 开发者阅读顺序

| Python 文件 | Java/Spring 类比 | 重点 |
| --- | --- | --- |
| `tests/test_compaction.py` | Service 单元测试 | 先从输入输出理解四级压缩 |
| `features/compaction.py` | `CompactionService` | 落盘、snip、micro、摘要 |
| `core/loop.py` | 应用服务/模板方法 | 请求前处理和工具结果处理的接线位置 |
| `tests/test_ch08_integration.py` | SpringBootTest | 验证大文件结果真实落盘 |
| `bootstrap.py` | `@Configuration` | P08 如何装配同一个管理器 |

## 运行

继续复用共享的 `python/.venv` 和 `python/.env`：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch08_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch08.cli --prompt "读取一个大文件并总结，观察完整结果落盘后的路径与预览"
```

完整检查：

```powershell
& ..\.venv\Scripts\python.exe -m compileall -q agent_ch08
& ..\.venv\Scripts\python.exe -m ruff check agent_ch08 tests
& ..\.venv\Scripts\python.exe -m mypy agent_ch08 --no-incremental
```

## 四级压缩

1. `compact_tool_results()`：超过阈值的大结果先写文件。
2. `snip_compact_history()`：历史组太多时保留头尾，删除中段完整组。
3. `micro_compact_history()`：旧工具正文替换为占位符，配对关系仍保留。
4. `compact_proactively()`：仍超过预算时生成结构化摘要，并保存完整 transcript。

这里的 canonical history 类似数据库中的事实表；request history 类似发给下游服务的
查询 DTO。压缩只修改后者，不能偷偷重写事实表。
