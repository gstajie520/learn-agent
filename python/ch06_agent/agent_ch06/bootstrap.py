"""组合根：按固定 Profile 装配第 1 到第 6 章累计能力。

这是什么：应用程序的依赖注入配置类，根据章节选择组装不同能力
Java 类比：@Configuration class AgentConfiguration
为什么需要：集中管理依赖创建和能力启用，避免业务代码中硬编码对象创建逻辑

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
)  # 基础系统提示词，定义 Agent 的身份和行为准则


def build_agent(
    profile: ChapterProfile,  # 章节配置对象（P01~P06）
    model: ModelClient,  # 模型客户端
    workspace: str,  # 工作目录
    command_runner: CommandRunner | None = None,  # 可选命令执行器
    file_system: WorkspaceFileSystem | None = None,  # 可选文件系统
    authorizer: ToolAuthorizer | None = None,  # 可选旧版授权器
    approval_provider: ApprovalProvider | None = None,  # 第三章后必须：交互式审批
    audit_sink: AuditSink | None = None,  # 第三章后必须：审计日志
    hooks: HookRegistry | None = None,  # 第四章后可选：Hook 注册表
    max_turns: int = 20,  # 最大循环次数
    subagent_model_factory: Callable[[], ModelClient] | None = None,  # 子 Agent 模型工厂
) -> AgentRunner:
    """创建固定章节 Agent，并拒绝能力越级注入。

    这是什么：根据章节 Profile 组装 AgentRunner 的工厂方法
    Java 类比：@Bean public AgentRunner agentRunner(ChapterProfile profile, ...)
    为什么需要：确保每个章节只启用对应的能力，防止跨章节能力混用
    """
    # 校验章节 Profile 必须是预定义的常量
    if (
        profile is not P01
        and profile is not P02
        and profile is not P03
        and profile is not P04
        and profile is not P05
        and profile is not P06
    ):
        raise ValueError("必须传入固定的章节配置对象")
    if hooks is not None and profile not in (P04, P05, P06):  # Hook 是第四章引入的
        raise ValueError("Hook 需要第四章或更高章节")

    # 创建或使用默认的适配器
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()

    # 根据章节创建工具集：第一章只有命令工具，第二章加入文件工具
    tools = (
        create_chapter_one_tools(command)
        if profile is P01
        else create_chapter_two_tools(command, actual_file_system)
    )

    # 第三章及以后启用权限策略
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
            write_boundary=actual_file_system,  # 确保写入操作在工作目录内
        )

    # 第六章启用 TodoTracker
    todo_tracker = TodoTracker() if "todo" in profile.capabilities else None
    if todo_tracker is not None:
        tools.register(todo_tracker.tool_definition)  # 注册 todo_write 工具

    actual_hooks = hooks or HookRegistry()

    # 第五章启用子 Agent 能力
    if "subagent" in profile.capabilities:
        if policy is None:
            raise ValueError("subagent capability 需要权限策略")

        def child_tools_factory() -> tuple[ToolRegistry, TodoTracker]:
            """为每个子 Agent 创建独立工具表和独立 TODO 状态。

            这是什么：子 Agent 的工具工厂
            Java 类比：Supplier<ToolRegistry> childToolsSupplier
            为什么需要：每个子 Agent 有独立的状态，避免并发修改同一工具注册表
            """
            child_tools = create_chapter_two_tools(command, actual_file_system)
            child_todo = TodoTracker()
            child_tools.register(child_todo.tool_definition)
            return child_tools, child_todo

        subagent = SubagentTool(
            subagent_model_factory or (lambda: model),  # 默认使用父 Agent 的模型
            child_tools_factory,
            actual_hooks,
            policy,
        )
        tools.register(subagent.tool_definition)  # 注册 call_subagent 工具

    # 根据是否有 TODO 能力调整系统提示词
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
        hooks=actual_hooks if "hooks" in profile.capabilities else None,  # 第四章后启用
        tool_round_observer=todo_tracker,  # 第六章启用 TODO 观察器
    )
