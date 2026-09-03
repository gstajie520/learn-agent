# Agent 架构实操

一套从零搭建生产级 AI Agent Harness 的 20 章中文教程。

本教程不把 Agent 简化成”调用一次模型 API”。它从最小的 Agent Loop 开始，逐章补齐工具、文件、权限、Hook、计划、上下文、记忆、可靠性、任务调度、多 Agent 协作、Worktree 隔离和 MCP，最后把全部能力接回同一个完整 Harness。

**当前主线：Python 实现** - 每章都有配套的 Python 代码、三段式注释（这是什么/Java类比/为什么需要）、XMind 学习脑图、Java 速通指南和面试题，读者可以边读边运行、边测试边理解设计边界。TypeScript 原始实现保留在 [`typescript/`](./typescript/) 目录供参考。

## 这套教程解决什么问题

模型负责推理和决定下一步；Harness 负责把决定安全地落到真实环境。教程围绕四个问题递进：

1. **Agent 如何行动？** 用一个稳定的循环读取模型回复、执行工具、追加结果。
2. **Agent 如何被约束？** 用文件边界、权限策略、Hook 和结构化协议控制副作用。
3. **Agent 如何处理长任务？** 用 TODO、子 Agent、Skill、上下文压缩、记忆、恢复、后台任务和 Cron 延长有效工作时间。
4. **多个 Agent 如何协作并接入外部能力？** 用任务认领、Mailbox、协议审批、SQLite、Worktree 和 MCP 形成可恢复、可审计的协作运行时。

核心原则：**每章只增加一个主要能力，前章行为继续保留；P20 不另造一套循环，而是验证前 19 章能力能否在同一个 AgentRunner 中协同工作。**

## 教程脉络

```text
Agent Loop
  -> 工具与文件边界
  -> 权限与 Hook
  -> 计划、子 Agent、Skill
  -> 产物落盘、上下文压缩、跨会话记忆
  -> 动态 Prompt、API 恢复、任务 DAG
  -> 后台任务、Cron
  -> Teammate、Mailbox、协议与计划审批
  -> SQLite 认领、Worktree 隔离
  -> MCP 动态工具池
  -> 完整 Harness
```

可以按五个阶段阅读：

| 阶段 | 章节 | 解决的问题 |
| --- | --- | --- |
| 执行基础 | 1–4 | 从循环、工具、文件边界走到权限和 Hook 生命周期 |
| 上下文与知识 | 5–10 | 让 Agent 能规划、委派、按需加载知识、压缩上下文、持久化记忆，并把运行态组装解耦 |
| 可靠执行与任务系统 | 11–14 | 处理截断、超长输入、限流、重试、任务依赖、后台作业和定时触发 |
| 多 Agent 协作与隔离 | 15–18 | 从消息投递走到协议闭环、去中心化认领和 Git Worktree 并行开发 |
| 动态扩展与总装 | 19–20 | 把外部 MCP 工具安全接入动态工具池，再验证完整 Harness 的统一边界 |

## 20 章地图

