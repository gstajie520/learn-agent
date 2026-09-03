"""固定章节能力快照。

Java 对照：`ChapterProfile` 类似不可变配置 record，P01-P10 类似预定义单例常量。
组合根使用对象身份判断，调用方不能临时拼一个同字段对象来冒充正式章节。

这是什么：章节能力配置模块，定义每章可用的功能集合
为什么需要：
    1. 每章逐步引入新能力（loop → tools → policy → hooks...）
    2. Bootstrap 根据 Profile 决定装配哪些组件
    3. 单例模式防止伪造 Profile
"""

from dataclasses import dataclass
from typing import Literal

Capability = Literal[
    "loop",          # 基础 Agent 循环
    "powershell",    # PowerShell 工具
    "tool_registry", # 工具注册表
    "files",         # 文件读写工具
    "policy",        # 权限策略
    "hooks",         # 生命周期钩子
    "todo",          # TODO 管理
    "subagent",      # 子 Agent 调用
    "skills",        # 按需加载 Skill
    "artifacts",     # Artifact 生成
    "compaction",    # 历史压缩
    "memory",        # 长期记忆
    "dynamic_prompt",# 动态 System Prompt
]


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """章节号及其允许装配的能力白名单。

    这是什么：不可变配置对象，定义某章可用的功能集合
    Java 类比：不可变 record，类似 @ConfigurationProperties
    为什么需要：
        1. 明确每章的能力边界（逐章递增）
        2. Bootstrap 根据白名单决定装配哪些组件
        3. frozen=True 防止运行时修改

    字段：
        chapter: 章节号（1-20）
        capabilities: 允许的能力集合（frozenset 不可变）
    """

    chapter: int
    capabilities: frozenset[Capability]


P01 = ChapterProfile(1, frozenset({"loop", "powershell"}))
P02 = ChapterProfile(2, frozenset({"loop", "powershell", "tool_registry", "files"}))
P03 = ChapterProfile(3, frozenset({"loop", "powershell", "tool_registry", "files", "policy"}))
P04 = ChapterProfile(
    4, frozenset({"loop", "powershell", "tool_registry", "files", "policy", "hooks"})
)
P05 = ChapterProfile(
    5, frozenset({"loop", "powershell", "tool_registry", "files", "policy", "hooks", "todo"})
)
P06 = ChapterProfile(
    6,
    frozenset(
        {"loop", "powershell", "tool_registry", "files", "policy", "hooks", "todo", "subagent"}
    ),
)
P07 = ChapterProfile(
    7,
    frozenset(
        {
            "loop",
            "powershell",
            "tool_registry",
            "files",
            "policy",
            "hooks",
            "todo",
            "subagent",
            "skills",
        }
    ),
)

P08 = ChapterProfile(
    8,
    frozenset(
        {
            "loop",
            "powershell",
            "tool_registry",
            "files",
            "policy",
            "hooks",
            "todo",
            "subagent",
            "skills",
            "artifacts",
            "compaction",
        }
    ),
)

P09 = ChapterProfile(
    9,
    frozenset(
        {
            "loop",
            "powershell",
            "tool_registry",
            "files",
            "policy",
            "hooks",
            "todo",
            "subagent",
            "skills",
            "artifacts",
            "compaction",
            "memory",
        }
    ),
)

P10 = ChapterProfile(
    10,
    frozenset(
        {
            "loop",          # 第 1 章：基础循环
            "powershell",    # 第 1 章：PowerShell 工具
            "tool_registry", # 第 2 章：工具注册表
            "files",         # 第 2 章：文件读写
            "policy",        # 第 3 章：权限策略
            "hooks",         # 第 4 章：生命周期钩子
            "todo",          # 第 5 章：TODO 管理
            "subagent",      # 第 6 章：子 Agent
            "skills",        # 第 7 章：按需加载 Skill
            "artifacts",     # 第 8 章：Artifact 生成
            "compaction",    # 第 8 章：历史压缩
            "memory",        # 第 9 章：长期记忆
            "dynamic_prompt",# 第 10 章：动态 System Prompt（本章新增）
        }
    ),
)


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；尚未迁移的章节明确报错。

    这是什么：Profile 工厂方法，根据章节号返回对应的单例
    Java 类比：类似 enum 的 valueOf() 或单例注册表
    为什么需要：
        1. 集中管理所有 Profile，避免调用方直接引用 P01-P10
        2. 明确报错未迁移的章节（而不是返回 None）
        3. 返回单例保证对象身份（is 比较）

    参数：
        chapter: 章节号（1-20）

    返回：
        对应章节的 ChapterProfile 单例

    抛出：
        ValueError: chapter 不是 1-20 的整数，或该章尚未迁移
    """
    profiles = {
        1: P01,
        2: P02,
        3: P03,
        4: P04,
        5: P05,
        6: P06,
        7: P07,
        8: P08,
        9: P09,
        10: P10,
    }
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")
    return profiles[chapter]
