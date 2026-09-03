"""固定章节能力快照。

Java 对照：`ChapterProfile` 类似不可变配置 record，P01-P09 类似预定义单例常量。
组合根使用对象身份判断，调用方不能临时拼一个同字段对象来冒充正式章节。

这是什么：章节能力的配置定义，每章渐进式增加功能
Java 类比：类似 Spring Profile 或枚举配置类
为什么需要：确保每章只启用对应的功能，防止能力越级使用
"""

from dataclasses import dataclass
from typing import Literal

# 能力类型：定义所有可用的 Agent 功能模块
Capability = Literal[
    "loop",         # 核心循环
    "powershell",   # PowerShell 命令执行
    "tool_registry",# 工具注册表
    "files",        # 文件系统操作
    "policy",       # 权限策略
    "hooks",        # Hook 生命周期
    "todo",         # TODO 跟踪
    "subagent",     # 子 Agent
    "skills",       # Skill 按需加载
    "artifacts",    # Artifact 支持
    "compaction",   # 上下文压缩
    "memory",       # 长期记忆
]


@dataclass(frozen=True, slots=True)
class ChapterProfile:
    """章节号及其允许装配的能力白名单。

    这是什么：章节配置的不可变数据对象
    Java 类比：类似 record ChapterProfile(int chapter, Set<Capability> capabilities)
    为什么需要：定义每章的能力边界，确保教学进度和功能匹配

    参数：
        chapter: 章节号（1-9）
        capabilities: 该章允许使用的能力集合（不可变）
    """

    chapter: int  # 章节号
    capabilities: frozenset[Capability]  # 能力白名单


# ==================== 章节配置单例 ====================
# 每个章节是一个预定义的不可变对象，通过对象身份（is）判断

P01 = ChapterProfile(1, frozenset({"loop", "powershell"}))
"""第一章：基础循环 + PowerShell 命令执行"""

P02 = ChapterProfile(2, frozenset({"loop", "powershell", "tool_registry", "files"}))
"""第二章：增加工具注册表和文件系统操作"""

P03 = ChapterProfile(3, frozenset({"loop", "powershell", "tool_registry", "files", "policy"}))
"""第三章：增加权限策略"""

P04 = ChapterProfile(
    4, frozenset({"loop", "powershell", "tool_registry", "files", "policy", "hooks"})
)
"""第四章：增加 Hook 生命周期"""

P05 = ChapterProfile(
    5, frozenset({"loop", "powershell", "tool_registry", "files", "policy", "hooks", "todo"})
)
"""第五章：增加 TODO 跟踪"""

P06 = ChapterProfile(
    6,
    frozenset(
        {"loop", "powershell", "tool_registry", "files", "policy", "hooks", "todo", "subagent"}
    ),
)
"""第六章：增加子 Agent"""

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
"""第七章：增加 Skill 按需加载"""

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
"""第八章：增加 Artifact 支持和上下文压缩"""

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
"""第九章：增加长期记忆"""


def profile_for_chapter(chapter: int) -> ChapterProfile:
    """根据章节号返回对应的配置对象。

    这是什么：章节配置的查找方法
    Java 类比：类似 ChapterProfile getProfile(int chapter)
    为什么需要：提供统一的配置获取接口，确保只返回预定义的单例

    参数：
        chapter: 章节号（1-9）

    返回：
        ChapterProfile: 对应章节的配置单例

    异常：
        ValueError: 章节号无效或尚未迁移
    """
    # 章节号到配置对象的映射表
    profiles = {1: P01, 2: P02, 3: P03, 4: P04, 5: P05, 6: P06, 7: P07, 8: P08, 9: P09}

    # 校验章节号类型和范围
    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 20:
        raise ValueError("chapter 必须是 1 到 20 的整数")

    # 检查章节是否已迁移
    if chapter not in profiles:
        raise ValueError(f"第 {chapter} 章尚未迁移为 Python")

    return profiles[chapter]
