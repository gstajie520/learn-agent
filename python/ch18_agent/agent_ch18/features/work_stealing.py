"""第十八章任务认领 Service、租约工具和空闲轮询配置。

Java 分层对照：

* ``LeasedTaskStore`` 是 Repository interface；SQLite 只是它的一个 Adapter。
* ``DirectTaskClaimService`` 是领域 Service，把可信 identity 绑定成任务 owner。
* ``WorkStealingRuntime`` 是 WorkerService 的配置对象，统一保存轮询策略和工具快照。

模型永远不能在工具参数里填写 owner。owner 来自 ``ToolContext.identity``，而完成任务
还必须回传当前 ``claim_token``。这和“用户名 + 一次性乐观锁令牌”同时校验很相似。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ..core.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)
from .tasks import (
    CANONICAL_UUID,
    CreateTaskInput,
    Task,
    TaskCompletion,
    TaskError,
    TaskStorageError,
    canonical_task_id,
)


class TaskClaimError(TaskError):
    """owner 或 claim token 与当前有效认领不匹配。"""

    def __init__(self, message: str, code: str = "task_claim_mismatch") -> None:
        super().__init__(code, message)


class TaskLeaseExpiredError(TaskClaimError):
    """认领曾经有效，但租约已经到达半开区间的结束边界。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, "task_lease_expired")


@dataclass(frozen=True, slots=True)
class TaskClaim:
    """一次成功认领的不可变结果。

    字段说明：
        ``task``：已经进入 in_progress 的任务快照。
        ``claim_token``：完成权限证明；旧 token 不能完成重新认领后的任务。
        ``lease_expires_at_utc``：本次认领的 UTC 到期时间。

    Java 可以把它理解成 ``record TaskClaim(Task task, UUID token, Instant expiresAt)``。
    """

    task: Task
    claim_token: str
    lease_expires_at_utc: datetime


class LeasedTaskStore(Protocol):
    """带租约的任务仓库接口，类似 Java Repository interface。"""

    def create_task(self, value: CreateTaskInput) -> Task:
        """创建一个带显式依赖的持久任务。"""

    def get_task(self, task_id: str) -> Task:
        """读取单个任务。"""

    def list_tasks(self) -> tuple[Task, ...]:
        """按稳定创建顺序列出任务图。"""

    def claim_task(self, task_id: str, owner: str) -> TaskClaim:
        """手动认领指定 ready 任务。"""

    def claim_next(self, owner: str) -> TaskClaim | None:
        """自动认领第一个 ready 任务。"""

    def complete_task(self, task_id: str, owner: str, claim_token: str) -> TaskCompletion:
        """使用当前租约凭证完成任务。"""


class TaskClaimService(Protocol):
    """把 Agent 身份绑定到仓库操作的应用服务接口。"""

    @property
    def store(self) -> LeasedTaskStore:
        """返回该 Service 使用的唯一仓库实例。"""

    def claim_task(self, task_id: str, context: ToolContext) -> TaskClaim:
        """从 ToolContext 获取 owner，模型参数不能伪造身份。"""

    def claim_next(self, owner: str) -> TaskClaim | None:
        """由受管 worker 使用自己的固定身份自动认领。"""

    def complete_task(
        self, task_id: str, claim_token: str, context: ToolContext
    ) -> TaskCompletion:
        """使用上下文身份和模型回传 token 完成任务。"""


class DirectTaskClaimService:
    """不保存额外状态的默认任务认领 Service。"""

    def __init__(self, store: LeasedTaskStore) -> None:
        """只保存组合根提供的共享 Repository 引用。"""
        self._store = store

    @property
    def store(self) -> LeasedTaskStore:
        """暴露引用，供组合根校验所有 Agent 是否真的共享一个仓库。"""
        return self._store

    def claim_task(self, task_id: str, context: ToolContext) -> TaskClaim:
        """把可信 ``context.identity`` 写成 owner。"""
        return self._store.claim_task(task_id, context.identity)

    def claim_next(self, owner: str) -> TaskClaim | None:
        """让队友后台线程直接以自己的固定 name 认领。"""
        return self._store.claim_next(owner)

    def complete_task(
        self, task_id: str, claim_token: str, context: ToolContext
    ) -> TaskCompletion:
        """同时校验 identity 和 claim token。"""
        return self._store.complete_task(task_id, context.identity, claim_token)


