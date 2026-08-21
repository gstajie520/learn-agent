# 第 7 章：按需加载 Skill

本章在第六章一次性子 Agent 基础上增加 `load_skill` 工具。启动时只把 `skills/` 目录中的名称和一行描述放进 System Prompt；模型明确调用 `load_skill` 后，才把对应 `SKILL.md` 正文作为 tool result 放进消息历史。

## Java 开发者阅读顺序

| Python 写法 | Java/Spring 类比 | 作用 |
| --- | --- | --- |
| `SkillRegistry` | 只读配置/路由注册表 | 扫描 Skill 元数据并提供加载工具 |
| `SkillSummary` | Java record / DTO | 保存模型路由所需的 name、description |
| `_SkillRecord` | 内部领域对象 | 保存目录和 manifest 的受控路径 |
| `SkillRegistry.scan()` | 初始化阶段的配置扫描 | 只读取 frontmatter，不读取正文 |
| `load_skill` | Controller/Service 方法 | 按名称重新校验路径并读取正文 |
| `validator` | Bean Validation | 在 handler 前拒绝路径穿越、未知字段和非法名称 |

先读：

```text
python/ch07_agent/
  agent_ch07/features/skills.py       # 本章核心
  agent_ch07/bootstrap.py             # P07 接线和父子工具集
  tests/test_skills.py                # Skill 单元边界
  tests/test_ch07_integration.py      # 完整 Agent Loop 接线
  skills/python-style/SKILL.md       # 可直接加载的示例
```

共享使用 `python/.venv` 和 `python/.env`，本章不会重新创建它们：

```powershell
Set-Location 'E:\cj\study\learn-agent\python\ch07_agent'
& ..\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& ..\.venv\Scripts\python.exe -m pytest tests
& ..\.venv\Scripts\python.exe -m agent_ch07.cli --prompt "先调用 load_skill 加载 python-style，再总结其中两条约定"
```

## 两级加载

第一层是目录摘要：

```text
- **python-style**: Use when 编写或审查 Python 模块、类型标注和文件路径；Don't use for SQL 或部署。
```

第二层是正文：

```text
# Python Style

外部输入先按 unknown 思路处理，进入业务逻辑前先做运行时校验。
```

目录默认最多 100 项、8000 个 UTF-8 字节；单条目录不会被截成半行。Skill 名称只能使用小写字母、数字和连字符，不能使用 `../secret`、`nul` 或绝对路径。扫描和加载都会检查真实路径仍在 workspace 内，防止符号链接替换后逃逸。

第七章的父工具顺序为 `shell, read_file, write_file, edit_file, glob, todo_write, task, load_skill`。子 Agent 也能调用 `load_skill`，但仍然没有 `task`；Skill 正文只进入调用它的那条历史。
