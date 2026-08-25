"""组合根：按固定 Profile 装配第 1 到第 11 章累计能力。

Java 对照：这相当于 Spring `@Configuration`。它创建真实适配器、工具注册表、
权限策略和 Hook 注册表，但不把业务流程写在对象创建代码里。
"""

from collections.abc import Callable
from typing import cast

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.events import EventInbox
from .core.filesystem import WorkspaceFileSystem
from .core.hooks import HookRegistry
from .core.loop import AgentRunner, ToolAuthorizer
from .core.model import ModelClient
from .core.permissions import ApprovalProvider, AuditSink, PermissionPolicy, PermissionRule
from .core.profiles import ChapterProfile, profile_for_chapter
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
from .features.mcp_tools import McpRuntime
from .features.memory import MemorySession, MemoryStore, ModelMemoryQueries
from .features.prompting import DynamicPromptProvider, DynamicPromptRenderer
from .features.protocol import ProtocolRuntime
from .features.recovery import RecoveryConfig, RecoveryManager
from .features.skills import SkillRegistry
from .features.subagents import SubagentTool
from .features.tasks import TaskStore, register_task_tools
from .features.teammates import TeammateRuntime
from .features.todos import TodoTracker
from .features.work_stealing import (
    LeasedTaskStore,
    WorkStealingRuntime,
    register_leased_task_tools,
    register_teammate_leased_task_tools,
)
from .features.worktrees import WorktreeRuntime

SYSTEM_PROMPT = (
    "You are a coding agent. Use tools when needed, inspect their results, and answer accurately."
)


