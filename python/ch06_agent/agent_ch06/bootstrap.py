"""组合根：按固定 Profile 装配第 1 到第 6 章累计能力。

Java 对照：这相当于 Spring `@Configuration`。它创建真实适配器、工具注册表、
权限策略和 Hook 注册表，但不把业务流程写在对象创建代码里。
"""

from collections.abc import Callable

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.filesystem import WorkspaceFileSystem
from .core.hooks import HookRegistry
from .core.loop import AgentRunner, ToolAuthorizer
from .core.model import ModelClient
from .core.permissions import ApprovalProvider, AuditSink, PermissionPolicy, PermissionRule
from .core.profiles import P01, P02, P03, P04, P05, P06, ChapterProfile
from .core.tools import ToolRegistry
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools
from .features.subagents import SubagentTool
from .features.todos import TodoTracker

SYSTEM_PROMPT = (
    "You are a coding agent. Use tools when needed, inspect their results, and answer accurately."
)


def build_agent(
    profile: ChapterProfile,
    model: ModelClient,
    workspace: str,
    command_runner: CommandRunner | None = None,
    file_system: WorkspaceFileSystem | None = None,
    authorizer: ToolAuthorizer | None = None,
    approval_provider: ApprovalProvider | None = None,
    audit_sink: AuditSink | None = None,
    hooks: HookRegistry | None = None,
    max_turns: int = 20,
    subagent_model_factory: Callable[[], ModelClient] | None = None,
) -> AgentRunner:
    """创建固定章节 Agent，并拒绝能力越级注入。"""
    if (
        profile is not P01
        and profile is not P02
        and profile is not P03
        and profile is not P04
        and profile is not P05
        and profile is not P06
    ):
        raise ValueError("必须传入固定的章节配置对象")
    if hooks is not None and profile not in (P04, P05, P06):
        raise ValueError("Hook 需要第四章或更高章节")
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()
    tools = (
        create_chapter_one_tools(command)
        if profile is P01
        else create_chapter_two_tools(command, actual_file_system)
    )
    policy: PermissionPolicy | None = None
    if profile in (P03, P04, P05, P06):
        if approval_provider is None:
            raise ValueError("第三章及以后必须提供 approval_provider")
        if audit_sink is None:
            raise ValueError("第三章及以后必须提供 audit_sink")
        policy = PermissionPolicy(
            rules=(
                PermissionRule(
                    "confirm-file-write",
                    "ask",
                    "第三章及以后的文件写入需要明确审批",
                    lambda request: (
                        request.prepared.definition is not None
                        and request.prepared.definition.name in {"write_file", "edit_file"}
                    ),
                ),
            ),
            approval=approval_provider,
            audit=audit_sink,
            write_boundary=actual_file_system,
        )
    todo_tracker = TodoTracker() if "todo" in profile.capabilities else None
    if todo_tracker is not None:
        tools.register(todo_tracker.tool_definition)
    actual_hooks = hooks or HookRegistry()
    if "subagent" in profile.capabilities:
        if policy is None:
            raise ValueError("subagent capability 需要权限策略")

        def child_tools_factory() -> tuple[ToolRegistry, TodoTracker]:
            """为每个子 Agent 创建独立工具表和独立 TODO 状态。"""
            child_tools = create_chapter_two_tools(command, actual_file_system)
            child_todo = TodoTracker()
            child_tools.register(child_todo.tool_definition)
            return child_tools, child_todo

        subagent = SubagentTool(
            subagent_model_factory or (lambda: model),
            child_tools_factory,
            actual_hooks,
            policy,
        )
        tools.register(subagent.tool_definition)
    prompt = SYSTEM_PROMPT
    if todo_tracker is not None:
        prompt += "\n复杂任务请调用 todo_write 提交完整任务快照，并在计划变化时更新。"
    return AgentRunner(
        model,
        tools,
        prompt,
        workspace,
        max_turns=max_turns,
        authorizer=authorizer,
        permission_policy=policy,
        hooks=actual_hooks if "hooks" in profile.capabilities else None,
        tool_round_observer=todo_tracker,
    )