| 章 | 主题 | 本章新增的关键能力 |
| ---: | --- | --- |
| [1](<./1. Agent Loop：一个循环，就是模型与真实世界之间的全部距离（Agent架构实操一）.md>) | Agent Loop | `loop`、`powershell`：模型请求、工具结果、继续/结束的最小循环 |
| [2](<./2. 给 Agent 加一个工具，只需要加一行（Agent架构实操二）.md>) | 工具与文件 | `tool_registry`、`files`：注册表、Zod 输入、workspace 安全路径、读写文件 |
| [3](<./3. 深度拆解复刻 Claude Code 权限系统：如何实现生产级的 Agent 安全策略？（Agent架构实操三）.md>) | 权限系统 | `policy`：审批、审计、四态权限决定和统一工具错误边界 |
| [4](<./4. 深度解析复刻 Claude Code ：顶级 AI Agent 是如何利用 Hook 解耦的？（Agent架构实操四）.md>) | Hook 解耦 | `hooks`：UserPromptSubmit、PreToolUse、PostToolUse、Stop 四个生命周期点 |
| [5](<./5. 为什么上下文越长，系统提示词越没用？深度揭秘 Transformer 机制下的“Agent 失忆症”（Agent架构实操五）.md>) | 会话计划 | `todo`：完整快照、状态校验、陈旧计划提醒，避免长任务漂移 |
| [6](<./6. 从“单兵死磕”到“分身协作”：复杂任务下 AI Agent 的工程化突围（Agent架构实操六）.md>) | 子 Agent | `subagent`：隔离历史、共享运行边界、禁止递归委派、限制轮数 |
| [7](<./7. 别再硬塞 Prompt 了！手把手教你搭建一套工业级的 Agent Skill 技能系统（Agent架构实操七）.md>) | Skill 系统 | `skills`：先扫描摘要，再按名称加载正文，知识按需进入上下文 |
| [8](<./8. 拆解复刻Claude Code 核心设计：如何用“四级压缩法”干掉 Agent 上下文膨胀？（Agent架构实操八）.md>) | 上下文压缩 | `artifacts`、`compaction`：结果落盘、分层裁剪、摘要恢复上下文预算 |
| [9](<./9. 从上下文压缩到文件级持久化：彻底解决 AI Agent 的健忘症（全流程解析）（Agent架构实操九）.md>) | 文件记忆 | `memory`：从 canonical history 提取、整理并跨会话检索持久记忆 |
| [10](<./10. 从“一锅炖”到“模块化”：重塑 AI Agent 的逻辑骨架（Agent架构实操十）.md>) | 动态上下文 | `dynamic_prompt`：Provider 按固定顺序生成运行态系统提示，避免复制 Loop |
| [11](<./11. API 韧性即生命：决定 AI Agent 商业化成败的隐藏细节（Agent架构实操十一）.md>) | API 恢复 | `recovery`：截断、超长、429/529、Retry-After、fallback、取消与总时限 |
| [12](<./12. 实战干货：5 个工具、3 个状态，带你撸出一个生产级 Agent 任务引擎（Agent架构实操十二）.md>) | 任务 DAG | `task_dag_json`：任务依赖、原子 JSON 持久化、DAG 校验、owner 防伪造 |
| [13](<./13. 从串行到异步：AI Agent 架构演进中的“慢操作”填坑指南（Agent架构实操十三）.md>) | 后台任务 | `background`：先落盘再启动 worker，以占位结果和完成事件连接异步作业 |
| [14](<./14. 让 Agent 学会看表：Cron 调度器的设计与实现（Agent架构实操十四）.md>) | Cron 调度 | `cron`：时区计算、UTC 持久化、durable/session-only 生命周期和 outbox 触发 |
| [15](<./15. 解密 Claude Code 协作机制：如何通过 Inbox 注入让 AI 队友真正实现“异步通信”？（Agent架构实操十五）.md>) | Teammate 与 Mailbox | `teammate`、`mailbox`：持久队友、FIFO 消息、恢复、坏消息隔离和 Inbox 注入 |
| [16](<./16. 从“单兵作战”到“自组织团队”，多 Agent 协同的必经之路是什么？（Agent架构实操十六）.md>) | 协作协议 | `protocol`、`plan_gate`：先登记再发送、完整匹配响应、计划审批和确定性 shutdown |
| [17](<./17. 从“人肉派发”到“自驱轮询”：多智能体（Agent Team）去中心化协作实战（Agent架构实操十七）.md>) | SQLite 认领 | `task_dag_sqlite`、`work_stealing`：事务内原子认领、租约、token 历史和角色工具裁剪 |
| [18](<./18. AI Agent也会“抢地盘”？多Agent并行开发时的文件冲突，到底该怎么解？（Agent架构实操十八）.md>) | Worktree 隔离 | `worktree`：预留、绑定、执行上下文、claim 路由和 `needs_review` 清理边界 |
| [19](<./19. 从静态工具到动态工具池：一次 MCP 接入让我重构了 Agent 架构（Agent架构实操十九）.md>) | MCP 工具池 | `mcp`：allowlist、连接、发布工具、命名隔离、策略分类和下一轮 Registry Snapshot |
| [20](<./20. Agent 架构设计：工具调用、权限控制、记忆机制、上下文压缩与 MCP 集成（Agent架构实操二十）.md>) | 完整 Harness | `full_harness`：统一组合根、单一 AgentRunner、动态上下文、MCP 边界和资源关闭 |

## 配套代码如何组织

### Python 实现（当前主线）

代码位于 [`python/`](./python/)。所有章节共享一个虚拟环境，每章是独立的 Python 包：

