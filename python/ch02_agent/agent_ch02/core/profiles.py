"""章节能力白名单。第 2 章只开放 loop 和 powershell。

这是什么：章节配置管理，定义每章可用的功能集合
Java 类比：类似配置常量类，定义 ChapterProfile DTO 和预定义常量
为什么需要：控制功能渐进开放，防止越章使用未讲解的特性

Java 对照：ChapterProfile 类似一个不可变配置 DTO，P01 类似 public static final 常量。
它防止第 2 章意外装配后续章节才应该出现的能力。
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """某个章节允许启用的能力集合。

    这是什么：章节配置的值对象，定义可用功能白名单
    Java 类比：类似 record ChapterProfile(int chapter, Set<String> capabilities)
    为什么需要：显式声明每章的功能边界，支持渐进式学习和测试隔离
    """

    chapter: int  # 章节编号，例如 1。
    capabilities: frozenset[str]  # 不可变集合，类似 Collections.unmodifiableSet。


P01 = ChapterProfile(1, frozenset({"loop", "powershell"}))  # 第一章固定能力配置。
P02 = ChapterProfile(2, frozenset({"loop", "powershell", "tool_registry", "files"}))  # 第二章增加工具注册和文件操作


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """根据章节号取得配置；未迁移的章节明确报错。

    这是什么：章节配置查找函数
    Java 类比：类似 static ChapterProfile getProfile(int chapter) throws IllegalArgumentException
    为什么需要：根据章节号动态获取配置，对未实现章节快速失败
    """
    if chapter == 1:  # 第 1 章配置
        return P01
    if chapter == 2:  # 第 2 章配置
        return P02
    raise ValueError(f"第 {chapter} 章尚未迁移为 Python 版本")  # 未实现的章节明确报错
