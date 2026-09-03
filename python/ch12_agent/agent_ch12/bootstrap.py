"""组合根：按固定 Profile 装配第 1 到第 12 章累计能力。

这是什么：Agent 的依赖注入和组装模块
Java 类比：类似 Spring 的 @Configuration 类，负责对象创建和依赖装配
为什么需要：集中管理对象创建逻辑，支持测试时注入 Fake 依赖
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
from .core.profiles import (
    P01,
    P02,
    P03,
    P04,
    P05,
    P06,
    P07,
    P08,
    P09,
    P10,
    P11,
    P12,
    ChapterProfile,
)
from .core.tools import ToolRegistry
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools
from .features.compaction import CompactionManager, ModelHistorySummarizer
from .features.memory import MemorySession, MemoryStore, ModelMemoryQueries
from .features.prompting import DynamicPromptProvider, DynamicPromptRenderer
from .features.recovery import RecoveryConfig, RecoveryManager
from .features.skills import SkillRegistry
from .features.subagents import SubagentTool
from .features.tasks import TaskStore, register_task_tools
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
    recovery_config: RecoveryConfig | None = None,
    task_store: TaskStore | None = None,
) -> AgentRunner:
    """创建固定章节 Agent，并拒绝能力越级注入。

    这是什么：Agent 的工厂函数，根据 Profile 装配对应章节的能力
    Java 类比：类似 @Bean 方法，根据配置创建并装配 AgentRunner
    为什么需要：按章节渐进式累加能力，防止低章节注入高章节才有的依赖

    参数：
        profile: 章节配置对象 (P01~P12)
        model: 模型客户端
        workspace: 工作区根目录
        command_runner: 命令执行器，None 时使用 PowerShellRunner
        file_system: 文件系统，None 时使用 LocalWorkspaceFileSystem
        authorizer: 工具授权器，用于权限控制
        approval_provider: 审批提供者，用于交互式权限确认
        audit_sink: 审计日志接收器
        hooks: Hook 注册表，P04 及以上章节支持
        max_turns: 最大工具轮次限制
        subagent_model_factory: 子 Agent 模型工厂，P06 及以上章节支持
        recovery_config: 恢复策略配置，P11 及以上章节支持
        task_store: 任务存储，P12 支持

    返回：
        AgentRunner: 装配完成的 Agent 运行器
    """
    if (
        profile is not P01
        and profile is not P02
        and profile is not P03
        and profile is not P04
        and profile is not P05
        and profile is not P06
        and profile is not P07
        and profile is not P08
        and profile is not P09
        and profile is not P10
        and profile is not P11
        and profile is not P12
    ):
        raise ValueError("必须传入固定的章节配置对象")
    if hooks is not None and profile not in (P04, P05, P06, P07, P08, P09, P10, P11, P12):
        raise ValueError("Hook 需要第四章或更高章节")
    if recovery_config is not None and "recovery" not in profile.capabilities:
        raise ValueError("recovery_config 需要第十一章或更高章节")
    if "recovery" in profile.capabilities and recovery_config is None:
        raise ValueError("第十一章及以后必须提供 recovery_config")
    if "task_dag_json" in profile.capabilities and task_store is None:
        raise ValueError("第十二章及以后必须提供 task_store")
    if "task_dag_json" not in profile.capabilities and task_store is not None:
        raise ValueError("task_store 需要第十二章或更高章节")
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()
    tools = (
        create_chapter_one_tools(command)
        if profile is P01
        else create_chapter_two_tools(command, actual_file_system)
    )
    policy: PermissionPolicy | None = None
    if profile in (P03, P04, P05, P06, P07, P08, P09, P10, P11, P12):
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
    compaction_manager = (
        CompactionManager(workspace, ModelHistorySummarizer(model))
        if "compaction" in profile.capabilities
        else None
    )
    recovery_manager = None
    if recovery_config is not None:
        if compaction_manager is None:
            raise ValueError("recovery capability 依赖 compaction")
        recovery_manager = RecoveryManager(model, compaction_manager, recovery_config)
    # 第九章把记忆实现成生命周期组件，而不是普通 Tool。这样模型只能通过
    # 无工具 side-query 建议“选什么、记什么”，不能直接写 .memory 文件。
    memory_session: MemorySession | None = None
    if "memory" in profile.capabilities:
        memory_queries = ModelMemoryQueries(model)
        memory_session = MemorySession(
            MemoryStore(workspace),
            selector=memory_queries,
            extractor=memory_queries,
            consolidator=memory_queries,
            emit_context_messages="dynamic_prompt" not in profile.capabilities,
        )
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
            if task_store is not None:
                # 子 Agent 与父 Agent 共享同一个 Repository，看到同一张项目任务图。
                register_task_tools(child_tools, task_store)
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
        if "dynamic_prompt" not in profile.capabilities:
            prompt += "\n当前 workspace 可用的 Skill 目录（需要时调用 load_skill 加载正文）：\n"
            prompt += catalog if catalog else "(当前 workspace 没有可用的 Skill。)"
        tools.register(skill_registry.tool_definition)
    if task_store is not None:
        # 五个 Task 工具最后追加，P11 的工具列表保持完整前缀。
        register_task_tools(tools, task_store)
    system_prompt_provider = (
        DynamicPromptProvider(
            DynamicPromptRenderer(),
            identity=prompt,
            tools=tools,
            workspace=workspace,
            context={"chapter": profile.chapter, "identity": "user"},
            skills=skill_registry,
            memory=memory_session,
        )
        if "dynamic_prompt" in profile.capabilities
        else None
    )
    return AgentRunner(
        model,
        tools,
        prompt,
        workspace,
        system_prompt_provider=system_prompt_provider,
        model_request_executor=recovery_manager,
        max_turns=max_turns,
        authorizer=authorizer,
        permission_policy=policy,
        hooks=actual_hooks if "hooks" in profile.capabilities else None,
        tool_round_observer=todo_tracker,
        history_processor=compaction_manager,
        tool_result_processor=compaction_manager,
        turn_lifecycle=memory_session,
    )
