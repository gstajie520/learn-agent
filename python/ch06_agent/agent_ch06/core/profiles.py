"""固定章节能力快照。

这是什么：定义每个章节的能力配置
Java 类比：record ChapterProfile(int chapter, Set<Capability> capabilities)
为什么需要：确保每个章节只启用对应的功能，防止跨章节能力混用

Java 对照：`ChapterProfile` 类似不可变配置 record，P01-P06 类似预定义单例常量。
组合根使用对象身份判断，调用方不能临时拼一个同字段对象来冒充正式章节。
"""

from dataclasses import dataclass
from typing import Literal

Capability = Literal[
    "loop", "powershell", "tool_registry", "files", "policy", "hooks", "todo", "subagent"
]


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """章节号及其允许装配的能力白名单。"""

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


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；尚未迁移的章节明确报错。"""
    profiles = {1: P01, 2: P02, 3: P03, 4: P04, 5: P05, 6: P06}
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")
    return profiles[chapter]
