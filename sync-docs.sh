#!/usr/bin/env bash
# 同步上游 (ryzqi/learn-agent) 的 20 篇教程文章与 AGENTS.md 到本 fork。
# 用法：bash sync-docs.sh
#
# 背景说明：
# - 本地文章自 fork 点 170dfc8 以来未被修改，可安全用上游版本覆盖；
# - 本仓库已把 code/ 重命名为 typescript/，所以覆盖后统一做路径重写；
# - README.md 是本地重写的 Python 主线版本，不在同步范围内（上游相关
#   说明已在上一提交中手动合并）。

set -euo pipefail

FILES=(
"1. Agent Loop：一个循环，就是模型与真实世界之间的全部距离（Agent架构实操一）.md"
"2. 给 Agent 加一个工具，只需要加一行（Agent架构实操二）.md"
"3. 深度拆解复刻 Claude Code 权限系统：如何实现生产级的 Agent 安全策略？（Agent架构实操三）.md"
"4. 深度解析复刻 Claude Code ：顶级 AI Agent 是如何利用 Hook 解耦的？（Agent架构实操四）.md"
"5. 为什么上下文越长，系统提示词越没用？深度揭秘 Transformer 机制下的“Agent 失忆症”（Agent架构实操五）.md"
"6. 从“单兵死磕”到“分身协作”：复杂任务下 AI Agent 的工程化突围（Agent架构实操六）.md"
"7. 别再硬塞 Prompt 了！手把手教你搭建一套工业级的 Agent Skill 技能系统（Agent架构实操七）.md"
"8. 拆解复刻Claude Code 核心设计：如何用“四级压缩法”干掉 Agent 上下文膨胀？（Agent架构实操八）.md"
"9. 从上下文压缩到文件级持久化：彻底解决 AI Agent 的健忘症（全流程解析）（Agent架构实操九）.md"
"10. 从“一锅炖”到“模块化”：重塑 AI Agent 的逻辑骨架（Agent架构实操十）.md"
"11. API 韧性即生命：决定 AI Agent 商业化成败的隐藏细节（Agent架构实操十一）.md"
"12. 实战干货：5 个工具、3 个状态，带你撸出一个生产级 Agent 任务引擎（Agent架构实操十二）.md"
"13. 从串行到异步：AI Agent 架构演进中的“慢操作”填坑指南（Agent架构实操十三）.md"
"14. 让 Agent 学会看表：Cron 调度器的设计与实现（Agent架构实操十四）.md"
"15. 解密 Claude Code 协作机制：如何通过 Inbox 注入让 AI 队友真正实现“异步通信”？（Agent架构实操十五）.md"
"16. 从“单兵作战”到“自组织团队”，多 Agent 协同的必经之路是什么？（Agent架构实操十六）.md"
"17. 从“人肉派发”到“自驱轮询”：多智能体（Agent Team）去中心化协作实战（Agent架构实操十七）.md"
"18. AI Agent也会“抢地盘”？多Agent并行开发时的文件冲突，到底该怎么解？（Agent架构实操十八）.md"
"19. 从静态工具到动态工具池：一次 MCP 接入让我重构了 Agent 架构（Agent架构实操十九）.md"
"20. Agent 架构设计：工具调用、权限控制、记忆机制、上下文压缩与 MCP 集成（Agent架构实操二十）.md"
)

echo "==> 覆盖 20 篇文章 + AGENTS.md 为上游版本..."
git checkout upstream/master -- "${FILES[@]}" AGENTS.md

echo "==> 重写 code/ 路径引用为 typescript/ ..."
for f in "${FILES[@]}"; do
  # 覆盖文章中的三种引用形态：反引号内联路径 `code/...`、Markdown 链接
  # ](code/...)、正文裸指称 code/chapters/...。所有 code/ 路径在本地都
  # 已迁移到 typescript/，因此统一替换不会破坏语义。
  sed -i 's|`code/|`typescript/|g; s|(code/)|(typescript/)|g; s|(./code/)|(./typescript/)|g; s|](code/|](typescript/|g; s|在 code/|在 typescript/|g; s|直接在 `code/`|直接在 `typescript/`|g' "$f"
done
sed -i 's|`code/|`typescript/|g; s|(code/)|(typescript/)|g' AGENTS.md

echo "==> 同步 .claude/tutorial-audit.md ..."
git checkout upstream/master -- .claude/tutorial-audit.md

echo "==> 完成。执行 git status 查看改动："
git status --short | head -30
