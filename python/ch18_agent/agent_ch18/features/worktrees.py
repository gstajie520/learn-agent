"""第十八章受控 Git Worktree 领域模型与运行时。

Java/Spring 对照：

* ``WorktreeBinding`` 类似不可变 Java ``record``，保存任务和工作树的当前绑定。
* ``WorktreeStore`` 类似 Repository interface，SQLite Adapter 负责事务和审计。
* ``WorktreeRuntime`` 类似领域 Service，同时实现任务认领和工具上下文解析。
* ``resolve`` 类似请求拦截器：在每次工具真正执行前，把主目录切换到可信 Worktree。

本章最重要的原则是“无法证明安全，就不删除”。Git stderr 只留在适配器边界，
给模型和学习者的错误使用稳定中文说明，协议状态值和错误码仍保留英文。
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ..adapters.git import GitCommandResult, GitExecutionError, SubprocessGitRunner
from ..core.tools import ToolContext, ToolDefinition, ToolResult, tool_error, tool_success
from .mailbox import canonical_agent_name
from .tasks import CANONICAL_UUID, TaskCompletion, TaskError, canonical_task_id
from .work_stealing import (
    LeasedTaskStore,
    TaskClaim,
    TaskClaimService,
    canonical_claim_token,
)

_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_STATUSES = frozenset({"reserved", "active", "kept", "needs_review", "removed"})
_ACTIONS = frozenset({"reserve", "create", "keep", "needs_review", "remove"})
_ACTION_STATUS = {
    "reserve": "reserved",
    "create": "active",
    "keep": "kept",
    "needs_review": "needs_review",
    "remove": "removed",
}


class WorktreeError(TaskError):
    """所有 Worktree 领域异常的父类。

    这是什么：Worktree 领域的基础异常类
    Java 类比：类似自定义的 WorktreeDomainException extends BusinessException
    为什么需要：统一 Worktree 相关异常的类型层次，便于调用方精确捕获
    """


class WorktreeRepositoryError(WorktreeError):
    """workspace 不是可受控的 Git 主仓库根。

    这是什么：仓库前置条件不满足的异常
    Java 类比：类似 InvalidRepositoryException
    为什么需要：Worktree 只能在真实 Git 仓库根目录创建，提前校验避免后续混乱
    """

    def __init__(self, message: str) -> None:
        super().__init__("worktree_repository_error", message)


class WorktreeStateError(WorktreeError):
    """Task 或 Binding 当前状态不允许目标操作。

    这是什么：状态机转换非法的异常
    Java 类比：类似 InvalidStateTransitionException
    为什么需要：状态机有明确的转换规则，违反规则应该显式失败
    """

    def __init__(self, message: str) -> None:
        super().__init__("worktree_invalid_state", message)


class WorktreeGitError(WorktreeError):
    """Git 已运行，但结果没有满足领域约束。

    这是什么：Git 命令执行后业务校验失败的异常
    Java 类比：类似 GitConstraintViolationException
    为什么需要：Git 返回了结果（退出码可能为 0），但内容不符合业务要求
    """

    def __init__(self, message: str) -> None:
        super().__init__("worktree_git_error", message)


class WorktreeContextError(WorktreeError):
    """claim token、执行身份或工作目录上下文不可信。

    这是什么：上下文校验失败的安全异常
    Java 类比：类似 InvalidContextException 或 SecurityException
    为什么需要：防止 token 失效后继续使用，或身份不匹配时路由错误
    """

    def __init__(self, message: str) -> None:
        super().__init__("worktree_context_error", message)


@dataclass(frozen=True, slots=True)
class WorktreeBinding:
    """任务和受管 Worktree 的当前状态快照。

    这是什么：Worktree 的不可变状态记录
    Java 类比：record WorktreeBinding(String taskId, String name, ...)
    为什么需要：状态变化由 Repository 生成新快照，确保审计事件和状态迁移原子性

    字段说明（路径和分支由领域规则固定，不能让模型传入）：
        task_id: 被隔离执行的 Task UUID
        name: 受管名称（同时决定分支名和目录名）
        branch: 固定为 wt/{name}，防止模型传入任意分支
        relative_path: 固定为 .agent_tutorial/worktrees/{name}
        integration_ref: 最终结果应合入的 refs/heads/... 引用
        baseline_commit: 创建 Worktree 时解析得到的基线提交（40/64位十六进制）
        branch_tip: 已验证的 Worktree HEAD；reserved 阶段为空
        status: 状态机五态（reserved/active/kept/needs_review/removed）
        review_reason: needs_review 时给人工看的稳定原因
        created_at_utc: 首次预留时间（UTC 时区）
        updated_at_utc: 最近一次状态迁移时间（UTC 时区）
    """

    task_id: str              # 被隔离执行的 Task UUID
    name: str                 # 受管名称，同时决定分支名和目录名
    branch: str               # 固定为 wt/{name}，不能让模型传任意分支
    relative_path: str        # 固定为 .agent_tutorial/worktrees/{name}
    integration_ref: str      # 最终结果应合入的 refs/heads/... 引用
    baseline_commit: str      # 创建 Worktree 时解析得到的基线提交
    branch_tip: str | None    # 已验证的 Worktree HEAD；reserved 阶段为空
    status: str               # reserved/active/kept/needs_review/removed
    review_reason: str | None # needs_review 时给人工看的稳定原因
    created_at_utc: datetime  # 首次预留时间
    updated_at_utc: datetime  # 最近一次状态迁移时间

    def __post_init__(self) -> None:
        """集中校验字段组合，防止非法快照进入 SQLite。

        这是什么：不可变对象的构造后校验
        Java 类比：record 的 compact constructor 或 @PostConstruct 校验
        为什么需要：确保每个 Binding 实例都满足业务不变式，而非依赖调用方记得校验
        """
        # 规范化并校验 UUID 格式
        task_id = canonical_task_id(self.task_id)
        name = canonical_agent_name(self.name)

        # 关键：防止路径注入攻击，分支和路径必须遵守固定规则
        if self.branch != f"wt/{name}":
            raise WorktreeStateError("Worktree 分支必须与受管名称一致")
        if self.relative_path != f".agent_tutorial/worktrees/{name}":
            raise WorktreeStateError("Worktree 路径必须与受管名称一致")

        # 状态机校验：只允许五个预定义状态
        if self.status not in _STATUSES:
            raise WorktreeStateError("Worktree status 无效")

        # 业务规则：needs_review 必须有原因，其他状态不能有原因
        reason = _normalize_reason(self.review_reason)
        if (self.status == "needs_review") != (reason is not None):
            raise WorktreeStateError("review_reason 与 Worktree status 不匹配")

        # 时间一致性校验：updated 不能早于 created
        created = _utc_time(self.created_at_utc, "创建时间")
        updated = _utc_time(self.updated_at_utc, "更新时间")
        if updated < created:
            raise WorktreeStateError("Worktree 更新时间早于创建时间")

        # frozen=True 后用 object.__setattr__ 修改规范化值
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "integration_ref", canonical_integration_ref(self.integration_ref))
        object.__setattr__(self, "baseline_commit", canonical_git_object_id(self.baseline_commit))
        object.__setattr__(
            self,
            "branch_tip",
            None if self.branch_tip is None else canonical_git_object_id(self.branch_tip),
        )
        object.__setattr__(self, "review_reason", reason)
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)


@dataclass(frozen=True, slots=True)
class WorktreeEvent:
    """append-only 审计事件；每行复制当时 Binding 的关键字段。

    这是什么：不可变的审计日志记录
    Java 类比：record WorktreeEvent(...) 用于事件溯源
    为什么需要：每次状态迁移都追加一条事件，确保操作可追溯和审计

    参数：
        sequence: SQLite 自增序号，决定唯一审计顺序
        action: 动作类型（reserve/create/keep/needs_review/remove）
        status: 本事件完成后的 Binding 状态
        task_id/name/branch/...: 复制 Binding 的关键字段快照
    """

    sequence: int             # SQLite 自增序号，决定唯一审计顺序
    action: str               # reserve/create/keep/needs_review/remove
    status: str               # 本事件完成后的 Binding 状态
    task_id: str              # 关联 Task UUID
    name: str                 # 受管 Worktree 名称
    branch: str               # 受管分支名
    relative_path: str        # 仓库内受管相对路径
    integration_ref: str      # 集成目标引用
    baseline_commit: str      # 创建时基线提交
    branch_tip: str | None    # 当次迁移已验证的分支 HEAD
    reason: str | None        # needs_review 的人工复核原因
    created_at_utc: datetime  # 事件发生时间

    def __post_init__(self) -> None:
        """验证 action/status 配对，并复用 Binding 的完整字段校验。

        这是什么：审计事件的一致性校验
        Java 类比：record compact constructor 校验
        为什么需要：确保审计事件与状态转换规则一致，action 必须对应正确的 status
        """
        # sequence 必须是正整数（SQLite AUTOINCREMENT 从 1 开始）
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            raise WorktreeStateError("Worktree event sequence 必须是正整数")

        # 关键：action 和 status 必须配对（如 "create" → "active"）
        if self.action not in _ACTIONS or _ACTION_STATUS[self.action] != self.status:
            raise WorktreeStateError("Worktree event action 与 status 不匹配")

        # 复用 WorktreeBinding 的完整校验逻辑
        WorktreeBinding(
            self.task_id,
            self.name,
            self.branch,
            self.relative_path,
            self.integration_ref,
            self.baseline_commit,
            self.branch_tip,
            self.status,
            self.reason,
            self.created_at_utc,
            self.created_at_utc,  # 事件时间同时作为 created 和 updated
        )


class WorktreeStore(LeasedTaskStore, Protocol):
    """同时保存 Task、claim、Binding 和审计事件的 Repository 接口。

    这是什么：Worktree 持久化的 Repository 接口
    Java 类比：interface WorktreeRepository extends TaskRepository
    为什么需要：定义持久化契约，让领域层不依赖 SQLite 具体实现

    方法说明（每个状态迁移方法都在同一事务中更新 Binding 和追加审计事件）：
        reserve_worktree: 预留 Worktree（两阶段提交的第一阶段）
        activate_worktree: Git 创建成功后激活 Worktree
        keep_worktree: 手动保留已完成任务的 Worktree
        mark_worktree_needs_review: 证明失败时转人工审查
        mark_worktree_removed: 删除完成后标记为 removed
        get_worktree_binding: 查询当前绑定快照
        list_worktree_events: 查询所有审计事件
        claim_next_bound: 认领第一个有 active binding 的 ready Task
        lookup_claim: 根据 claim token 查询认领信息
    """

    def reserve_worktree(self, binding: WorktreeBinding) -> WorktreeBinding: ...
    def activate_worktree(self, task_id: str, branch_tip: str, occurred_at_utc: datetime) -> WorktreeBinding: ...
    def keep_worktree(self, task_id: str, branch_tip: str, occurred_at_utc: datetime) -> WorktreeBinding: ...
    def mark_worktree_needs_review(self, task_id: str, branch_tip: str | None, reason: str, occurred_at_utc: datetime) -> WorktreeBinding: ...
    def mark_worktree_removed(self, task_id: str, branch_tip: str, occurred_at_utc: datetime) -> WorktreeBinding: ...
    def get_worktree_binding(self, task_id: str) -> WorktreeBinding: ...
    def list_worktree_events(self) -> tuple[WorktreeEvent, ...]: ...
    def claim_next_bound(self, owner: str) -> TaskClaim | None: ...
    def lookup_claim(self, claim_token: str) -> TaskClaim | None: ...


class GitRunner(Protocol):
    """WorktreeRuntime 使用的 Git Port。

    这是什么：Git 命令执行的端口接口
    Java 类比：interface GitRunner（端口适配器模式）
    为什么需要：领域层通过接口调用 Git，适配器层负责 subprocess 细节
    """

    def run(self, arguments: Sequence[str], cwd: str) -> GitCommandResult: ...


class WorktreeRuntime(TaskClaimService):
    """把 Worktree 生命周期、任务认领和工具 cwd 路由连成一条状态链。

    这是什么：Worktree 的领域服务（Domain Service）
    Java 类比：@Service class WorktreeService implements TaskClaimService
    为什么需要：统一管理 Worktree 从创建到删除的完整生命周期，并提供 cwd 解析能力

    核心职责：
        1. Worktree 生命周期管理（create/keep/remove）
        2. 任务认领（claim_task/claim_next/complete_task）
        3. 上下文路由（resolve：从 claim token 解析可信 cwd）

    设计原则：
        - 无法证明安全，就不删除（fail-safe）
        - 路径和分支由领域规则固定，不信任外部输入
        - 每次工具调用前重新验证 token 有效性
    """

    def __init__(
        self,
        workspace: str,
        store: WorktreeStore,
        git_runner: GitRunner | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """保存依赖；真实 Git 仓库检查必须显式调用 ``validate_repository``。

        这是什么：依赖注入构造器
        Java 类比：@Autowired 构造器，注入 Repository 和基础设施依赖
        为什么需要：延迟仓库校验到显式调用，避免构造器抛异常

        参数：
            workspace: 主仓库根目录（必须是真实存在的 Git 仓库）
            store: WorktreeStore 实现（通常是 SqliteTaskStore）
            git_runner: Git 命令执行器（默认 SubprocessGitRunner）
            clock: 时钟函数（默认 datetime.now(UTC)，测试时可替换）
        """
        if not isinstance(workspace, str) or not workspace.strip():
            raise TypeError("workspace 必须是非空字符串")

        # 校验 store 是否实现了 WorktreeStore 的所有方法
        for method in (
            "reserve_worktree", "activate_worktree", "keep_worktree",
            "mark_worktree_needs_review", "mark_worktree_removed",
            "get_worktree_binding", "claim_next_bound", "lookup_claim",
        ):
            if not callable(getattr(store, method, None)):
                raise TypeError("store 必须实现 WorktreeStore")

        # 保存依赖：类似 Java 的 private final 字段
        self._workspace_root = str(Path(workspace).resolve())  # 规范化路径
        self._store = store                                     # Repository 接口
        self._git = git_runner or SubprocessGitRunner()        # Git 适配器
        self._clock = clock or (lambda: datetime.now(UTC))     # 时钟函数

        # execution_scope -> (scope_object, claim_token) 的映射表
        # 用于在一次 Agent.run 内自动路由到 Worktree
        self._scope_claims: dict[int, tuple[object, str]] = {}

        # 延迟仓库校验：构造器不校验，避免测试困难
        self._repository_validated = False

    @property
    def workspace_root(self) -> str:
        """返回主仓库根；AgentRunner 用它校验 Provider 的信任边界。

        这是什么：只读属性，返回规范化的仓库根路径
        Java 类比：public String getWorkspaceRoot()
        为什么需要：AgentRunner 需要确认 ToolContextProvider 解析的路径在信任边界内
        """
        return self._workspace_root

    @property
    def store(self) -> WorktreeStore:
        """返回唯一共享 Repository，供组合根校验对象身份。

        这是什么：只读属性，暴露内部 Repository 引用
        Java 类比：public WorktreeStore getStore()
        为什么需要：bootstrap 层需要校验所有组件共享同一个 store 实例
        """
        return self._store

    @property
    def lead_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """返回只应注册给 Lead 的三个管理工具。

        这是什么：返回 Worktree 管理工具的定义
        Java 类比：public List<ToolDefinition> getLeadToolDefinitions()
        为什么需要：create/keep/remove 是管理操作，只能由 Lead Agent 调用
        """
        return worktree_tool_definitions(self)

    def validate_repository(self) -> None:
        """确认 workspace 是 Git 主仓库真实根；成功后缓存结论。

        这是什么：仓库前置条件校验
        Java 类比：@PostConstruct void validateRepository()
        为什么需要：Worktree 只能在 Git 仓库根目录创建，提前校验避免后续失败

        校验内容：
            1. 路径必须是真实存在的目录
            2. 路径必须在 Git 工作树内（git rev-parse --is-inside-work-tree）
            3. 路径必须是仓库根（git rev-parse --show-toplevel）

        异常：
            WorktreeRepositoryError: 任何校验失败
        """
        # 缓存机制：避免重复校验
        if self._repository_validated:
            return

        # 1. 校验路径真实存在且是目录
        try:
            root = Path(self._workspace_root).resolve(strict=True)  # strict=True 要求路径存在
            if not root.is_dir():
                raise OSError("不是目录")
        except OSError as error:
            raise WorktreeRepositoryError("workspace 不是 Git 仓库") from error

        # 2. 校验路径在 Git 工作树内
        inside = self._run_git(("rev-parse", "--is-inside-work-tree"), root)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise WorktreeRepositoryError("workspace 不是 Git 仓库")

        # 3. 校验路径是仓库根（不是子目录）
        top = self._run_git(("rev-parse", "--show-toplevel"), root)
        try:
            repository_root = Path(top.stdout.strip()).resolve(strict=True)
        except OSError as error:
            raise WorktreeRepositoryError("Git 仓库根目录无法解析") from error

        # 关键：workspace 必须是仓库根，不能是子目录
        if top.returncode != 0 or repository_root != root:
            raise WorktreeRepositoryError("workspace 必须是 Git 仓库根目录")

        # 保存规范化路径并标记校验通过
        self._workspace_root = str(root)
        self._repository_validated = True

    def create_worktree(self, task_id: str, name: str, integration_ref: str) -> WorktreeBinding:
        """先 reserve 意图，再创建 Git Worktree，回读验证后转为 active。

        这是什么：两阶段提交创建 Worktree
        Java 类比：@Transactional public WorktreeBinding createWorktree(...)
        为什么需要：先预留状态（reserve），Git 成功后再激活（active），失败时可以清理

        两阶段流程：
            阶段1：reserve_worktree（预留名称和路径，status=reserved）
            阶段2：Git worktree add 成功后，activate_worktree（status=active）

        参数：
            task_id: 要隔离执行的任务 UUID
            name: Worktree 名称（决定分支 wt/{name} 和路径 .agent_tutorial/worktrees/{name}）
            integration_ref: 最终合入的目标引用（如 refs/heads/main）

        返回：
            WorktreeBinding: status=active 的绑定快照

        异常：
            WorktreeStateError: 任务状态不是 pending
            WorktreeGitError: Git 命令失败或结果不符合预期
        """
        # 前置条件：仓库必须已校验
        self.validate_repository()

        # 规范化输入参数
        normalized_id = canonical_task_id(task_id)
        normalized_name = canonical_agent_name(name)
        normalized_ref = canonical_integration_ref(integration_ref)

        # 业务规则：只能为 pending 任务创建 Worktree
        task = self._store.get_task(normalized_id)
        if task.status != "pending":
            raise WorktreeStateError(f"任务 {task.id} 当前是 {task.status}，创建 Worktree 需要 pending")

        # 解析集成引用的基线提交（SHA-1/SHA-256）
        baseline = self._resolve_commit(normalized_ref, Path(self._workspace_root))
        now = self._now()

        # === 阶段1：预留 Worktree（reserved 状态） ===
        # 此时 branch_tip 为 None，因为 Git Worktree 还未创建
        binding = self._store.reserve_worktree(
            WorktreeBinding(
                normalized_id,
                normalized_name,
                f"wt/{normalized_name}",                         # 固定分支命名规则
                f".agent_tutorial/worktrees/{normalized_name}",  # 固定路径规则
                normalized_ref,
                baseline,
                None,                                             # reserved 阶段无 branch_tip
                "reserved",
                None,
                now,
                now,
            )
        )

        # 准备 Worktree 目标路径（创建父目录、校验不存在）
        path = self._prepare_new_path(binding)

        # === 阶段2：执行 Git 命令创建 Worktree ===
        # -b 创建新分支，从 baseline_commit 开始
        result = self._run_git(
            ("worktree", "add", "-b", binding.branch, str(path), binding.baseline_commit),
            Path(self._workspace_root),
        )
        if result.returncode != 0:
            # Git 失败：Binding 已 reserved，需手动清理或转 needs_review
            raise WorktreeGitError("Git 无法创建已经 reserved 的 Worktree")

        # 回读验证：确认 Worktree 的 HEAD 和分支名正确
        branch_tip = self._resolve_commit("HEAD", path)
        branch = self._run_git(("branch", "--show-current"), path)
        if branch.returncode != 0 or branch.stdout.strip() != binding.branch:
            raise WorktreeGitError("Git 创建出的 Worktree 分支与 binding 不一致")

        # === 阶段2 完成：激活 Worktree（active 状态） ===
        return self._store.activate_worktree(binding.task_id, branch_tip, self._now())

    def keep_worktree(self, task_id: str) -> WorktreeBinding:
        """显式保留已完成任务的 active Worktree；证明失败则转 needs_review。"""
        binding = self._completed_binding(task_id, ("active",))
        try:
            path = self._registered_path(binding)
            branch_tip = self._resolve_commit("HEAD", path)
        except WorktreeError:
            return self._needs_review(binding, binding.branch_tip, "受管 Worktree 路径或分支 HEAD 无法确认")
        return self._store.keep_worktree(binding.task_id, branch_tip, self._now())

    def remove_worktree(self, task_id: str) -> WorktreeBinding:
        """只删除已完成、干净且分支提交已进入集成引用的 Worktree。

        这是什么：Fail-Safe 删除 Worktree
        Java 类比：public WorktreeBinding removeWorktree(String taskId)
        为什么需要：保护用户数据优先于自动化清理，任何证明失败都转 needs_review

        Fail-Safe 原则（先证明安全，再删除）：
            1. 任务必须 completed
            2. 路径仍在 .agent_tutorial/worktrees/ 下（防止路径逃逸）
            3. git status --porcelain 为空（无未提交修改）
            4. 分支提交已在 integration_ref（已合并）
            任何失败 → needs_review（保留现场供人工排查）

        删除步骤（任一失败则转 needs_review）：
            1. git switch --detach（脱离分支）
            2. git branch -d {branch}（安全删除分支）
            3. git worktree remove {path}（移除 Worktree）

        参数：
            task_id: 要删除的任务 UUID

        返回：
            WorktreeBinding: status=removed 或 status=needs_review 的绑定快照
        """
        # 前置条件：任务必须 completed，Binding 必须是 active/kept/needs_review
        binding = self._completed_binding(task_id, ("active", "kept", "needs_review"))

        # === 证明1：路径可用且在安全边界内 ===
        try:
            path = self._registered_path(binding)
        except WorktreeError:
            # 路径不存在或逃逸：保留现场，不删除
            return self._needs_review(binding, binding.branch_tip, "受管 Worktree 路径不可用或越界")

        # === 证明2：路径是 Git 注册的 Worktree ===
        if not self._is_registered(binding, path):
            return self._needs_review(binding, binding.branch_tip, "受管路径不是 Git 注册的目标 Worktree")

        # === 证明3：Worktree 干净（无未提交修改） ===
        status = self._run_git(("status", "--porcelain=v1", "--untracked-files=all"), path)
        if status.returncode != 0:
            return self._needs_review(binding, binding.branch_tip, "git status 无法证明 Worktree 干净")
        if status.stdout:  # 有输出说明有未提交修改
            return self._needs_review(binding, binding.branch_tip, "Worktree 存在未提交修改")

        # === 证明4：分支提交已合入集成引用 ===
        try:
            branch_tip = self._resolve_commit("HEAD", path)
            integration_tip = self._resolve_commit(binding.integration_ref, Path(self._workspace_root))
        except WorktreeError:
            return self._needs_review(binding, binding.branch_tip, "集成引用或分支 HEAD 无法解析")

        # 检查 branch_tip 是否是 integration_tip 的祖先
        ancestor = self._run_git(
            ("merge-base", "--is-ancestor", branch_tip, integration_tip), Path(self._workspace_root)
        )
        if ancestor.returncode != 0:  # 非零表示不是祖先（未合并）
            return self._needs_review(binding, branch_tip, "Worktree 分支尚未合入集成引用")

        # === 所有证明通过，开始删除 ===
        # 任一步骤失败都转 needs_review，不抛异常
        for arguments, cwd, reason in (
            (("switch", "--detach"), path, "Git 无法 detach Worktree"),
            (("branch", "-d", binding.branch), Path(self._workspace_root), "Git 无法安全删除受管分支"),
            (("worktree", "remove", str(path)), Path(self._workspace_root), "Git 无法移除受管 Worktree"),
        ):
            if self._run_git(arguments, cwd).returncode != 0:
                return self._needs_review(binding, branch_tip, reason)

        # 删除完成：标记为 removed
        return self._store.mark_worktree_removed(binding.task_id, branch_tip, self._now())

    def claim_task(self, task_id: str, context: ToolContext) -> TaskClaim:
        """手动认领 active binding，并把本次 execution_scope 绑定到 claim token。"""
        if context.execution_scope is None:
            raise WorktreeContextError("认领 Worktree 任务需要 execution_scope")
        binding = self._store.get_worktree_binding(task_id)
        if binding.status != "active":
            raise WorktreeStateError("只有 active Worktree binding 可以认领")
        claim = self._store.claim_task(task_id, context.identity)
        self._scope_claims[id(context.execution_scope)] = (context.execution_scope, claim.claim_token)
        return claim

    def claim_next(self, owner: str) -> TaskClaim | None:
        """自动认领第一个具有 active binding 的 ready Task。"""
        return self._store.claim_next_bound(owner)

    def complete_task(self, task_id: str, claim_token: str, context: ToolContext) -> TaskCompletion:
        """完成当前 claim，并清理 execution_scope 到 token 的临时绑定。"""
        completion = self._store.complete_task(task_id, context.identity, claim_token)
        if context.execution_scope is not None:
            current = self._scope_claims.get(id(context.execution_scope))
            if current is not None and current[0] is context.execution_scope:
                self._scope_claims.pop(id(context.execution_scope), None)
        return completion

    def resolve(self, context: ToolContext) -> ToolContext:
        """按显式 token 或当前 scope 把工具路由到 active Worktree。

        这是什么：上下文拦截器，从 claim token 解析可信 cwd
        Java 类比：Filter.doFilter() 或请求拦截器
        为什么需要：每次工具调用前重新验证 token 有效性，确保路由到正确的 Worktree

        路由逻辑：
            1. 优先使用显式 claim_token
            2. 否则查找当前 execution_scope 绑定的 token
            3. 无 token 则返回原始 context（主工作区）
            4. 有 token 则校验并解析到 Worktree 路径

        安全校验（任一失败都抛异常，不回退到主工作区）：
            - token 格式合法且未过期
            - token 的 owner 与 context.identity 一致
            - token 的 task_id 与 context.task_id 一致（如果指定）
            - 对应的 Binding 状态是 active
            - worktree_name 一致（如果指定）

        参数：
            context: 当前工具上下文

        返回：
            ToolContext: 路由后的上下文（workspace 可能被替换为 Worktree 路径）

        异常：
            WorktreeContextError: token 失效或校验失败（不回退到主工作区）
        """
        # 1. 确定要使用的 claim token
        token = context.claim_token

        # 如果没有显式 token，尝试从 execution_scope 查找
        if token is None and context.execution_scope is not None:
            scoped = self._scope_claims.get(id(context.execution_scope))
            # 必须校验对象身份（不只是 id），防止 id 重用
            if scoped is not None and scoped[0] is context.execution_scope:
                token = scoped[1]

        # 2. 无 token 则直接返回（使用主工作区）
        if token is None:
            return context

        # 3. 校验并解析 token
        try:
            normalized_token = canonical_claim_token(token)
            claim = self._store.lookup_claim(normalized_token)
        except (TaskError, ValueError, TypeError) as error:
            # token 格式非法或已失效
            raise WorktreeContextError("claim token 已失效或格式错误") from error

        # 关键：token 失效后不能回退到主工作区（安全边界）
        if claim is None:
            raise WorktreeContextError("claim token 未知，不能回落主工作区")

        # 4. 校验 token 的 owner 与当前 identity 一致
        if claim.task.owner != context.identity:
            raise WorktreeContextError("claim token 的 owner 与当前 identity 不一致")

        # 5. 校验 task_id 一致性（如果 context 指定了 task_id）
        if context.task_id is not None and canonical_task_id(context.task_id) != claim.task.id:
            raise WorktreeContextError("claim token 与当前 task_id 不一致")

        # 6. 查询 Worktree Binding 并校验状态
        binding = self._store.get_worktree_binding(claim.task.id)
        if binding.status != "active":
            # 任务完成后 Binding 可能是 kept/needs_review/removed
            raise WorktreeContextError("claim 对应的 Worktree binding 不再 active")

        # 7. 校验 worktree_name 一致性（如果 context 指定了）
        if context.worktree_name is not None and context.worktree_name != binding.name:
            raise WorktreeContextError("claim token 与当前 worktree_name 不一致")

        # 8. 解析 Worktree 路径并校验安全性
        path = self._registered_path(binding)

        # 9. 返回路由后的上下文（workspace 替换为 Worktree 路径）
        return ToolContext(
            str(path),              # 替换为 Worktree 路径
            context.identity,
            context.idempotency_key,
            claim.task.id,          # 填充 task_id
            normalized_token,       # 填充规范化的 claim_token
            binding.name,           # 填充 worktree_name
            context.execution_scope,
        )

    def _completed_binding(self, task_id: str, allowed: Sequence[str]) -> WorktreeBinding:
        """读取 completed Task 与允许状态的 Binding。"""
        task = self._store.get_task(task_id)
        if task.status != "completed":
            raise WorktreeStateError(f"任务 {task.id} 当前是 {task.status}，操作需要 completed")
        binding = self._store.get_worktree_binding(task.id)
        if binding.status not in allowed:
            raise WorktreeStateError(f"Worktree binding 当前是 {binding.status}，不允许该操作")
        return binding

    def _needs_review(self, binding: WorktreeBinding, branch_tip: str | None, reason: str) -> WorktreeBinding:
        """仅把 active 转 needs_review；kept/needs_review 保持现场和原状态。"""
        if binding.status != "active":
            return binding
        return self._store.mark_worktree_needs_review(
            binding.task_id, branch_tip, reason, self._now()
        )

    def _prepare_new_path(self, binding: WorktreeBinding) -> Path:
        """创建受管父目录，并拒绝已存在目标和路径逃逸。"""
        root = Path(self._workspace_root)
        parent = root / ".agent_tutorial" / "worktrees"
        parent.mkdir(parents=True, exist_ok=True)
        resolved_parent = parent.resolve(strict=True)
        if not _inside(root, resolved_parent):
            raise WorktreeRepositoryError("Worktree 管理目录逃出了 workspace")
        path = resolved_parent / binding.name
        if path.exists() or path.is_symlink():
            raise WorktreeStateError("Worktree 目标路径已经存在")
        return path

    def _registered_path(self, binding: WorktreeBinding) -> Path:
        """解析现有受管路径，并确认真实路径仍位于 workspace 内。"""
        root = Path(self._workspace_root)
        expected = root / Path(binding.relative_path)
        try:
            path = expected.resolve(strict=True)
        except OSError as error:
            raise WorktreeGitError("受管 Worktree 路径不存在") from error
        if not path.is_dir() or not _inside(root, path):
            raise WorktreeGitError("受管 Worktree 路径不安全")
        return path

    def _is_registered(self, binding: WorktreeBinding, path: Path) -> bool:
        """从 ``git worktree list --porcelain`` 验证路径和分支仍匹配。"""
        result = self._run_git(("worktree", "list", "--porcelain"), Path(self._workspace_root))
        if result.returncode != 0:
            return False
        target = os.path.normcase(str(path))
        current_path: str | None = None
        current_branch: str | None = None
        records: list[tuple[str | None, str | None]] = []
        for line in (*result.stdout.splitlines(), ""):
            if not line:
                if current_path is not None:
                    records.append((current_path, current_branch))
                current_path = None
                current_branch = None
            elif line.startswith("worktree "):
                current_path = line.removeprefix("worktree ")
            elif line.startswith("branch "):
                current_branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        return any(os.path.normcase(str(Path(item).resolve())) == target and branch == binding.branch for item, branch in records if item is not None)

    def _resolve_commit(self, reference: str, cwd: Path) -> str:
        """把 ref 解析成 40/64 位完整对象 ID。"""
        result = self._run_git(("rev-parse", "--verify", f"{reference}^{{commit}}"), cwd)
        if result.returncode != 0:
            raise WorktreeGitError("Git 提交引用无法解析")
        return canonical_git_object_id(result.stdout.strip())

    def _run_git(self, arguments: Sequence[str], cwd: Path) -> GitCommandResult:
        """把进程级异常转换成不泄漏内部输出的领域异常。"""
        try:
            return self._git.run(arguments, str(cwd))
        except GitExecutionError as error:
            raise WorktreeGitError("Git 进程执行失败") from error

    def _now(self) -> datetime:
        """读取 UTC 时钟，拒绝无时区 datetime。"""
        value = self._clock()
        return _utc_time(value, "运行时钟")


def worktree_tool_definitions(runtime: WorktreeRuntime) -> tuple[ToolDefinition, ...]:
    """创建 Lead 的 create/keep/remove 三个 Worktree 管理工具。"""
    return (
        ToolDefinition(
            "create_worktree",
            "为 pending Task 创建受管 Git Worktree。",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "pattern": CANONICAL_UUID.pattern},
                    "name": {"type": "string", "minLength": 1},
                    "integration_ref": {"type": "string", "minLength": 1},
                },
                "required": ["task_id", "name", "integration_ref"],
                "additionalProperties": False,
            },
            "write",
            lambda arguments, _context: _operation(
                lambda: runtime.create_worktree(
                    str(arguments["task_id"]), str(arguments["name"]), str(arguments["integration_ref"])
                )
            ),
            _validate_create,
        ),
        *_single_task_tools(runtime),
    )


def _single_task_tools(runtime: WorktreeRuntime) -> tuple[ToolDefinition, ToolDefinition]:
    """创建 keep_worktree 与 remove_worktree 两个单 task_id 工具。"""
    schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "pattern": CANONICAL_UUID.pattern}},
        "required": ["task_id"],
        "additionalProperties": False,
    }
    def make_handler(operation: Callable[[str], WorktreeBinding]) -> Callable[[Mapping[str, Any], ToolContext], ToolResult]:
        """给闭包明确标注工具 Handler 类型，帮助 mypy 理解参数。"""
        def handler(arguments: Mapping[str, Any], _context: ToolContext) -> ToolResult:
            return _operation(lambda: operation(str(arguments["task_id"])))
        return handler

    return tuple(
        ToolDefinition(
            name,
            description,
            schema,
            "write",
            make_handler(operation),
            _validate_task_id,
        )
        for name, description, operation in (
            ("keep_worktree", "显式保留已完成任务的受管 Worktree。", runtime.keep_worktree),
            ("remove_worktree", "安全移除已合入且干净的受管 Worktree。", runtime.remove_worktree),
        )
    )  # type: ignore[return-value]


def _operation(operation: Callable[[], WorktreeBinding]) -> ToolResult:
    """把 Worktree 领域结果转换为稳定 JSON 工具结果。"""
    try:
        binding = operation()
    except TaskError as error:
        return tool_error(error.code, str(error))
    return tool_success(json.dumps(_binding_payload(binding), ensure_ascii=False, sort_keys=True))


def _binding_payload(binding: WorktreeBinding) -> dict[str, object]:
    """把 Python 字段映射为 snake_case wire format。"""
    return {
        "baseline_commit": binding.baseline_commit,
        "branch": binding.branch,
        "branch_tip": binding.branch_tip,
        "integration_ref": binding.integration_ref,
        "name": binding.name,
        "relative_path": binding.relative_path,
        "review_reason": binding.review_reason,
        "status": binding.status,
        "task_id": binding.task_id,
    }


def canonical_git_object_id(value: object) -> str:
    """规范化 Git SHA-1/SHA-256 完整对象 ID。"""
    if not isinstance(value, str) or _OBJECT_ID.fullmatch(value) is None:
        raise WorktreeStateError("Git object id 必须是 40 或 64 位小写十六进制")
    return value


def canonical_integration_ref(value: object) -> str:
    """只接受安全的本地分支完整引用 ``refs/heads/...``。"""
    if not isinstance(value, str) or value != value.strip() or not value.startswith("refs/heads/"):
        raise WorktreeStateError("integration_ref 必须是 refs/heads/... 完整引用")
    suffix = value.removeprefix("refs/heads/")
    if (
        not suffix
        or suffix.startswith("/")
        or suffix.endswith(("/", ".", ".lock"))
        or ".." in suffix
        or "@{" in suffix
        or any(character in value for character in " ~^:?*[\\")
        or any(part in {"", ".", ".."} for part in suffix.split("/"))
    ):
        raise WorktreeStateError("integration_ref 格式不安全")
    return value


def _normalize_reason(value: object) -> str | None:
    """把复核原因去除首尾空白；空字符串视为无原因。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise WorktreeStateError("review_reason 必须是字符串或 None")
    normalized = value.strip()
    return normalized or None


