"""固定章节能力快照。

Java 对照：`ChapterProfile` 类似不可变配置 record，P01-P20 类似预定义单例常量。
组合根使用对象身份判断（`is`），调用方不能临时拼一个同字段对象来冒充正式章节。

第 20 章把原来逐章手写的能力集合改成"增量表 + 累计推导"：
每章只声明自己新增的能力，`_PROFILES` 再把前缀累加成完整档案。
这样"第 N 章档案必须是第 N-1 章的严格超集"由数据结构保证，而不是靠人工核对。
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
    # task_dag_sqlite 与 work_stealing 表示带租约的 SQLite 任务图与去中心化认领。
    "task_dag_sqlite",
    "work_stealing",
    # worktree 表示受控 Git 工作树隔离，mcp 表示可动态发布和撤销的远程 MCP 工具边界。
    "worktree",
    "mcp",
    # full_harness 标记 P20 完整能力集，不新增独立运行时。
    "full_harness",
]


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """章节号及其允许装配的能力白名单。

    字段说明：
    - `chapter`：章节号，组合根用它填充 Prompt 的静态 context；
    - `capabilities`：该章允许启用的能力集合，`frozenset` 保证构造后不可增删。

    Java 对照：等价于一个只有 getter 的不可变 record，`frozenset` 类似
    `Set.copyOf(...)` 返回的只读集合。
    """

    chapter: int
    capabilities: frozenset[Capability]


# 每章只声明"本章新增"的能力；完整档案由前缀累加得到。
# Java 对照：类似 `List<List<String>>` 常量表，元素顺序即章节顺序。
_PROFILE_DELTAS: tuple[tuple[Capability, ...], ...] = (
    ("loop", "powershell"),
    ("tool_registry", "files"),
    ("policy",),
    ("hooks",),
    ("todo",),
    ("subagent",),
    ("skills",),
    ("artifacts", "compaction"),
    ("memory",),
    ("dynamic_prompt",),
    ("recovery",),
    ("task_dag_json",),
    ("background",),
    ("cron",),
    ("teammate", "mailbox"),
    ("protocol", "plan_gate"),
    ("task_dag_sqlite", "work_stealing"),
    ("worktree",),
    ("mcp",),
    # full_harness 是 P20 的标记能力：不新增具体运行时，只声明前十九章能力全部生效。
    ("full_harness",),
)


def _build_profiles() -> tuple[ChapterProfile, ...]:
    """把增量表累加成每章的完整档案。

    这里用普通 for 循环而不是推导式，因为要维护一个跨轮次累积的 `accumulated` 列表；
    Java 对照：等价于在循环里对 `Set` 反复 `addAll` 并每轮快照一次。
    """
    profiles: list[ChapterProfile] = []
    accumulated: list[Capability] = []
    for index, delta in enumerate(_PROFILE_DELTAS):
        # extend 就地追加本章增量，因此下一轮天然包含所有历史能力。
        accumulated.extend(delta)
        profiles.append(ChapterProfile(index + 1, frozenset(accumulated)))
    # tuple(...) 冻结外层序列，避免调用方替换某一章的档案对象。
    return tuple(profiles)


_PROFILES = _build_profiles()


def _profile_at(chapter: int) -> ChapterProfile:
    """按章节号取固定档案；越界视为编程错误而不是返回空能力集。"""
    if not 1 <= chapter <= len(_PROFILES):
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")
    return _PROFILES[chapter - 1]


P01 = _profile_at(1)
P02 = _profile_at(2)
P03 = _profile_at(3)
P04 = _profile_at(4)
P05 = _profile_at(5)
P06 = _profile_at(6)
P07 = _profile_at(7)
P08 = _profile_at(8)
P09 = _profile_at(9)
P10 = _profile_at(10)
P11 = _profile_at(11)
P12 = _profile_at(12)
P13 = _profile_at(13)
P14 = _profile_at(14)
P15 = _profile_at(15)
P16 = _profile_at(16)
P17 = _profile_at(17)
P18 = _profile_at(18)
P19 = _profile_at(19)
# P20 是完整 Harness 档案，统一启用前十九章已经验证的累计能力。
P20 = _profile_at(20)


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；越界或非整数输入立即失败。

    `isinstance(chapter, bool)` 需要单独排除，因为 Python 的 `bool` 是 `int` 子类，
    `True` 会被 `isinstance(True, int)` 判为真。Java 中 `boolean` 与 `int` 无继承关系，
    不需要这一步。
    """
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")
    return _profile_at(chapter)