```text
python/
├─ .venv/                      # 共享虚拟环境（一次性创建）
├─ .env                        # 共享 API 配置
├─ ch01_agent/                 # 第 1 章：Agent Loop 基础
│  ├─ agent_ch01/              # Python 包（模块化代码）
│  │  ├─ core/                 # 核心模块（loop.py, tools.py, model.py 等）
│  │  ├─ adapters/             # 适配器（openai_chat.py, powershell.py 等）
│  │  ├─ features/             # 功能模块（builtin_tools.py 等）
│  │  └─ cli.py                # 命令行入口
│  ├─ tests/                   # 单元测试
│  ├─ pyproject.toml           # 依赖声明
│  ├─ ch01_learning_roadmap.xmind   # XMind 学习脑图
│  ├─ ch01_learning_roadmap.md      # Markdown 脑图备份
│  ├─ JAVA_QUICKSTART.txt      # Java 开发者 45 分钟速通指南
│  └─ generate_xmind.py        # XMind 生成脚本
├─ ch02_agent/                 # 第 2 章：工具注册与文件边界
│  └─ ...（结构同 ch01）
├─ ...
└─ ch20_agent/                 # 第 20 章：完整 Harness

每章学习材料：
- XMind 脑图：6 个分支（学习路线、核心文件、Java对照、设计模式、关键概念、面试题）
- JAVA_QUICKSTART.txt：3-4 步学习路线 + 5 个必打断点 + 3 个可选断点 + FAQ
- 三段式代码注释：「这是什么」+「Java 类比」+「为什么需要」
- 6-8 道面试题（含详细答案）
```

各章不是互相独立的玩具项目：后续章节在前章基础上扩展能力，每章是完整的可运行快照。实现细节以当前源码和测试为准。

### TypeScript 原始实现（参考）

TypeScript 原始实现保留在 [`typescript/`](./typescript/) 目录：

```text
typescript/
├─ chapters/
│  ├─ ch01/
│  │  ├─ src/       # TypeScript 实现
│  │  └─ tests/     # 行为测试
│  ├─ ...
│  └─ ch20/
├─ skills/
├─ scripts/
├─ package.json
└─ .env.example
```

## 开始阅读与运行

### Python 实现（推荐）

#### 1. 准备环境

- Windows 11 示例命令统一使用 PowerShell。
- Python `>=3.11`。
- 在 `python/` 中创建虚拟环境：

```powershell
cd C:\ajie\code\learn-agent\python

# 创建虚拟环境
python -m venv .venv

# 升级 pip
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

真实模型运行需要配置 `.env`。先复制模板，再填写 API Key：

```powershell
if (-not (Test-Path '.env')) {
  Copy-Item '.env.example' '.env'
}
```

编辑 `.env` 文件：

```text
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx  # 填入你的 DeepSeek API Key
OPENAI_MODEL=deepseek-chat
```

#### 2. 安装章节并运行

按学习进度逐章安装（推荐）：

```powershell
# 安装 ch01（必须！是所有章节的基础）
.\.venv\Scripts\python.exe -m pip install -e .\ch01_agent[dev]

# 运行测试验证环境
.\.venv\Scripts\python.exe -m pytest .\ch01_agent\tests -v

# 手动运行 Agent
.\.venv\Scripts\python.exe -m agent_ch01.cli “1+1等于几？”

