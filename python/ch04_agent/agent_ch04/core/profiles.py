"""固定章节能力快照。

Java 对照：`ChapterProfile` 类似不可变配置 record，P01-P04 类似预定义单例常量。
组合根使用对象身份判断，调用方不能临时拼一个同字段对象来冒充正式章节。
"""

from dataclasses import dataclass
from typing import Literal

Capability = Literal["loop", "powershell", "tool_registry", "files", "policy", "hooks"]


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """章节号及其允许装配的能力白名单。

    这是什么：章节配置的不可变值对象
    Java 类比：类似 record ChapterProfile(int chapter, Set<Capability> capabilities)
    为什么需要：定义每个章节允许使用的能力白名单，防止低章节使用高章节才有的特性
    """
    chapter: int
    capabilities: frozenset[Capability]


P01 = ChapterProfile(1, frozenset({"loop", "powershell"}))  # 第一章：基础循环和 PowerShell
P02 = ChapterProfile(2, frozenset({"loop", "powershell", "tool_registry", "files"}))  # 第二章：增加工具注册和文件操作
P03 = ChapterProfile(3, frozenset({"loop", "powershell", "tool_registry", "files", "policy"}))  # 第三章：增加权限策略
P04 = ChapterProfile(4, frozenset({"loop", "powershell", "tool_registry", "files", "policy", "hooks"}))  # 第四章：增加 Hook 系统


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；尚未迁移的章节明确报错。

    这是什么：章节配置查找器
    Java 类比：类似 static ChapterProfile getProfile(int chapter)
    为什么需要：根据章节号返回对应的能力配置，未迁移的章节明确报错
    """
    profiles = {1: P01, 2: P02, 3: P03, 4: P04}
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")
    return profiles[chapter]
