"""组合根：按固定 Profile 装配第 1 到第 5 章累计能力。

Java 对照：这相当于 Spring `@Configuration` 类。它创建真实适配器、工具注册表、
权限策略和 Hook 注册表，但不把业务流程写在对象创建代码里。

这是什么：依赖注入的组合根，负责组装所有组件
为什么需要：集中管理依赖关系，确保章节能力严格按白名单装配
"""

from .adapters.filesystem import LocalWorkspaceFileSystem
from .adapters.powershell import PowerShellRunner
from .core.commands import CommandRunner
from .core.filesystem import WorkspaceFileSystem
from .core.hooks import HookRegistry
from .core.loop import AgentRunner, ToolAuthorizer
from .core.model import ModelClient
from .core.permissions import ApprovalProvider, AuditSink, PermissionPolicy, PermissionRule
from .core.profiles import P01, P02, P03, P04, P05, ChapterProfile
from .features.builtin_tools import create_chapter_one_tools, create_chapter_two_tools
from .features.todos import TodoTracker

# 所有章节共享的基础系统提示词
SYSTEM_PROMPT = "You are a coding agent. Use tools when needed, inspect their results, and answer accurately."


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
) -> AgentRunner:
    """创建固定章节 Agent，并拒绝能力越级注入。

    这是什么：Agent 的工厂方法，根据章节配置装配对应能力
    Java 类比：public static AgentRunner buildAgent(ChapterProfile profile, ...)
    为什么需要：防止越级使用未学功能，确保教程循序渐进

    参数：
        profile: 章节能力配置对象（必须是 P01-P05 之一）
        model: 模型客户端实现
        workspace: Agent 工作目录
        command_runner: 可选的命令执行器（默认 PowerShell）
        file_system: 可选的文件系统适配器
        authorizer: 旧版授权器（兼容第 1 章）
        approval_provider: 权限审批接口（第 3 章起必需）
        audit_sink: 审计日志接口（第 3 章起必需）
        hooks: Hook 注册表（第 4 章起可用）
        max_turns: 最大模型调用轮数

    返回：
        AgentRunner: 装配完成的 Agent 实例

    异常：
        ValueError: 章节配置非法或能力越级注入
    """
    # 必须传入模块预定义的章节单例，防止伪造配置对象
    if profile is not P01 and profile is not P02 and profile is not P03 and profile is not P04 and profile is not P05:
        raise ValueError("必须传入固定的章节配置对象")

    # Hook 只在第 4 章及以后可用，提前使用会报错
    if hooks is not None and profile is not P04 and profile is not P05:
        raise ValueError("Hook 需要第四章或更高章节")

    # 默认适配器：PowerShell 命令执行器和本地文件系统
    command = command_runner or PowerShellRunner()
    actual_file_system = file_system or LocalWorkspaceFileSystem()

    # 第 1 章只有 shell 工具，第 2 章起加入文件工具
    tools = (
        create_chapter_one_tools(command)
        if profile is P01
        else create_chapter_two_tools(command, actual_file_system)
    )

    # 第 3 章起需要权限策略，必须提供审批和审计接口
    policy: PermissionPolicy | None = None
    if profile is P03 or profile is P04 or profile is P05:
        if approval_provider is None:
            raise ValueError("第三章及以后必须提供 approval_provider")
        if audit_sink is None:
            raise ValueError("第三章及以后必须提供 audit_sink")

        # 创建权限策略：文件写入需要审批
        policy = PermissionPolicy(
            rules=(
                PermissionRule(
                    "confirm-file-write",  # 规则名
                    "ask",  # 匹配时产生 ask 决策
                    "第三章及以后的文件写入需要明确审批",  # 原因说明
                    lambda request: (
                        request.prepared.definition is not None
                        and request.prepared.definition.name in {"write_file", "edit_file"}
                    ),  # 匹配条件：工具名是 write_file 或 edit_file
                ),
            ),
            approval=approval_provider,  # 审批接口
            audit=audit_sink,  # 审计接口
            write_boundary=actual_file_system,  # 文件路径边界检查
        )

    # 第 5 章加入 TODO 跟踪器（同时作为工具和观察器）
    todo_tracker = TodoTracker() if "todo" in profile.capabilities else None
    if todo_tracker is not None:
        tools.register(todo_tracker.tool_definition)  # 注册 todo_write 工具

    # 第 5 章的系统提示词需要告知 TODO 功能
    prompt = SYSTEM_PROMPT
    if todo_tracker is not None:
        prompt += "\n复杂任务请调用 todo_write 提交完整任务快照，并在计划变化时更新。"

    # 返回组装好的 Agent 实例
    return AgentRunner(
        model,
        tools,
        prompt,
        workspace,
        max_turns=max_turns,
        authorizer=authorizer,  # 旧版授权器（可选）
        permission_policy=policy,  # 第 3 章起的权限策略
        hooks=hooks,  # 第 4 章起的 Hook 注册表
        tool_round_observer=todo_tracker,  # 第 5 章的工具轮观察器
    )
