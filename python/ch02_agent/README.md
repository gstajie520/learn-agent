# 第 2 章：给 Agent 加上工作区文件工具

这是 TypeScript 第 2 章的 Python 完整迁移版。第二章保留第一章的 Agent Loop 和 PowerShell，新增 `read_file`、`write_file`、`edit_file`、`glob` 四个工具。

```text
agent_ch02/
  core/filesystem.py       # 文件系统领域异常和 Protocol 接口
  adapters/filesystem.py   # pathlib 真实实现，负责路径安全和 UTF-8
  core/tools.py            # 工具注册、参数校验、执行边界
  features/builtin_tools.py# shell 与四个文件工具
  bootstrap.py             # 类似 Spring @Configuration 的组合根
```

共享环境只创建一次：`python/.venv` 和 `python/.env` 位于上一级 `python/` 目录，第二章不会重新创建。

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch02_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
```

真实运行前确认共享 `.env` 已配置。离线测试注入 Fake 模型和 Fake 命令执行器，不需要网络或密钥。

Java 阅读顺序建议从 `tests/test_files.py` 开始，再跳到 `create_chapter_two_tools`、`ToolRegistry.prepare/invoke`、`LocalWorkspaceFileSystem`，最后看 CLI 和 OpenAI 适配器。把 `Protocol` 当作 Java `interface`，把 `dataclass` 当作 Java record/DTO，把 `Path.resolve()` 理解成规范化并解析真实路径。
