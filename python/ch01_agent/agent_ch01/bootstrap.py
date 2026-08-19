"""组合根：把外部实现装配为第 1 章 Agent。

Java 对照：可以把本文件理解为 Spring 的 `@Configuration` 类。
它负责创建对象和连接依赖，但不负责真正的 Agent 业务流程。
"""

from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.loop import AgentRunner, ToolAuthorizer
from .core.model import ModelClient
from .core.profiles import ChapterProfile
from .features.builtin_tools import create_chapter_one_tools

SYSTEM_PROMPT = "You are a coding agent. Use tools when needed, inspect their results, and answer accurately."
# Java 对照：上面是模块常量，作用近似 `private static final String SYSTEM_PROMPT`。


def build_agent(profile: ChapterProfile, model: ModelClient, workspace: str, command_runner: CommandRunner | None = None, authorizer: ToolAuthorizer | None = None, max_turns: int = 20) -> AgentRunner:
    """创建一个第 1 章 AgentRunner。

    `command_runner or PowerShellRunner()` 表示：调用者传了 Fake 就用 Fake，
    没传时才创建真实 PowerShellRunner。这就是最简单的依赖注入。
    """
    if profile.chapter != 1:
        raise ValueError(f"第 {profile.chapter} 章尚未迁移为 Python 版本")
    return AgentRunner(model, create_chapter_one_tools(command_runner or PowerShellRunner()), SYSTEM_PROMPT, workspace, max_turns=max_turns, authorizer=authorizer)
