"""组合根：把外部实现装配为第 3 章 Agent。

这是什么：依赖注入容器，负责创建和连接各层对象。
Java 类比：类似 Spring 的 @Configuration 类或 ApplicationContext。
为什么需要：单一职责原则，装配逻辑和业务逻辑分离，便于测试时替换依赖。

Java 对照：可以把本文件理解为 Spring 的 `@Configuration` 类。
它负责创建对象和连接依赖，但不负责真正的 Agent 业务流程。
"""

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.filesystem import WorkspaceFileSystem
from .core.loop import AgentRunner, ToolAuthorizer
from .core.model import ModelClient
from .core.permissions import (
    ApprovalProvider,
    AuditSink,
    PermissionPolicy,
    PermissionRule,
)
from .core.profiles import P01, P02, P03, ChapterProfile
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools

SYSTEM_PROMPT = "You are a coding agent. Use tools when needed, inspect their results, and answer accurately."
# Java 对照：上面是模块常量，作用近似 `private static final String SYSTEM_PROMPT`。


def build_agent(profile: ChapterProfile, model: ModelClient, workspace: str, command_runner: CommandRunner | None = None, file_system: WorkspaceFileSystem | None = None, authorizer: ToolAuthorizer | None = None, approval_provider: ApprovalProvider | None = None, audit_sink: AuditSink | None = None, max_turns: int = 20) -> AgentRunner:
    """创建一个第 3 章 AgentRunner。

    `command_runner or PowerShellRunner()` 表示：调用者传了 Fake 就用 Fake，
    没传时才创建真实 PowerShellRunner。这就是最简单的依赖注入。
    """
    # `is` 比较对象身份，不是字段值。这样调用方不能 new 一个内容相同的 DTO
    # 冒充固定章节配置，Java 中相当于只接受预定义的单例常量。
    if profile is not P01 and profile is not P02 and profile is not P03:
        raise ValueError("必须传入固定的章节配置对象")
    command = command_runner or PowerShellRunner()
    tools = (
        create_chapter_one_tools(command)
        if profile.chapter == 1
        else create_chapter_two_tools(command, file_system or LocalWorkspaceFileSystem())
    )
    policy = None
    if profile is P03:
        if approval_provider is None:
            raise ValueError("第三章必须提供 approval_provider")
        if audit_sink is None:
            raise ValueError("第三章必须提供 audit_sink")
        policy = PermissionPolicy(
            rules=(
                PermissionRule(
                    "confirm-file-write",
                    "ask",
                    "第三章的文件写入需要明确审批",
                    lambda request: request.prepared.definition is not None
                    and request.prepared.definition.name in {"write_file", "edit_file"},
                ),
            ),
            approval=approval_provider,
            audit=audit_sink,
            write_boundary=file_system or LocalWorkspaceFileSystem(),
        )
    return AgentRunner(model, tools, SYSTEM_PROMPT, workspace, max_turns=max_turns, authorizer=authorizer, permission_policy=policy)
