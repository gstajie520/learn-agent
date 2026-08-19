"""章节能力白名单。第 1 章只开放 loop 和 powershell。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    chapter: int
    capabilities: frozenset[str]


P01 = ChapterProfile(1, frozenset({"loop", "powershell"}))


def profile_for_chapter(chapter: int) -> ChapterProfile:
    if chapter == 1:
        return P01
    raise ValueError(f"Chapter {chapter} has not been migrated to Python yet")