def _utc_time(value: object, label: str) -> datetime:
    """校验带时区 datetime，并复制成 UTC。"""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise WorktreeStateError(f"Worktree {label}必须是带时区 datetime")
    return value.astimezone(UTC)


def _inside(parent: Path, child: Path) -> bool:
    """判断 child 的真实路径是否在 parent 内。"""
    try:
        return os.path.commonpath((os.path.normcase(parent), os.path.normcase(child))) == os.path.normcase(parent)
    except ValueError:
        return False


def _validate_create(arguments: Mapping[str, Any]) -> bool:
    """严格校验 create_worktree 三个字段。"""
    return (
        set(arguments) == {"task_id", "name", "integration_ref"}
        and isinstance(arguments["task_id"], str)
        and CANONICAL_UUID.fullmatch(arguments["task_id"]) is not None
        and isinstance(arguments["name"], str)
        and bool(arguments["name"].strip())
        and isinstance(arguments["integration_ref"], str)
        and bool(arguments["integration_ref"].strip())
    )


def _validate_task_id(arguments: Mapping[str, Any]) -> bool:
    """严格校验只包含 canonical task_id。"""
    return (
        set(arguments) == {"task_id"}
        and isinstance(arguments["task_id"], str)
        and CANONICAL_UUID.fullmatch(arguments["task_id"]) is not None
    )
