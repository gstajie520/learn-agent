"""固定章节能力快照。

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
    "memory",
    "dynamic_prompt",
    "recovery",
    "task_dag_json",
    "background",
    "cron",
    "teammate",
    "mailbox",
    "protocol",
    "plan_gate",
    "task_dag_sqlite",
    "work_stealing",
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
            "dynamic_prompt",
        }
    ),
)

P11 = ChapterProfile(
    11,
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
            "dynamic_prompt",
            "recovery",
        }
    ),
)

P12 = ChapterProfile(12, frozenset((*P11.capabilities, "task_dag_json")))
P13 = ChapterProfile(13, frozenset((*P12.capabilities, "background")))
P14 = ChapterProfile(14, frozenset((*P13.capabilities, "cron")))
P15 = ChapterProfile(15, frozenset((*P14.capabilities, "teammate", "mailbox")))
P16 = ChapterProfile(16, frozenset((*P15.capabilities, "protocol", "plan_gate")))
P17 = ChapterProfile(17, frozenset((*P16.capabilities, "task_dag_sqlite", "work_stealing")))


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；尚未迁移的章节明确报错。"""
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
        11: P11,
        12: P12,
        13: P13,
        14: P14,
        15: P15,
        16: P16,
        17: P17,
    }
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")
    return profiles[chapter]
