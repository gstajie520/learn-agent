"""组合根：按固定 Profile 装配第 1 到第 9 章累计能力。

Java 对照：这相当于 Spring `@Configuration` 类。它创建真实适配器、工具注册表、
权限策略和 Hook 注册表，但不把业务流程写在对象创建代码里。

这是什么：Agent 的依赖注入容器，负责组装所有组件
Java 类比：类似 Spring 的 ApplicationContext 或带 @Bean 方法的 @Configuration
为什么需要：集中管理对象创建逻辑，让核心业务代码不依赖具体实现
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
from .core.profiles import P01, P02, P03, P04, P05, P06, P07, P08, P09, ChapterProfile
from .core.tools import ToolRegistry
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools
from .features.compaction import CompactionManager, ModelHistorySummarizer
from .features.memory import MemorySession, MemoryStore, ModelMemoryQueries
from .features.skills import SkillRegistry
from .features.subagents import SubagentTool
from .features.todos import TodoTracker

# 全局系统提示词：定义 Agent 的基础行为规范
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
    “””创建指定章节的 Agent，并拒绝能力越级注入。

    这是什么：Agent 工厂方法，根据章节配置组装不同能力的 Agent
    Java 类比：类似 Spring 的 @Bean 方法，根据 @Profile 激活不同配置
    为什么需要：每章渐进式增加能力，确保测试时不会意外引入未学习的功能

    参数：
        profile: 章节配置对象（P01~P09），决定启用哪些功能
        model: 模型客户端（OpenAI、DeepSeek 等）
        workspace: 工具允许操作的工作目录
        command_runner: 命令执行器（默认 PowerShell）
        file_system: 文件系统接口（默认本地文件系统）
        authorizer: 工具授权器（可选，用于权限控制）
        approval_provider: 审批提供者（第三章起必需）
        audit_sink: 审计日志接收器（第三章起必需）
        hooks: Hook 注册表（第四章起支持）
        max_turns: 最大循环次数（默认 20）
        subagent_model_factory: 子 Agent 模型工厂（子 Agent 功能需要）

    返回：
        AgentRunner: 配置完成的 Agent 运行器

    异常：
        ValueError: 配置不合法（如第二章传入 hooks）
    “””
    # 严格校验：只允许预定义的章节配置对象，防止传入自定义 Profile
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
    ):
        raise ValueError(“必须传入固定的章节配置对象”)

    # Hook 功能从第四章开始引入，提前注入会导致测试不匹配教学进度
    if hooks is not None and profile not in (P04, P05, P06, P07, P08, P09):
        raise ValueError(“Hook 需要第四章或更高章节”)

    # 依赖注入：优先使用传入的实现，否则使用默认实现
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()

    # 第一章只有命令工具，第二章起增加文件系统工具
    tools = (
        create_chapter_one_tools(command)
        if profile is P01
        else create_chapter_two_tools(command, actual_file_system)
    )

    # 第三章起引入权限策略，需要审批提供者和审计接收器
    policy: PermissionPolicy | None = None
    if profile in (P03, P04, P05, P06, P07, P08, P09):
        if approval_provider is None:
            raise ValueError(“第三章及以后必须提供 approval_provider”)
        if audit_sink is None:
            raise ValueError(“第三章及以后必须提供 audit_sink”)

        # 创建权限策略，拦截文件写入操作
        policy = PermissionPolicy(
            rules=(
                PermissionRule(
                    “confirm-file-write”,
                    “ask”,  # 需要用户明确审批
                    “第三章及以后的文件写入需要明确审批”,
                    lambda request: (
                        request.prepared.definition is not None
                        and request.prepared.definition.name in {“write_file”, “edit_file”}
                    ),
                ),
            ),
            approval=approval_provider,
            audit=audit_sink,
            write_boundary=actual_file_system,
        )

    # 第五章引入 TODO 跟踪功能
    todo_tracker = TodoTracker() if “todo” in profile.capabilities else None
    if todo_tracker is not None:
        tools.register(todo_tracker.tool_definition)

    actual_hooks = hooks or HookRegistry()

    # 第七章引入 Skill 按需加载功能
    skill_registry = SkillRegistry.scan(workspace) if “skills” in profile.capabilities else None

    # 第六章引入上下文压缩功能
    compaction_manager = (
        CompactionManager(workspace, ModelHistorySummarizer(model))
        if “compaction” in profile.capabilities
        else None
    )

    # 第九章引入记忆功能：作为生命周期组件而非普通工具
    # 模型只能通过 side-query 建议”选什么、记什么”，不能直接写 .memory 文件
    memory_session: MemorySession | None = None
    if “memory” in profile.capabilities:
        memory_queries = ModelMemoryQueries(model)
        memory_session = MemorySession(
            MemoryStore(workspace),
            selector=memory_queries,
            extractor=memory_queries,
            consolidator=memory_queries,
        )

    # 第八章引入子 Agent 功能
    if “subagent” in profile.capabilities:
        if policy is None:
            raise ValueError(“subagent capability 需要权限策略”)

        def child_tools_factory() -> tuple[ToolRegistry, TodoTracker]:
            “””为每个子 Agent 创建独立工具表和独立 TODO 状态。

            这是什么：子 Agent 的工具工厂方法
            Java 类比：类似 Spring 的 @Scope(“prototype”) Bean
            为什么需要：每个子 Agent 有独立的工具状态，避免相互干扰
            “””
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

    # 动态扩展系统提示词：根据启用的功能添加使用说明
    prompt = SYSTEM_PROMPT
    if todo_tracker is not None:
        prompt += “\n复杂任务请调用 todo_write 提交完整任务快照，并在计划变化时更新。”

    if skill_registry is not None:
        catalog = skill_registry.render_catalog()
        prompt += “\n当前 workspace 可用的 Skill 目录（需要时调用 load_skill 加载正文）：\n”
        prompt += catalog if catalog else “(当前 workspace 没有可用的 Skill。)”
        tools.register(skill_registry.tool_definition)

    # 组装最终的 AgentRunner，注入所有依赖和生命周期组件
    return AgentRunner(
        model,
        tools,
        prompt,
        workspace,
        max_turns=max_turns,
        authorizer=authorizer,
        permission_policy=policy,
        hooks=actual_hooks if “hooks” in profile.capabilities else None,
        tool_round_observer=todo_tracker,  # TODO 跟踪器观察每轮工具调用
        history_processor=compaction_manager,  # 压缩管理器处理历史消息
        tool_result_processor=compaction_manager,  # 压缩管理器处理工具结果
        turn_lifecycle=memory_session,  # 记忆会话管理每轮生命周期
    )
