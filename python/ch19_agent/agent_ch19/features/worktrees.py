"""第十九章受控 Git Worktree 领域模型与运行时。

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
    """所有 Worktree 领域异常的父类。"""


class WorktreeRepositoryError(WorktreeError):
    """workspace 不是可受控的 Git 主仓库根。"""

    def __init__(self, message: str) -> None:
        super().__init__("worktree_repository_error", message)


class WorktreeStateError(WorktreeError):
    """Task 或 Binding 当前状态不允许目标操作。"""

    def __init__(self, message: str) -> None:
        super().__init__("worktree_invalid_state", message)


class WorktreeGitError(WorktreeError):
    """Git 已运行，但结果没有满足领域约束。"""

    def __init__(self, message: str) -> None:
        super().__init__("worktree_git_error", message)


class WorktreeContextError(WorktreeError):
    """claim token、执行身份或工作目录上下文不可信。"""

    def __init__(self, message: str) -> None:
        super().__init__("worktree_context_error", message)


@dataclass(frozen=True, slots=True)
class WorktreeBinding:
    """任务和受管 Worktree 的当前状态快照。

    Java 可以把它理解成 ``record WorktreeBinding(...)``。字段被冻结后不能修改；
    状态变化必须交给 Repository 生成一个新快照，并同时追加审计事件。
    """

    task_id: str  # 被隔离执行的 Task UUID。
    name: str  # 受管名称，同时决定分支名和目录名。
    branch: str  # 固定为 wt/{name}，不能让模型传任意分支。
    relative_path: str  # 固定为 .agent_tutorial/worktrees/{name}。
    integration_ref: str  # 最终结果应合入的 refs/heads/... 引用。
    baseline_commit: str  # 创建 Worktree 时解析得到的基线提交。
    branch_tip: str | None  # 已验证的 Worktree HEAD；reserved 阶段为空。
    status: str  # reserved/active/kept/needs_review/removed。
    review_reason: str | None  # needs_review 时给人工看的稳定原因。
    created_at_utc: datetime  # 首次预留时间。
    updated_at_utc: datetime  # 最近一次状态迁移时间。

    def __post_init__(self) -> None:
        """集中校验字段组合，防止非法快照进入 SQLite。"""
        task_id = canonical_task_id(self.task_id)
        name = canonical_agent_name(self.name)
        if self.branch != f"wt/{name}":
            raise WorktreeStateError("Worktree 分支必须与受管名称一致")
        if self.relative_path != f".agent_tutorial/worktrees/{name}":
            raise WorktreeStateError("Worktree 路径必须与受管名称一致")
        if self.status not in _STATUSES:
            raise WorktreeStateError("Worktree status 无效")
        reason = _normalize_reason(self.review_reason)
        if (self.status == "needs_review") != (reason is not None):
            raise WorktreeStateError("review_reason 与 Worktree status 不匹配")
        created = _utc_time(self.created_at_utc, "创建时间")
        updated = _utc_time(self.updated_at_utc, "更新时间")
        if updated < created:
            raise WorktreeStateError("Worktree 更新时间早于创建时间")
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
    """append-only 审计事件；每行复制当时 Binding 的关键字段。"""

    sequence: int  # SQLite 自增序号，决定唯一审计顺序。
    action: str  # reserve/create/keep/needs_review/remove。
    status: str  # 本事件完成后的 Binding 状态。
    task_id: str  # 关联 Task UUID。
    name: str  # 受管 Worktree 名称。
    branch: str  # 受管分支名。
    relative_path: str  # 仓库内受管相对路径。
    integration_ref: str  # 集成目标引用。
    baseline_commit: str  # 创建时基线提交。
    branch_tip: str | None  # 当次迁移已验证的分支 HEAD。
    reason: str | None  # needs_review 的人工复核原因。
    created_at_utc: datetime  # 事件发生时间。

    def __post_init__(self) -> None:
        """验证 action/status 配对，并复用 Binding 的完整字段校验。"""
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence <= 0
        ):
            raise WorktreeStateError("Worktree event sequence 必须是正整数")
        if self.action not in _ACTIONS or _ACTION_STATUS[self.action] != self.status:
            raise WorktreeStateError("Worktree event action 与 status 不匹配")
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
            self.created_at_utc,
        )


class WorktreeStore(LeasedTaskStore, Protocol):
    """同时保存 Task、claim、Binding 和审计事件的 Repository 接口。"""

    def reserve_worktree(self, binding: WorktreeBinding) -> WorktreeBinding: ...
    def activate_worktree(
        self, task_id: str, branch_tip: str, occurred_at_utc: datetime
    ) -> WorktreeBinding: ...
    def keep_worktree(
        self, task_id: str, branch_tip: str, occurred_at_utc: datetime
    ) -> WorktreeBinding: ...
    def mark_worktree_needs_review(
        self, task_id: str, branch_tip: str | None, reason: str, occurred_at_utc: datetime
    ) -> WorktreeBinding: ...
    def mark_worktree_removed(
        self, task_id: str, branch_tip: str, occurred_at_utc: datetime
    ) -> WorktreeBinding: ...
    def get_worktree_binding(self, task_id: str) -> WorktreeBinding: ...
    def list_worktree_events(self) -> tuple[WorktreeEvent, ...]: ...
    def claim_next_bound(self, owner: str) -> TaskClaim | None: ...
    def lookup_claim(self, claim_token: str) -> TaskClaim | None: ...


class GitRunner(Protocol):
    """WorktreeRuntime 使用的 Git Port。"""

    def run(self, arguments: Sequence[str], cwd: str) -> GitCommandResult: ...


class WorktreeRuntime(TaskClaimService):
    """把 Worktree 生命周期、任务认领和工具 cwd 路由连成一条状态链。"""

    def __init__(
        self,
        workspace: str,
        store: WorktreeStore,
        git_runner: GitRunner | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """保存依赖；真实 Git 仓库检查必须显式调用 ``validate_repository``。"""
        if not isinstance(workspace, str) or not workspace.strip():
            raise TypeError("workspace 必须是非空字符串")
        for method in (
            "reserve_worktree",
            "activate_worktree",
            "keep_worktree",
            "mark_worktree_needs_review",
            "mark_worktree_removed",
            "get_worktree_binding",
            "claim_next_bound",
            "lookup_claim",
        ):
            if not callable(getattr(store, method, None)):
                raise TypeError("store 必须实现 WorktreeStore")
        self._workspace_root = str(Path(workspace).resolve())
        self._store = store
        self._git = git_runner or SubprocessGitRunner()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._scope_claims: dict[int, tuple[object, str]] = {}
        self._repository_validated = False

    @property
    def workspace_root(self) -> str:
        """返回主仓库根；AgentRunner 用它校验 Provider 的信任边界。"""
        return self._workspace_root

    @property
    def store(self) -> WorktreeStore:
        """返回唯一共享 Repository，供组合根校验对象身份。"""
        return self._store

    @property
    def lead_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """返回只应注册给 Lead 的三个管理工具。"""
        return worktree_tool_definitions(self)

    def validate_repository(self) -> None:
        """确认 workspace 是 Git 主仓库真实根；成功后缓存结论。"""
        if self._repository_validated:
            return
        try:
            root = Path(self._workspace_root).resolve(strict=True)
            if not root.is_dir():
                raise OSError("不是目录")
        except OSError as error:
            raise WorktreeRepositoryError("workspace 不是 Git 仓库") from error
        inside = self._run_git(("rev-parse", "--is-inside-work-tree"), root)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise WorktreeRepositoryError("workspace 不是 Git 仓库")
        top = self._run_git(("rev-parse", "--show-toplevel"), root)
        try:
            repository_root = Path(top.stdout.strip()).resolve(strict=True)
        except OSError as error:
            raise WorktreeRepositoryError("Git 仓库根目录无法解析") from error
        if top.returncode != 0 or repository_root != root:
            raise WorktreeRepositoryError("workspace 必须是 Git 仓库根目录")
        self._workspace_root = str(root)
        self._repository_validated = True

    def create_worktree(self, task_id: str, name: str, integration_ref: str) -> WorktreeBinding:
        """先 reserve 意图，再创建 Git Worktree，回读验证后转为 active。"""
        self.validate_repository()
        normalized_id = canonical_task_id(task_id)
        normalized_name = canonical_agent_name(name)
        normalized_ref = canonical_integration_ref(integration_ref)
        task = self._store.get_task(normalized_id)
        if task.status != "pending":
            raise WorktreeStateError(
                f"任务 {task.id} 当前是 {task.status}，创建 Worktree 需要 pending"
            )
        baseline = self._resolve_commit(normalized_ref, Path(self._workspace_root))
        now = self._now()
        binding = self._store.reserve_worktree(
            WorktreeBinding(
                normalized_id,
                normalized_name,
                f"wt/{normalized_name}",
                f".agent_tutorial/worktrees/{normalized_name}",
                normalized_ref,
                baseline,
                None,
                "reserved",
                None,
                now,
                now,
            )
        )
        path = self._prepare_new_path(binding)
        result = self._run_git(
            ("worktree", "add", "-b", binding.branch, str(path), binding.baseline_commit),
            Path(self._workspace_root),
        )
        if result.returncode != 0:
            raise WorktreeGitError("Git 无法创建已经 reserved 的 Worktree")
        branch_tip = self._resolve_commit("HEAD", path)
        branch = self._run_git(("branch", "--show-current"), path)
        if branch.returncode != 0 or branch.stdout.strip() != binding.branch:
            raise WorktreeGitError("Git 创建出的 Worktree 分支与 binding 不一致")
        return self._store.activate_worktree(binding.task_id, branch_tip, self._now())

    def keep_worktree(self, task_id: str) -> WorktreeBinding:
        """显式保留已完成任务的 active Worktree；证明失败则转 needs_review。"""
        binding = self._completed_binding(task_id, ("active",))
        try:
            path = self._registered_path(binding)
            branch_tip = self._resolve_commit("HEAD", path)
        except WorktreeError:
            return self._needs_review(
                binding, binding.branch_tip, "受管 Worktree 路径或分支 HEAD 无法确认"
            )
        return self._store.keep_worktree(binding.task_id, branch_tip, self._now())

    def remove_worktree(self, task_id: str) -> WorktreeBinding:
        """只删除已完成、干净且分支提交已进入集成引用的 Worktree。"""
        binding = self._completed_binding(task_id, ("active", "kept", "needs_review"))
        try:
            path = self._registered_path(binding)
        except WorktreeError:
            return self._needs_review(binding, binding.branch_tip, "受管 Worktree 路径不可用或越界")
        if not self._is_registered(binding, path):
            return self._needs_review(
                binding, binding.branch_tip, "受管路径不是 Git 注册的目标 Worktree"
            )
        status = self._run_git(("status", "--porcelain=v1", "--untracked-files=all"), path)
        if status.returncode != 0:
            return self._needs_review(
                binding, binding.branch_tip, "git status 无法证明 Worktree 干净"
            )
        if status.stdout:
            return self._needs_review(binding, binding.branch_tip, "Worktree 存在未提交修改")
        try:
            branch_tip = self._resolve_commit("HEAD", path)
            integration_tip = self._resolve_commit(
                binding.integration_ref, Path(self._workspace_root)
            )
        except WorktreeError:
            return self._needs_review(binding, binding.branch_tip, "集成引用或分支 HEAD 无法解析")
        ancestor = self._run_git(
            ("merge-base", "--is-ancestor", branch_tip, integration_tip), Path(self._workspace_root)
        )
        if ancestor.returncode != 0:
            return self._needs_review(binding, branch_tip, "Worktree 分支尚未合入集成引用")
        for arguments, cwd, reason in (
            (("switch", "--detach"), path, "Git 无法 detach Worktree"),
            (
                ("branch", "-d", binding.branch),
                Path(self._workspace_root),
                "Git 无法安全删除受管分支",
            ),
            (
                ("worktree", "remove", str(path)),
                Path(self._workspace_root),
                "Git 无法移除受管 Worktree",
            ),
        ):
            if self._run_git(arguments, cwd).returncode != 0:
                return self._needs_review(binding, branch_tip, reason)
        return self._store.mark_worktree_removed(binding.task_id, branch_tip, self._now())

    def claim_task(self, task_id: str, context: ToolContext) -> TaskClaim:
        """手动认领 active binding，并把本次 execution_scope 绑定到 claim token。"""
        if context.execution_scope is None:
            raise WorktreeContextError("认领 Worktree 任务需要 execution_scope")
        binding = self._store.get_worktree_binding(task_id)
        if binding.status != "active":
            raise WorktreeStateError("只有 active Worktree binding 可以认领")
        claim = self._store.claim_task(task_id, context.identity)
        self._scope_claims[id(context.execution_scope)] = (
            context.execution_scope,
            claim.claim_token,
        )
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
        """按显式 token 或当前 scope 把工具路由到 active Worktree。"""
        token = context.claim_token
        if token is None and context.execution_scope is not None:
            scoped = self._scope_claims.get(id(context.execution_scope))
            if scoped is not None and scoped[0] is context.execution_scope:
                token = scoped[1]
        if token is None:
            return context
        try:
            normalized_token = canonical_claim_token(token)
            claim = self._store.lookup_claim(normalized_token)
        except (TaskError, ValueError, TypeError) as error:
            raise WorktreeContextError("claim token 已失效或格式错误") from error
        if claim is None:
            raise WorktreeContextError("claim token 未知，不能回落主工作区")
        if claim.task.owner != context.identity:
            raise WorktreeContextError("claim token 的 owner 与当前 identity 不一致")
        if context.task_id is not None and canonical_task_id(context.task_id) != claim.task.id:
            raise WorktreeContextError("claim token 与当前 task_id 不一致")
        binding = self._store.get_worktree_binding(claim.task.id)
        if binding.status != "active":
            raise WorktreeContextError("claim 对应的 Worktree binding 不再 active")
        if context.worktree_name is not None and context.worktree_name != binding.name:
            raise WorktreeContextError("claim token 与当前 worktree_name 不一致")
        path = self._registered_path(binding)
        return ToolContext(
            str(path),
            context.identity,
            context.idempotency_key,
            claim.task.id,
            normalized_token,
            binding.name,
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

    def _needs_review(
        self, binding: WorktreeBinding, branch_tip: str | None, reason: str
    ) -> WorktreeBinding:
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
        return any(
            os.path.normcase(str(Path(item).resolve())) == target and branch == binding.branch
            for item, branch in records
            if item is not None
        )

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
                    str(arguments["task_id"]),
                    str(arguments["name"]),
                    str(arguments["integration_ref"]),
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

    def make_handler(
        operation: Callable[[str], WorktreeBinding],
    ) -> Callable[[Mapping[str, Any], ToolContext], ToolResult]:
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
        return os.path.commonpath(
            (os.path.normcase(parent), os.path.normcase(child))
        ) == os.path.normcase(parent)
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
