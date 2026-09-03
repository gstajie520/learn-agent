"""组合根：把外部实现装配为第 2 章 Agent。

这是什么：依赖注入的组装层，负责创建和连接所有依赖
Java 类比：类似 Spring 的 @Configuration 类或手动依赖注入的工厂类
为什么需要：集中管理对象创建和依赖关系，避免核心逻辑直接 new 具体实现

Java 对照：可以把本文件理解为 Spring 的 `@Configuration` 类。
它负责创建对象和连接依赖，但不负责真正的 Agent 业务流程。
"""

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.filesystem import WorkspaceFileSystem
from .core.loop import AgentRunner, ToolAuthorizer
from .core.model import ModelClient
from .core.profiles import P01, P02, ChapterProfile
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools

SYSTEM_PROMPT = "You are a coding agent. Use tools when needed, inspect their results, and answer accurately."
# Java 对照：上面是模块常量，作用近似 `private static final String SYSTEM_PROMPT`。


def build_agent(profile: ChapterProfile, model: ModelClient, workspace: str, command_runner: CommandRunner | None = None, file_system: WorkspaceFileSystem | None = None, authorizer: ToolAuthorizer | None = None, max_turns: int = 20) -> AgentRunner:
    """创建一个第 2 章 AgentRunner。

    这是什么：Agent 工厂方法，根据章节配置组装完整的 Agent
    Java 类比：类似 @Bean AgentRunner buildAgent(...) { return new AgentRunner(...); }
    为什么需要：根据不同章节配置选择工具集，支持测试时注入 Fake 依赖

    `command_runner or PowerShellRunner()` 表示：调用者传了 Fake 就用 Fake，
    没传时才创建真实 PowerShellRunner。这就是最简单的依赖注入。
    """
    # `is` 比较对象身份，不是字段值。这样调用方不能 new 一个内容相同的 DTO
    # 冒充固定章节配置，Java 中相当于只接受预定义的单例常量。
    if profile is not P01 and profile is not P02:  # 只接受预定义的章节配置常量
        raise ValueError("必须传入固定的章节配置对象")
    command = command_runner or PowerShellRunner()  # 使用传入的 runner 或创建默认实例
    tools = (  # 根据章节选择工具集
        create_chapter_one_tools(command)
        if profile.chapter == 1  # 第 1 章只有命令工具
        else create_chapter_two_tools(command, file_system or LocalWorkspaceFileSystem())  # 第 2 章增加文件工具
    )
    return AgentRunner(model, tools, SYSTEM_PROMPT, workspace, max_turns=max_turns, authorizer=authorizer)  # 组装并返回 Agent
