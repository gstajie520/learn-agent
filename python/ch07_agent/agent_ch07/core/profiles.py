"""固定章节能力快照。

这是什么：
    章节配置模块，定义 P01-P07 各章节允许装配的能力白名单。

Java 类比：
    类似不可变配置 record + 预定义单例常量，用于控制依赖注入范围。
    P01-P07 类似 Spring Profile 的配置快照。

为什么需要：
    - 组合根使用对象身份判断，防止调用方临时伪造同字段对象来越级能力
    - 强制渐进式学习路径，第 3 章不能使用第 5 章的 TODO 能力
    - 提供清晰的章节能力边界，便于教学和测试隔离

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
]


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """章节号及其允许装配的能力白名单。

    这是什么：
        不可变的章节配置对象，定义该章节可用的能力集合。

    Java 类比：
        record ChapterProfile(int chapter, Set<Capability> capabilities)
        其中 capabilities 是 Collections.unmodifiableSet()

    为什么需要：
        - frozen=True 保证配置不可变，避免运行时被篡改
        - 用 frozenset 而非 list 保证能力集合的不可变性和查找效率
        - 明确章节边界，便于组合根校验依赖注入的合法性
    """

    chapter: int  # 章节号（1-7）
    capabilities: frozenset[Capability]  # 该章节允许的能力白名单


# 各章节的单例配置对象（使用对象身份判断，不是值比较）
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
            "skills",  # 第 7 章新增：按需加载 Skill
        }
    ),
)


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；尚未迁移的章节明确报错。

    这是什么：
        根据章节号返回对应的配置单例，拒绝无效或未实现章节。

    Java 类比：
        类似工厂方法 static ChapterProfile forChapter(int chapter)
        返回预定义的单例常量。

    为什么需要：
        - 集中管理章节配置，避免散落在各处的硬编码
        - 未实现章节明确报错，而非返回 null 或空配置
        - 确保返回的是模块内单例，不允许外部伪造
    """
    profiles = {1: P01, 2: P02, 3: P03, 4: P04, 5: P05, 6: P06, 7: P07}
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")
    return profiles[chapter]