# 继续安装其他章节
.\.venv\Scripts\python.exe -m pip install -e .\ch02_agent[dev]
.\.venv\Scripts\python.exe -m pip install -e .\ch03_agent[dev]
# ... 以此类推
```

或者一次性安装所有章节：

```powershell
for ($i=1; $i -le 20; $i++) {
    $ch = “ch{0:D2}_agent” -f $_
    .\.venv\Scripts\python.exe -m pip install -e “.\$ch[dev]”
}
```

#### 3. 学习材料

每章提供完整的学习材料：

1. **打开 XMind 脑图**：`chXX_learning_roadmap.xmind`
   - 6 个主分支：学习路线、核心文件、Java对照、设计模式、关键概念、面试题速查
   
2. **阅读 Java 速通指南**：`JAVA_QUICKSTART.txt`
   - 3-4 步学习路线（45 分钟）
   - 调试断点速查（5 个必打 + 3 个可选，标注行号和观察点）
   - 核心概念速记、FAQ 常见问题

3. **阅读代码注释**：所有 `.py` 文件都有三段式注释
   - 这是什么（功能描述）
   - Java 类比（对照 Java 语法/概念）
   - 为什么需要（设计动机）

4. **做面试题**：每章 6-8 道面试题在脑图和速通指南中

---

### TypeScript 实现（参考）

如果你想参考 TypeScript 原始实现，进入 `typescript/` 目录：

#### 1. 准备环境

- Node.js `>=20.12`。
- 在 `typescript/` 中安装依赖：

```powershell
Set-Location '.\typescript'
npm ci
```

真实模型运行需要配置 `.env`：

```powershell
if (-not (Test-Path '.env')) {
  Copy-Item '.env.example' '.env'
}
```

```text
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_FALLBACK_MODEL=
```

#### 2. 运行单章

每章都有固定 npm script：

```powershell
npm run ch01 -- --prompt “列出当前目录”
npm run ch20 -- --prompt “验证完整 Harness”
```

也可以通过统一入口选择章节：

```powershell
npm run agent-tutorial -- run --chapter 12 --prompt “建立任务依赖”
```

#### 3. 验证实现

从 `typescript/` 执行：

```powershell
npm run typecheck
npm run test:ch01
npm run test:ch20
npm test
npm run lint
npm run format:check
npm run build
npm run verify:snapshot-drift
```

## 推荐阅读方式

### Python 实现（当前主线）

1. **先看学习材料**：打开 `chXX_learning_roadmap.xmind`，浏览 6 个分支，快速建立全局认知
2. **读 Java 速通指南**：`JAVA_QUICKSTART.txt` 提供 3-4 步学习路线（45 分钟）
3. **打断点调试**：按速通指南的断点列表，单步执行理解流程
4. **阅读核心代码**：重点读 `core/`、`features/`、`adapters/` 的关键文件，三段式注释帮你快速理解
5. **运行测试**：`pytest chXX_agent/tests -v` 观察状态、事件、权限、文件和错误分支
6. **做面试题**：验证理解，脑图和速通指南中有 6-8 道题及答案
7. **对比下一章**：看新增了哪些能力，为什么不能塞回旧模块

推荐学习顺序：
- **第 1 周**：ch01（Agent Loop 基础）- 深入 3 天，理解透彻
- **第 2 周**：ch02-ch03（工具注册 + 权限系统）
- **第 3-4 周**：ch04-ch07（Hook、TODO、子Agent、Skill）
- **第 5-7 周**：ch08-ch14（上下文压缩、记忆、模块化、API韧性、Task DAG、后台任务、Cron）
- **第 8-10 周**：ch15-ch20（Mailbox、多Agent、自驱队友、Worktree、MCP、完整Harness）

**总耗时**：1.5-2 个月（每天 1-1.5 小时深度学习）

### TypeScript 实现（参考）

1. 先读文章中的”验收结果/问题本质”，明确本章要证明什么。
2. 再看 `typescript/chapters/chNN/src/` 的组合根、核心类型和工具 handler。
3. 运行该章测试，观察状态、事件、权限、文件和错误分支。
4. 用下一章对比上一章：只找新增能力，以及新增能力为什么不能塞回旧模块。
5. 读到第 20 章时，回看同一个 `AgentRunner` 的执行顺序、Registry Snapshot、tool result 配对、权限边界和资源关闭。

## 参考来源与关系

本教程参考以下公开项目的思想、章节组织和工程讨论；代码、章节编号、TypeScript 实现与验收标准属于本仓库自身，不是它们的官方翻译或逐章复制。

- [`bojieli/ai-agent-book`](https://github.com/bojieli/ai-agent-book)：《深入理解 AI Agent：设计原理与工程实践》。它以“Agent = LLM + 上下文 + 工具”为主线，提供 10 章正文和大量配套实验。本教程借鉴其从原理走向工程实践、先定义评估再落实现制的方式；第 9、10、14、15 章等文章也会明确讨论对应取舍。
- [`shareAI-lab/learn-claude-code`](https://github.com/shareAI-lab/learn-claude-code)：从零构建 Claude Code 风格 agent harness 的累进教程。它把工具、知识、观察、动作接口、权限和单一 Agent Loop 放在同一 Harness 视角下。本教程借鉴其“每课只增加一个机制、最后重新集成”的教学方法，并结合 TypeScript、严格契约和本仓库的测试门禁重新实现。

两份参考项目关注点不同：前者提供更宽的 Agent 原理、上下文、记忆、工具和多 Agent 视野；后者深入 Claude Code 风格 Harness 的内部机制。本教程把两种视角收敛为一条可运行的 20 章工程路线。

## 讨论与反馈

欢迎在 [LINUX DO](https://linux.do/) 讨论阅读疑问、架构取舍、运行问题和改进建议。发帖前请遵守社区规则；本 README 只提供讨论入口，不代替社区规范。

## 许可证与贡献

本仓库的文章与代码以仓库实际文件中的声明为准。改进教程时，建议保持“一章一主题、代码与文章同步、先验证后宣称完成”的节奏，并在提交中说明受影响章节和验证命令。
