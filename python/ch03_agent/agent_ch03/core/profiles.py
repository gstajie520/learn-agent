"""章节能力白名单。第 3 章只开放 loop 和 powershell。

Java 对照：ChapterProfile 类似一个不可变配置 DTO，P01 类似 public static final 常量。
它防止第 3 章意外装配后续章节才应该出现的能力。
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """某个章节允许启用的能力集合。"""

    chapter: int  # 章节编号，例如 1。
    capabilities: frozenset[str]  # 不可变集合，类似 Collections.unmodifiableSet。


P01 = ChapterProfile(1, frozenset({"loop", "powershell"}))  # 第一章固定能力配置。
P02 = ChapterProfile(2, frozenset({"loop", "powershell", "tool_registry", "files"}))
P03 = ChapterProfile(3, frozenset({"loop", "powershell", "tool_registry", "files", "policy"}))


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """根据章节号取得配置；未迁移的章节明确报错。"""
    if chapter == 1:
        return P01
    if chapter == 2:
        return P02
    if chapter == 3:
        return P03
    raise ValueError(f"第 {chapter} 章尚未迁移为 Python 版本")
