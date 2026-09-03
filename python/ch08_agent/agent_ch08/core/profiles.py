"""固定章节能力快照。

这是什么：定义每个章节启用的能力集合的配置模块
Java 类比：类似 enum ChapterProfile 或配置常量类
为什么需要：让不同章节能渐进式引入新能力，确保教学和测试的隔离性

Java 对照：`ChapterProfile` 类似不可变配置 record，P01-P06 类似预定义单例常量。
组合根使用对象身份判断，调用方不能临时拼一个同字段对象来冒充正式章节。
"""

from dataclasses import dataclass
from typing import Literal

Capability = Literal[
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
]


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """章节号及其允许装配的能力白名单。

    这是什么：封装章节配置的不可变值对象
    Java 类比：类似 record ChapterProfile(int chapter, Set<Capability> capabilities)
    为什么需要：明确每个章节启用哪些能力，防止误用未引入的特性
    """

    chapter: int
    capabilities: frozenset[Capability]


# P01-P08: 预定义的章节能力配置单例，每章逐步解锁新能力
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


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；尚未迁移的章节明确报错。

    这是什么：根据章节号查找配置的工厂函数
    Java 类比：类似 ChapterProfile.forChapter(int chapter)
    为什么需要：提供类型安全的配置查找，防止使用未定义的章节
    """
    profiles = {1: P01, 2: P02, 3: P03, 4: P04, 5: P05, 6: P06, 7: P07, 8: P08}
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")
    return profiles[chapter]
