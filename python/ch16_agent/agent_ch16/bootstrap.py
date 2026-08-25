"""组合根：按固定 Profile 装配第 1 到第 11 章累计能力。

Java 对照：这相当于 Spring `@Configuration`。它创建真实适配器、工具注册表、
权限策略和 Hook 注册表，但不把业务流程写在对象创建代码里。
"""

from collections.abc import Callable

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.events import EventInbox
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
    P13,
    P14,
    P15,
    P16,
    ChapterProfile,
)
from .core.tools import ToolRegistry
from .features.background import (
    BackgroundDispatcher,
    BackgroundJobStore,
    JobSupervisor,
    register_background_job_tools,
)
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools
from .features.compaction import CompactionManager, ModelHistorySummarizer
from .features.cron import CronRuntime
from .features.mailbox import MailboxStore
from .features.memory import MemorySession, MemoryStore, ModelMemoryQueries
from .features.prompting import DynamicPromptProvider, DynamicPromptRenderer
from .features.protocol import ProtocolRuntime
from .features.recovery import RecoveryConfig, RecoveryManager
from .features.skills import SkillRegistry
from .features.subagents import SubagentTool
from .features.tasks import TaskStore, register_task_tools
from .features.teammates import TeammateRuntime
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
    background_store: BackgroundJobStore | None = None,
    background_supervisor: JobSupervisor | None = None,
    cron_runtime: CronRuntime | None = None,
    mailbox_store: MailboxStore | None = None,
    teammate_runtime: TeammateRuntime | None = None,
    protocol_runtime: ProtocolRuntime | None = None,
) -> AgentRunner:
    """创建固定章节 Agent，并拒绝能力越级注入。"""
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
        and profile is not P13
        and profile is not P14
        and profile is not P15
        and profile is not P16
    ):
        raise ValueError("必须传入固定的章节配置对象")
    if hooks is not None and profile not in (
        P04,
        P05,
        P06,
        P07,
        P08,
        P09,
        P10,
        P11,
        P12,
        P13,
        P14,
        P15,
        P16,
    ):
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
        create_chapter_one_tools(command, background="background" in profile.capabilities)
        if profile is P01
        else create_chapter_two_tools(
            command, actual_file_system, background="background" in profile.capabilities
        )
    )
    policy: PermissionPolicy | None = None
    if profile in (P03, P04, P05, P06, P07, P08, P09, P10, P11, P12, P13, P14, P15, P16):
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
    background_dispatcher = None
    if profile is P13:
        if background_supervisor is None:
            if background_store is None:
                raise ValueError("第十三章必须提供 background_store")
            background_supervisor = JobSupervisor(background_store, EventInbox())
        background_dispatcher = BackgroundDispatcher(background_supervisor)
        register_background_job_tools(tools, background_supervisor)
    if profile in (P14, P15, P16):
        if background_supervisor is None or cron_runtime is None:
            raise ValueError("第十四章必须提供共享 background_supervisor 和 cron_runtime")
        if (
            cron_runtime.supervisor is not background_supervisor
            or cron_runtime.event_inbox is not background_supervisor.inbox
        ):
            raise ValueError("cron_runtime 必须共享 background_supervisor 和 EventInbox")
        tools.register(cron_runtime.tool_definition)
    if profile in (P15, P16):
        if mailbox_store is None or teammate_runtime is None:
            raise ValueError("第十五章必须提供 mailbox_store 和 teammate_runtime")
        if teammate_runtime.store is not mailbox_store:
            raise ValueError("teammate_runtime 必须共享 mailbox_store")
        tools.register(teammate_runtime.spawn_tool_definition)
        tools.register(teammate_runtime.send_tool_definition)
        teammate_policy = policy
        if profile is P16:
            if protocol_runtime is None:
                raise ValueError("第十六章必须提供 protocol_runtime")
            if (
                protocol_runtime.team is not teammate_runtime
                or protocol_runtime.team.mailbox_store is not mailbox_store
            ):
                raise ValueError("protocol_runtime 必须共享 teammate_runtime 和 mailbox_store")
            teammate_runtime.configure_protocol(protocol_runtime)
            for definition in protocol_runtime.lead_tool_definitions():
                tools.register(definition)
            teammate_policy = (
                policy.with_rules((protocol_runtime.plan_gate_rule,))
                if policy is not None
                else None
            )

        def teammate_factory(name: str, role: str, send_definition: object) -> AgentRunner:
            """创建只拥有 shell/read_file/write_file/send_message 的独立队友 Runner。"""
            teammate_tools = create_chapter_two_tools(command, actual_file_system)
            teammate_tools.register(send_definition)  # type: ignore[arg-type]
            if protocol_runtime is not None:
                teammate_tools.register(protocol_runtime.submit_plan_tool_definition)
            teammate_compaction = (
                CompactionManager(workspace, ModelHistorySummarizer(model))
                if "compaction" in profile.capabilities
                else None
            )
            teammate_recovery = (
                RecoveryManager(model, teammate_compaction, recovery_config)
                if recovery_config is not None and teammate_compaction is not None
                else None
            )
            return AgentRunner(
                model,
                teammate_tools,
                f"You are {name}, serving as {role}.",
                workspace,
                model_request_executor=teammate_recovery,
                max_turns=max_turns,
                identity=name,
                permission_policy=teammate_policy,
                hooks=actual_hooks,
                history_processor=teammate_compaction,
                tool_result_processor=teammate_compaction,
            )

        teammate_runtime.configure_runner_factory(teammate_factory)
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
        tool_dispatcher=background_dispatcher,
        event_pump=teammate_runtime
        if teammate_runtime is not None
        else (cron_runtime if cron_runtime is not None else background_supervisor),
        resources=tuple(
            item
            for item in (background_supervisor, cron_runtime, teammate_runtime)
            if item is not None
        ),
    )