def _full_harness_runtime_status(
    background_supervisor: JobSupervisor | None,
    cron_runtime: CronRuntime | None,
    teammate_runtime: TeammateRuntime | None,
    mcp_runtime: McpRuntime | None,
) -> dict[str, object]:
    """汇总 P20 需要让模型看见的两项运行态：MCP 已连接 alias 与是否仍有异步工作。

    这里只读取同步属性，不 await 后台任务，也不向远端发请求：Prompt 渲染发生在
    每次模型请求前，任何阻塞都会拖慢整个回合。

    Java 对照：类似一个只读 `StatusDto`，由 `@Configuration` 捕获运行时 bean 引用后按需计算，
    而不是把可变状态直接暴露给上层。

    注意：这份 JSON 只是给模型的决策提示，不是授权依据。真正的边界仍在
    `PermissionPolicy`、计划门控和 `McpToolPolicy`。
    """
    # 三个运行时任一还有未完成工作就算 pending；用 `is not None and ...` 而不是
    # Java 的 `?.` 空安全调用，Python 需要显式判空。
    pending_work = (
        (background_supervisor is not None and background_supervisor.has_pending_work)
        or (cron_runtime is not None and cron_runtime.has_pending_work)
        or (teammate_runtime is not None and teammate_runtime.has_pending_work)
    )
    connections: tuple[str, ...] = (
        () if mcp_runtime is None else tuple(mcp_runtime.connected_aliases)
    )
    return {"mcp_connections": connections, "pending_work": pending_work}


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
    task_store: TaskStore | LeasedTaskStore | None = None,
    background_store: BackgroundJobStore | None = None,
    background_supervisor: JobSupervisor | None = None,
    cron_runtime: CronRuntime | None = None,
    mailbox_store: MailboxStore | None = None,
    teammate_runtime: TeammateRuntime | None = None,
    protocol_runtime: ProtocolRuntime | None = None,
    work_stealing_runtime: WorkStealingRuntime | None = None,
    worktree_runtime: WorktreeRuntime | None = None,
    mcp_runtime: McpRuntime | None = None,
) -> AgentRunner:
    """创建固定章节 Agent，并拒绝能力越级注入。"""
    # 只接受模块内固定单例。用 profile_for_chapter 反查后比较对象身份，
    # 调用方就不能临时构造一个同字段 ChapterProfile 来冒充正式章节。
    # Java 对照：类似只接受 enum 常量，而不接受 new 出来的等值对象。
    if profile_for_chapter(profile.chapter) is not profile:
        raise ValueError("必须传入固定的章节配置对象")
    # 以下全部改用 capability 判断而不是列举章节对象：
    # 每新增一章只需在 profiles.py 追加增量，组合根不必再改一遍长长的章节元组。
    if hooks is not None and "hooks" not in profile.capabilities:
        raise ValueError("Hook 需要第四章或更高章节")
    if recovery_config is not None and "recovery" not in profile.capabilities:
        raise ValueError("recovery_config 需要第十一章或更高章节")
    if "recovery" in profile.capabilities and recovery_config is None:
        raise ValueError("第十一章及以后必须提供 recovery_config")
    if "task_dag_json" in profile.capabilities and task_store is None:
        raise ValueError("第十二章及以后必须提供 task_store")
    if "task_dag_json" not in profile.capabilities and task_store is not None:
        raise ValueError("task_store 需要第十二章或更高章节")
    # 以下全部改用 capability 判断而不是逐个列出 profile 单例：P20 是 P19 的严格超集，
    # 只要能力集合包含对应标记，同一段共享关系校验就自动对 P20 生效。
    if "work_stealing" in profile.capabilities and work_stealing_runtime is None:
        raise ValueError("第十七章及以后必须提供 work_stealing_runtime")
    if "work_stealing" not in profile.capabilities and work_stealing_runtime is not None:
        raise ValueError("work_stealing_runtime 只适用于第十七章及以后")
    if "task_dag_sqlite" in profile.capabilities:
        if task_store is None or work_stealing_runtime is None:
            raise ValueError("第十七章及以后必须提供 SQLite task_store 和 work_stealing_runtime")
        if task_store is not work_stealing_runtime.store:
            raise ValueError("第十七章及以后 task_store 必须和 work_stealing_runtime 共享同一实例")
    if "worktree" in profile.capabilities:
        if worktree_runtime is None:
            raise ValueError("第十八章及以后必须提供 worktree_runtime")
        if task_store is not worktree_runtime.store:
            raise ValueError("第十八章及以后 worktree_runtime 必须和 task_store 共享同一实例")
        if (
            work_stealing_runtime is None
            or work_stealing_runtime.claim_service is not worktree_runtime
        ):
            raise ValueError("第十八章及以后 work_stealing_runtime 必须使用同一个 worktree_runtime")
    elif worktree_runtime is not None:
        raise ValueError("worktree_runtime 只适用于第十八章及以后")
    if "mcp" in profile.capabilities and mcp_runtime is None:
        raise ValueError("第十九章及以后必须提供 mcp_runtime")
    if "mcp" not in profile.capabilities and mcp_runtime is not None:
        raise ValueError("mcp_runtime 只适用于第十九章及以后")
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()
    tools = (
        create_chapter_one_tools(command, background="background" in profile.capabilities)
        # 第一章还没有文件工具，因此按章节号而不是 capability 区分基础工具表。
        if profile.chapter == 1
        else create_chapter_two_tools(
            command, actual_file_system, background="background" in profile.capabilities
        )
    )
    policy: PermissionPolicy | None = None
    if "policy" in profile.capabilities:
        if approval_provider is None:
            raise ValueError("第三章及以后必须提供 approval_provider")
        if audit_sink is None:
            raise ValueError("第三章及以后必须提供 audit_sink")
        permission_rules = [
                PermissionRule(
                    "confirm-file-write",
                    "ask",
                    "第三章及以后的文件写入需要明确审批",
                    lambda request: (
                        request.prepared.definition is not None
                        and request.prepared.definition.name in {"write_file", "edit_file"}
                    ),
                ),
        ]
        if "mcp" in profile.capabilities:
            permission_rules.append(
                PermissionRule(
                    "confirm-external-tool",
                    "ask",
                    "第十九章及以后外部 MCP 连接和 external 工具需要明确审批",
                    lambda request: (
                        request.prepared.definition is not None
                        and request.prepared.definition.effect == "external"
                    ),
                ),
            )
        policy = PermissionPolicy(
            rules=tuple(permission_rules),
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
            if work_stealing_runtime is not None:
                register_leased_task_tools(
                    child_tools, work_stealing_runtime.store, work_stealing_runtime.claim_service
                )
            elif task_store is not None:
                # 子 Agent 与父 Agent 共享同一个 Repository，看到同一张项目任务图。
                register_task_tools(child_tools, cast(TaskStore, task_store))
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
    if work_stealing_runtime is not None:
        register_leased_task_tools(
            tools, work_stealing_runtime.store, work_stealing_runtime.claim_service
        )
    if worktree_runtime is not None:
        for definition in worktree_runtime.lead_tool_definitions:
            tools.register(definition)
    elif "task_dag_sqlite" not in profile.capabilities and task_store is not None:
        # 五个 Task 工具最后追加，P11 的工具列表保持完整前缀。
        register_task_tools(tools, cast(TaskStore, task_store))
    if mcp_runtime is not None:
        # 管理工具只进入 Lead registry；远程工具在 connect 成功后由 runtime 动态发布。
        mcp_runtime.install(tools)
    background_dispatcher = None
    if "background" in profile.capabilities:
        if background_supervisor is None:
            if background_store is None:
                raise ValueError("第十三章必须提供 background_store")
            background_supervisor = JobSupervisor(background_store, EventInbox())
        # 只要存在 supervisor 就注入 Dispatcher；同步章节仍直接调用 ToolRegistry，
        # 因此权限与 Hook 的执行顺序不变。
        background_dispatcher = BackgroundDispatcher(background_supervisor)
        # query/cancel 两个后台工具只属于 P13 的教学工具面；P14 起改由 typed event 通知，
        # 因此后续章节的 Lead 工具列表不再包含它们。
        if "cron" not in profile.capabilities:
            register_background_job_tools(tools, background_supervisor)
    if "cron" in profile.capabilities:
        if background_supervisor is None or cron_runtime is None:
            raise ValueError("第十四章必须提供共享 background_supervisor 和 cron_runtime")
        if (
            cron_runtime.supervisor is not background_supervisor
            or cron_runtime.event_inbox is not background_supervisor.inbox
        ):
            raise ValueError("cron_runtime 必须共享 background_supervisor 和 EventInbox")
        tools.register(cron_runtime.tool_definition)
    if "teammate" in profile.capabilities:
        if mailbox_store is None or teammate_runtime is None:
            raise ValueError("第十五章必须提供 mailbox_store 和 teammate_runtime")
        if teammate_runtime.store is not mailbox_store:
            raise ValueError("teammate_runtime 必须共享 mailbox_store")
        tools.register(teammate_runtime.spawn_tool_definition)
        tools.register(teammate_runtime.send_tool_definition)
        teammate_policy = policy
        if "protocol" in profile.capabilities:
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
        if work_stealing_runtime is not None:
            teammate_runtime.configure_work_stealing(work_stealing_runtime)

        def teammate_factory(name: str, role: str, send_definition: object) -> AgentRunner:
            """创建只拥有 shell/read_file/write_file/send_message 的独立队友 Runner。"""
            teammate_tools = create_chapter_two_tools(command, actual_file_system)
            teammate_tools.register(send_definition)  # type: ignore[arg-type]
            if protocol_runtime is not None:
                teammate_tools.register(protocol_runtime.submit_plan_tool_definition)
            if work_stealing_runtime is not None:
                register_teammate_leased_task_tools(
                    teammate_tools,
                    work_stealing_runtime.store,
                    work_stealing_runtime.claim_service,
                )
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
                tool_context_provider=worktree_runtime,
            )

        teammate_runtime.configure_runner_factory(teammate_factory)
    # P20 才安装运行态状态 Provider：lambda 捕获上面装配好的运行时引用，
    # 因此每轮渲染读到的都是当前状态，而不是构建期的快照。
    # Java 对照：类似把一个 `() -> buildStatus(beans)` 的 Supplier 注入渲染器。
    status_provider = (
        (
            lambda: _full_harness_runtime_status(
                background_supervisor, cron_runtime, teammate_runtime, mcp_runtime
            )
        )
        if "full_harness" in profile.capabilities
        else None
    )
    system_prompt_provider = (
        DynamicPromptProvider(
            DynamicPromptRenderer(),
            identity=prompt,
            tools=tools,
            workspace=workspace,
            context={"chapter": profile.chapter, "identity": "user"},
            skills=skill_registry,
            memory=memory_session,
            status_provider=status_provider,
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
            for item in (background_supervisor, cron_runtime, teammate_runtime, mcp_runtime)
            if item is not None
        ),
        tool_context_provider=worktree_runtime,
    )