class WorkStealingSleeper(Protocol):
    """可中断等待接口；测试可注入即时 sleeper，避免真的等 5 秒。"""

    def sleep(self, seconds: float, wakeup: threading.Event) -> None:
        """等待超时或等待 wakeup 被 set。"""


class EventWorkStealingSleeper:
    """基于 ``threading.Event.wait`` 的生产 sleeper。"""

    def sleep(self, seconds: float, wakeup: threading.Event) -> None:
        """新消息或关闭流程调用 ``set()`` 后会立即结束等待。"""
        wakeup.wait(seconds)


class WorkStealingRuntime:
    """封装共享 Store、认领 Service、轮询参数和两套工具列表。

    字段说明：
        ``_store``：Lead、子 Agent、队友共同操作的 SQLite Repository。
        ``_claim_service``：统一绑定 owner 的领域 Service。
        ``_sleeper``：可被新消息和关闭流程中断的等待器。
        ``_poll_interval_seconds``：两次空扫描之间等待多久。
        ``_max_idle_polls``：连续多少次空扫描后结束当前 worker 线程。
        ``_lead_tool_definitions``：完整五工具，包含 create_task。
        ``_teammate_tool_definitions``：去掉 create_task 的四工具。
    """

    def __init__(
        self,
        store: LeasedTaskStore,
        *,
        claim_service: TaskClaimService | None = None,
        sleeper: WorkStealingSleeper | None = None,
        poll_interval_seconds: float = 5.0,
        max_idle_polls: int = 12,
    ) -> None:
        """固定本次运行所用的仓库、服务和轮询策略。"""
        _require_leased_store(store)
        actual_service = claim_service or DirectTaskClaimService(store)
        if actual_service.store is not store:
            raise ValueError("claim_service 必须使用 WorkStealingRuntime 的同一个 store")
        actual_sleeper = sleeper or EventWorkStealingSleeper()
        if not callable(getattr(actual_sleeper, "sleep", None)):
            raise TypeError("sleeper 必须实现 sleep()")
        if not isinstance(poll_interval_seconds, (int, float)) or isinstance(
            poll_interval_seconds, bool
        ):
            raise TypeError("poll_interval_seconds 必须是数字")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        if isinstance(max_idle_polls, bool) or not isinstance(max_idle_polls, int):
            raise TypeError("max_idle_polls 必须是整数")
        if max_idle_polls <= 0:
            raise ValueError("max_idle_polls 必须大于 0")
        self._store = store
        self._claim_service = actual_service
        self._sleeper = actual_sleeper
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._max_idle_polls = max_idle_polls
        definitions = leased_task_tool_definitions(store, actual_service)
        self._lead_tool_definitions = definitions
        self._teammate_tool_definitions = definitions[1:]

    @property
    def store(self) -> LeasedTaskStore:
        """返回共享仓库实例。"""
        return self._store

    @property
    def claim_service(self) -> TaskClaimService:
        """返回共享身份绑定 Service。"""
        return self._claim_service

    @property
    def max_idle_polls(self) -> int:
        """返回连续空轮询上限。"""
        return self._max_idle_polls

    @property
    def lead_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """Lead 使用完整五工具。"""
        return self._lead_tool_definitions

    @property
    def teammate_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """持续队友使用四工具，不能创建新任务。"""
        return self._teammate_tool_definitions

    def claim_next(self, owner: str) -> TaskClaim | None:
        """委托共享 Service 自动认领下一个 ready 任务。"""
        return self._claim_service.claim_next(owner)

    def wait_for_poll(self, wakeup: threading.Event) -> None:
        """等待下一次轮询；wakeup 被设置时提前返回。"""
        self._sleeper.sleep(self._poll_interval_seconds, wakeup)

    def render_claim_prompt(self, claim: TaskClaim) -> str:
        """把租约和任务渲染成确定性的模型输入。"""
        payload = _claim_payload(claim)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return f"<auto-claimed-task>\n{encoded}\n</auto-claimed-task>"


