"""组合根：把外部实现装配为第 2 章 Agent。

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

    `command_runner or PowerShellRunner()` 表示：调用者传了 Fake 就用 Fake，
    没传时才创建真实 PowerShellRunner。这就是最简单的依赖注入。
    """
    # `is` 比较对象身份，不是字段值。这样调用方不能 new 一个内容相同的 DTO
    # 冒充固定章节配置，Java 中相当于只接受预定义的单例常量。
    if profile is not P01 and profile is not P02:
        raise ValueError("必须传入固定的章节配置对象")
    command = command_runner or PowerShellRunner()
    tools = (
        create_chapter_one_tools(command)
        if profile.chapter == 1
        else create_chapter_two_tools(command, file_system or LocalWorkspaceFileSystem())
    )
    return AgentRunner(model, tools, SYSTEM_PROMPT, workspace, max_turns=max_turns, authorizer=authorizer)
