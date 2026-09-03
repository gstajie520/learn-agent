"""组合根：按固定 Profile 装配第 1 到第 7 章累计能力。

这是什么：
    应用的组合根（Composition Root），负责创建和装配所有依赖对象。

Java 类比：
    类似 Spring 的 @Configuration 类，定义 Bean 的创建和依赖注入逻辑。

为什么需要：
    - 集中管理依赖注入，避免业务代码直接创建适配器
    - 按章节 Profile 控制能力装配，防止越级使用未学习的特性
    - 分离对象创建和业务逻辑，符合单一职责原则

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
from .core.profiles import P01, P02, P03, P04, P05, P06, P07, ChapterProfile
from .core.tools import ToolRegistry
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools
from .features.skills import SkillRegistry
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
    """创建固定章节 Agent，并拒绝能力越级注入。

    这是什么：
        根据章节 Profile 创建完整配置的 AgentRunner 的工厂方法。

    Java 类比：
        AgentRunner buildAgent(ChapterProfile profile, ...) 工厂方法
        类似 Spring 的 @Bean 方法，返回完全装配好的对象。

    为什么需要：
        - 按章节 Profile 控制能力白名单，防止第 2 章使用第 5 章的 TODO
        - 集中装配所有依赖（模型、工具、权限、Hook），保证配置正确性
        - 为测试提供统一的创建入口，便于注入 Fake 对象
        - 第 7 章新增：注册 SkillRegistry 和 load_skill 工具
    """
    if (
        profile is not P01
        and profile is not P02
        and profile is not P03
        and profile is not P04
        and profile is not P05
        and profile is not P06
        and profile is not P07
    ):
        raise ValueError("必须传入固定的章节配置对象")
    if hooks is not None and profile not in (P04, P05, P06, P07):
        raise ValueError("Hook 需要第四章或更高章节")
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()
    tools = (
        create_chapter_one_tools(command)
        if profile is P01
        else create_chapter_two_tools(command, actual_file_system)
    )
    policy: PermissionPolicy | None = None
    if profile in (P03, P04, P05, P06, P07):
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
    skill_registry = SkillRegistry.scan(workspace) if "skills" in profile.capabilities else None
    if "subagent" in profile.capabilities:
        if policy is None:
            raise ValueError("subagent capability 需要权限策略")

        def child_tools_factory() -> tuple[ToolRegistry, TodoTracker]:
            """为每个子 Agent 创建独立工具表和独立 TODO 状态。"""
            child_tools = create_chapter_two_tools(command, actual_file_system)
            child_todo = TodoTracker()
            child_tools.register(child_todo.tool_definition)
            if skill_registry is not None:
                child_tools.register(skill_registry.tool_definition)
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
    if skill_registry is not None:
        catalog = skill_registry.render_catalog()
        prompt += "\n当前 workspace 可用的 Skill 目录（需要时调用 load_skill 加载正文）：\n"
        prompt += catalog if catalog else "(当前 workspace 没有可用的 Skill。)"
        tools.register(skill_registry.tool_definition)
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