def leased_task_tool_definitions(
    store: LeasedTaskStore,
    claim_service: TaskClaimService | None = None,
) -> tuple[ToolDefinition, ...]:
    """创建 Lead 的五个 SQLite Task 工具定义。"""
    _require_leased_store(store)
    service = claim_service or DirectTaskClaimService(store)
    if service.store is not store:
        raise ValueError("claim_service 必须使用同一个 leased Task store")
    return (
        ToolDefinition(
            "create_task",
            "创建带显式依赖的 SQLite 项目任务。",
            _create_parameters(),
            "write",
            lambda arguments, _context: _task_operation(
                lambda: tool_success(
                    _encode_payload(
                        _task_payload(
                            store.create_task(
                                CreateTaskInput(
                                    str(arguments["subject"]),
                                    str(arguments.get("description", "")),
                                    tuple(str(item) for item in arguments.get("blocked_by", ())),
                                )
                            )
                        )
                    )
                )
            ),
            _validate_create,
        ),
        ToolDefinition(
            "get_task",
            "按 UUID 读取一个 SQLite 项目任务。",
            _task_id_parameters(),
            "read",
            lambda arguments, _context: _task_operation(
                lambda: tool_success(
                    _encode_payload(_task_payload(store.get_task(str(arguments["task_id"]))))
                )
            ),
            _validate_task_id,
        ),
        ToolDefinition(
            "list_tasks",
            "按创建顺序列出 SQLite 任务图。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "read",
            lambda _arguments, _context: _task_operation(
                lambda: tool_success(
                    _encode_payload({"tasks": [_task_payload(task) for task in store.list_tasks()]})
                )
            ),
            lambda arguments: not arguments,
        ),
        ToolDefinition(
            "claim_task",
            "原子认领 ready 任务，并返回 claim token 和租约截止时间。",
            _task_id_parameters(),
            "write",
            lambda arguments, context: _task_operation(
                lambda: tool_success(
                    _encode_payload(service.claim_task(str(arguments["task_id"]), context))
                )
            ),
            _validate_task_id,
        ),
        ToolDefinition(
            "complete_task",
            "使用当前 identity 和 claim token 完成已认领任务。",
            _complete_parameters(),
            "write",
            lambda arguments, context: _task_operation(
                lambda: _completion_result(
                    service.complete_task(
                        str(arguments["task_id"]), str(arguments["claim_token"]), context
                    )
                )
            ),
            _validate_complete,
        ),
    )


def register_leased_task_tools(
    registry: ToolRegistry,
    store: LeasedTaskStore,
    claim_service: TaskClaimService | None = None,
) -> None:
    """给 Lead 或一次性子 Agent 注册完整五工具。"""
    for definition in leased_task_tool_definitions(store, claim_service):
        registry.register(definition)


def register_teammate_leased_task_tools(
    registry: ToolRegistry,
    store: LeasedTaskStore,
    claim_service: TaskClaimService | None = None,
) -> None:
    """给持续队友注册四工具，明确跳过 ``create_task``。"""
    for definition in leased_task_tool_definitions(store, claim_service)[1:]:
        registry.register(definition)


def canonical_claim_token(value: object) -> str:
    """claim token 必须是小写 canonical UUID。"""
    try:
        return canonical_task_id(value)
    except TaskError as error:
        raise TaskClaimError("claim token 必须是小写 canonical UUID") from error


def _task_operation(operation: Any) -> ToolResult:
    """把已知 Task 领域异常转换成稳定工具错误。"""
    try:
        result = operation()
    except TaskError as error:
        return tool_error(error.code, str(error))
    if not isinstance(result, ToolResult):
        raise TypeError("Task 工具内部操作必须返回 ToolResult")
    return result


