"""组合根：按固定 Profile 装配第 1 到第 4 章累计能力。

Java 对照：这相当于 Spring `@Configuration`。它创建真实适配器、工具注册表、
权限策略和 Hook 注册表，但不把业务流程写在对象创建代码里。
"""

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.filesystem import WorkspaceFileSystem
from .core.hooks import HookRegistry
from .core.loop import AgentRunner, ToolAuthorizer
from .core.model import ModelClient
from .core.permissions import ApprovalProvider, AuditSink, PermissionPolicy, PermissionRule
from .core.profiles import P01, P02, P03, P04, ChapterProfile
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools

SYSTEM_PROMPT = "You are a coding agent. Use tools when needed, inspect their results, and answer accurately."


def build_agent(profile: ChapterProfile, model: ModelClient, workspace: str, command_runner: CommandRunner | None = None, file_system: WorkspaceFileSystem | None = None, authorizer: ToolAuthorizer | None = None, approval_provider: ApprovalProvider | None = None, audit_sink: AuditSink | None = None, hooks: HookRegistry | None = None, max_turns: int = 20) -> AgentRunner:
    """创建固定章节 Agent，并拒绝能力越级注入。

    这是什么：Agent 的工厂方法，根据章节配置组装不同能力的 Agent
    Java 类比：类似 @Configuration 类中的 @Bean 方法，根据 profile 组装不同的依赖
    为什么需要：让各章节能力递进清晰可测，防止越级使用未讲解的能力（如第 1 章注入 Hook）
    """
    if profile is not P01 and profile is not P02 and profile is not P03 and profile is not P04:
        raise ValueError("必须传入固定的章节配置对象")
    if hooks is not None and profile is not P04:
        raise ValueError("Hook 需要第四章或更高章节")
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()
    tools = create_chapter_one_tools(command) if profile is P01 else create_chapter_two_tools(command, actual_file_system)
    policy: PermissionPolicy | None = None
    if profile is P03 or profile is P04:
        if approval_provider is None:
            raise ValueError("第三章及以后必须提供 approval_provider")
        if audit_sink is None:
            raise ValueError("第三章及以后必须提供 audit_sink")
        policy = PermissionPolicy(
            rules=(PermissionRule("confirm-file-write", "ask", "第三章及以后的文件写入需要明确审批", lambda request: request.prepared.definition is not None and request.prepared.definition.name in {"write_file", "edit_file"}),),
            approval=approval_provider,
            audit=audit_sink,
            write_boundary=actual_file_system,
        )
    return AgentRunner(model, tools, SYSTEM_PROMPT, workspace, max_turns=max_turns, authorizer=authorizer, permission_policy=policy, hooks=hooks)
