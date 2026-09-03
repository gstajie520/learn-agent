"""固定章节能力快照。

Java 对照：`ChapterProfile` 类似不可变配置 record，P01-P05 类似预定义单例常量。
组合根使用对象身份判断，调用方不能临时拼一个同字段对象来冒充正式章节。

这是什么：定义每章 Agent 允许使用的能力边界
为什么需要：防止越级使用未学功能，确保教程循序渐进
"""

from dataclasses import dataclass
from typing import Literal

# 能力字面量联合类型，类似 Java 的能力枚举
Capability = Literal["loop", "powershell", "tool_registry", "files", "policy", "hooks", "todo"]


@dataclass(frozen=True, slots=True)  # frozen=True 表示不可变，类似 Java record
class ChapterProfile:
    """章节号及其允许装配的能力白名单。

    这是什么：一个章节的能力配置对象
    Java 类比：record ChapterProfile(int chapter, Set<Capability> capabilities)
    为什么需要：让组合根通过对象身份（is 比较）验证章节合法性，防止伪造
    """
    chapter: int  # 章节序号，1-20
    capabilities: frozenset[Capability]  # 该章允许的能力集合，frozenset 是不可变 Set


# 预定义的章节单例常量，类似 Java 的 public static final ChapterProfile P01 = ...
P01 = ChapterProfile(1, frozenset({"loop", "powershell"}))  # 第 1 章：基础循环 + Shell
P02 = ChapterProfile(2, frozenset({"loop", "powershell", "tool_registry", "files"}))  # 第 2 章：+工具注册+文件
P03 = ChapterProfile(3, frozenset({"loop", "powershell", "tool_registry", "files", "policy"}))  # 第 3 章：+权限策略
P04 = ChapterProfile(4, frozenset({"loop", "powershell", "tool_registry", "files", "policy", "hooks"}))  # 第 4 章：+Hook 生命周期
P05 = ChapterProfile(5, frozenset({"loop", "powershell", "tool_registry", "files", "policy", "hooks", "todo"}))  # 第 5 章：+TODO 跟踪


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """只返回模块内固定单例；尚未迁移的章节明确报错。

    这是什么：根据章节号返回对应的能力配置
    Java 类比：static ChapterProfile forChapter(int chapter) throws IllegalArgumentException
    为什么需要：CLI 参数只能传数字，需要转换成预定义的配置对象
    """
    # 固定映射表：只有这些章节已经实现，类似 Java 的 Map.of(1, P01, 2, P02, ...)
    profiles = {1: P01, 2: P02, 3: P03, 4: P04, 5: P05}

    # Python 的 bool 是 int 的子类，必须先排除 True/False，避免 chapter=True 被当成 1
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")

    # 尚未实现的章节明确拒绝，而不是返回一个临时拼凑的对象
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")

    return profiles[chapter]  # 返回模块级单例，组合根用 is 判断对象身份