def _completion_result(completion: TaskCompletion) -> ToolResult:
    """把领域完成结果转换成模型可见 JSON。"""
    return tool_success(
        _encode_payload(
            {
                "task": _task_payload(completion.task),
                "unblocked": [_task_payload(task) for task in completion.unblocked],
            }
        )
    )


def _task_payload(task: Task) -> dict[str, object]:
    """把 Python 字段转换成稳定 wire format。"""
    return {
        "blocked_by": list(task.blocked_by),
        "description": task.description,
        "id": task.id,
        "owner": task.owner,
        "status": task.status,
        "subject": task.subject,
    }


def _claim_payload(claim: TaskClaim) -> dict[str, object]:
    """把 ``TaskClaim`` 转换成模型需要回传的三个字段。"""
    return {
        "claim_token": claim.claim_token,
        "lease_expires_at_utc": claim.lease_expires_at_utc.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "task": _task_payload(claim.task),
    }


def _encode_payload(value: object) -> str:
    """生成确定性紧凑 JSON；dataclass TaskClaim 会先转换为普通字典。"""
    if isinstance(value, TaskClaim):
        value = _claim_payload(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _create_parameters() -> dict[str, Any]:
    """返回 create_task 的 JSON Schema。"""
    return {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "blocked_by": {
                "type": "array",
                "items": {"type": "string", "pattern": CANONICAL_UUID.pattern},
                "uniqueItems": True,
            },
        },
        "required": ["subject"],
        "additionalProperties": False,
    }


def _task_id_parameters() -> dict[str, Any]:
    """返回只接收 task_id 的 JSON Schema。"""
    return {
        "type": "object",
        "properties": {"task_id": {"type": "string", "pattern": CANONICAL_UUID.pattern}},
        "required": ["task_id"],
        "additionalProperties": False,
    }


def _complete_parameters() -> dict[str, Any]:
    """返回 complete_task 的 JSON Schema，claim_token 是必填权限证明。"""
    return {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "pattern": CANONICAL_UUID.pattern},
            "claim_token": {"type": "string", "pattern": CANONICAL_UUID.pattern},
        },
        "required": ["task_id", "claim_token"],
        "additionalProperties": False,
    }


def _validate_create(arguments: Mapping[str, Any]) -> bool:
    """严格校验 create_task 输入，不接受未知字段。"""
    if not set(arguments).issubset({"subject", "description", "blocked_by"}):
        return False
    subject = arguments.get("subject")
    description = arguments.get("description", "")
    dependencies = arguments.get("blocked_by", ())
    return (
        isinstance(subject, str)
        and bool(subject.strip())
        and isinstance(description, str)
        and isinstance(dependencies, (list, tuple))
        and all(
            isinstance(item, str) and CANONICAL_UUID.fullmatch(item) is not None
            for item in dependencies
        )
        and len(dependencies) == len(set(dependencies))
    )


def _validate_task_id(arguments: Mapping[str, Any]) -> bool:
    """严格校验单 task_id 输入。"""
    return (
        set(arguments) == {"task_id"}
        and isinstance(arguments["task_id"], str)
        and CANONICAL_UUID.fullmatch(arguments["task_id"]) is not None
    )


def _validate_complete(arguments: Mapping[str, Any]) -> bool:
    """严格校验 task_id 与 claim_token。"""
    return (
        set(arguments) == {"task_id", "claim_token"}
        and all(
            isinstance(arguments[name], str)
            and CANONICAL_UUID.fullmatch(arguments[name]) is not None
            for name in ("task_id", "claim_token")
        )
    )


def _require_leased_store(value: object) -> None:
    """运行时检查最小结构契约，错误配置在启动阶段立即暴露。"""
    methods = (
        "create_task",
        "get_task",
        "list_tasks",
        "claim_task",
        "claim_next",
        "complete_task",
    )
    if not all(callable(getattr(value, name, None)) for name in methods):
        raise TypeError("store 必须实现 LeasedTaskStore")


def require_claim(value: TaskClaim | None) -> TaskClaim:
    """教学辅助：把可选认领转换成必有值，否则给出清晰异常。"""
    if value is None:
        raise TaskStorageError("当前没有可认领的 ready 任务")
    return value
