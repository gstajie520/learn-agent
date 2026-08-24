"""第十二章：持久化 Task DAG 的领域模型和五个工具。

Java 对照：

* ``Task`` 类似不可变的 Java ``record Task(...)``；它只保存一个项目任务。
* ``TaskStore`` 类似 Repository interface；本模块不知道 JSON 文件怎样加锁和落盘。
* ``register_task_tools`` 类似把五个 Controller/Command Handler 注册到命令总线。

这里的 Task 和第五章 TODO 不相同。TODO 是当前 Agent 会话里的步骤清单；Task 是
workspace 级项目状态，进程退出后仍能从磁盘恢复，并且可以通过 ``blocked_by`` 形成 DAG。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..core.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)

TaskStatus = Literal["pending", "in_progress", "completed"]
TASK_STATUSES: tuple[TaskStatus, ...] = ("pending", "in_progress", "completed")
CANONICAL_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class TaskError(Exception):
    """所有可预期 Task 领域错误的父类。

    ``code`` 是给程序和模型判断的稳定错误码；中文 ``message`` 是给学习者看的说明。
    Java 中可以理解成带 ``errorCode`` 字段的业务异常基类。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TaskNotFoundError(TaskError):
    """canonical UUID 合法，但磁盘任务图里没有该任务。"""

    def __init__(self, message: str) -> None:
        super().__init__("task_not_found", message)


class TaskGraphError(TaskError):
    """任务图存在缺边、自依赖、重复依赖、ID 碰撞或环。"""

    def __init__(self, message: str) -> None:
        super().__init__("task_graph_error", message)


class TaskStateError(TaskError):
    """当前状态不允许执行 claim 或 complete。"""

    def __init__(self, message: str, code: str = "task_invalid_state") -> None:
        super().__init__(code, message)


class TaskBlockedError(TaskStateError):
    """任务仍有未完成依赖，因此暂时不能认领。"""

    def __init__(self, task_id: str, blocked_by: Sequence[str]) -> None:
        self.task_id = task_id
        self.blocked_by = tuple(blocked_by)
        super().__init__(
            f"任务 {task_id} 仍被以下依赖阻塞: {', '.join(self.blocked_by)}",
            "task_blocked",
        )


class TaskOwnershipError(TaskError):
    """只有认领任务的 owner 才能完成它。"""

    def __init__(self, message: str) -> None:
        super().__init__("task_owner_mismatch", message)


class TaskStorageError(TaskError):
    """任务目录、JSON 文件、锁或原子写入边界损坏。"""

    def __init__(self, message: str) -> None:
        super().__init__("task_storage_error", message)


@dataclass(frozen=True, slots=True)
class Task:
    """一个不可变项目任务。

    字段说明：
        ``id``：canonical UUID，也是 JSON 文件名。
        ``subject``：列表中快速识别任务的短标题。
        ``description``：更完整的工作说明，允许为空字符串。
        ``status``：只允许 pending、in_progress、completed 三态。
        ``owner``：认领者身份；pending 必须为空，其他状态必须非空。
        ``blocked_by``：当前任务依赖的上游 Task ID，不允许重复。

    ``frozen=True`` 类似 Java record 的 final 字段；创建后不能绕过状态机直接改属性。
    """

    id: str
    subject: str
    description: str
    status: TaskStatus
    owner: str | None
    blocked_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", canonical_task_id(self.id))
        object.__setattr__(self, "subject", _normalize_subject(self.subject))
        object.__setattr__(self, "description", _normalize_description(self.description))
        if self.status not in TASK_STATUSES:
            raise TaskStorageError("任务 status 只能是 pending、in_progress 或 completed")
        normalized_owner = None if self.owner is None else normalize_owner(self.owner)
        object.__setattr__(self, "owner", normalized_owner)
        object.__setattr__(self, "blocked_by", _normalize_dependencies(self.blocked_by))
        if self.status == "pending" and normalized_owner is not None:
            raise TaskStorageError("pending 任务不能有 owner")
        if self.status != "pending" and normalized_owner is None:
            raise TaskStorageError("in_progress 或 completed 任务必须有 owner")


@dataclass(frozen=True, slots=True)
class CreateTaskInput:
    """创建任务的输入 DTO；ID、初始状态和 owner 不允许由模型指定。"""

    subject: str
    description: str = ""
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskCompletion:
    """完成结果：已完成任务，以及本次直接解锁的下游任务。"""

    task: Task
    unblocked: tuple[Task, ...]


class TaskStore(Protocol):
    """持久化任务仓库接口，类似 Java Repository interface。

    工具层只依赖这些同步方法。第十二章使用 JSON 实现，后续章节可以换 SQLite，
    而五个工具和 Agent Loop 不需要跟着改变。
    """

    def create_task(self, value: CreateTaskInput) -> Task: ...

    def get_task(self, task_id: str) -> Task: ...

    def list_tasks(self) -> tuple[Task, ...]: ...

    def claim_task(self, task_id: str, owner: str) -> Task: ...

    def complete_task(self, task_id: str, owner: str) -> TaskCompletion: ...


def canonical_task_id(value: object) -> str:
    """只接受 UUID 的小写 canonical 文本，路径字符串无法进入存储层。"""
    if not isinstance(value, str) or CANONICAL_UUID.fullmatch(value) is None:
        raise TaskGraphError("task id 必须是小写 canonical UUID")
    return value


def normalize_owner(value: object) -> str:
    """清理可信运行时 identity；空白 owner 不能进入状态机。"""
    if not isinstance(value, str):
        raise TaskOwnershipError("任务 owner 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise TaskOwnershipError("任务 owner 不能为空")
    return normalized


def register_task_tools(registry: ToolRegistry, store: TaskStore) -> None:
    """把五个 Task 工具按固定顺序注册到同一个 ToolRegistry。"""
    registry.register(_create_task_definition(store))
    registry.register(
        _task_id_definition(
            "get_task",
            "按 canonical UUID 读取一个持久项目任务；只读，不修改 status 或 owner。",
            "read",
            store,
        )
    )
    registry.register(
        ToolDefinition(
            "list_tasks",
            "列出按 ID 稳定排序的完整项目任务图；创建依赖或认领任务前先查看。",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "read",
            lambda _arguments, _context: _task_operation(
                lambda: tool_success(
                    _encode_payload({"tasks": [_task_payload(task) for task in store.list_tasks()]})
                )
            ),
            _validate_empty_input,
        )
    )
    registry.register(
        _task_id_definition(
            "claim_task",
            "原子认领一个 ready 的 pending 任务；owner 由运行时 identity 写入，不能传参伪造。",
            "write",
            store,
        )
    )
    registry.register(
        ToolDefinition(
            "complete_task",
            "完成当前 identity 已认领的任务，并返回本次直接解锁的 pending 任务。",
            _task_id_parameters(),
            "write",
            lambda arguments, context: _task_operation(
                lambda: _complete_result(
                    store.complete_task(str(arguments["task_id"]), normalize_owner(context.identity))
                )
            ),
            _validate_task_id_input,
        )
    )


def _create_task_definition(store: TaskStore) -> ToolDefinition:
    return ToolDefinition(
        "create_task",
        "规划后创建持久项目任务；blocked_by 只能使用 list_tasks/get_task 返回的 canonical UUID。",
        {
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
        },
        "write",
        lambda arguments, _context: _task_operation(
            lambda: tool_success(
                _encode_payload(
                    _task_payload(
                        store.create_task(
                            CreateTaskInput(
                                str(arguments["subject"]),
                                str(arguments.get("description", "")),
                                tuple(str(value) for value in arguments.get("blocked_by", ())),
                            )
                        )
                    )
                )
            )
        ),
        _validate_create_input,
    )


def _task_id_definition(
    name: Literal["get_task", "claim_task"],
    description: str,
    effect: str,
    store: TaskStore,
) -> ToolDefinition:
    def handler(arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        task_id = str(arguments["task_id"])
        return _task_operation(
            lambda: tool_success(
                _encode_payload(
                    _task_payload(
                        store.get_task(task_id)
                        if name == "get_task"
                        else store.claim_task(task_id, normalize_owner(context.identity))
                    )
                )
            )
        )

    return ToolDefinition(
        name, description, _task_id_parameters(), effect, handler, _validate_task_id_input
    )


def _task_operation(operation: Any) -> ToolResult:
    """已知领域异常转换成稳定工具错误；未知异常继续交给 registry 兜底。"""
    try:
        result = operation()
    except TaskError as error:
        return tool_error(error.code, str(error))
    if not isinstance(result, ToolResult):
        raise TypeError("Task 工具内部操作必须返回 ToolResult")
    return result


def _complete_result(completion: TaskCompletion) -> ToolResult:
    return tool_success(
        _encode_payload(
            {
                "task": _task_payload(completion.task),
                "unblocked": [_task_payload(task) for task in completion.unblocked],
            }
        )
    )


def _task_payload(task: Task) -> dict[str, object]:
    """模型可见字段和磁盘 JSON 都使用 ``blocked_by``，避免两套 wire format。"""
    return {
        "blocked_by": list(task.blocked_by),
        "description": task.description,
        "id": task.id,
        "owner": task.owner,
        "status": task.status,
        "subject": task.subject,
    }


def _encode_payload(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _task_id_parameters() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "pattern": CANONICAL_UUID.pattern},
        },
        "required": ["task_id"],
        "additionalProperties": False,
    }


def _validate_empty_input(value: Mapping[str, Any]) -> bool:
    return not value


def _validate_task_id_input(value: Mapping[str, Any]) -> bool:
    return set(value) == {"task_id"} and isinstance(value["task_id"], str) and (
        CANONICAL_UUID.fullmatch(value["task_id"]) is not None
    )


def _validate_create_input(value: Mapping[str, Any]) -> bool:
    if not set(value).issubset({"subject", "description", "blocked_by"}):
        return False
    subject = value.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        return False
    description = value.get("description", "")
    if not isinstance(description, str):
        return False
    dependencies = value.get("blocked_by", ())
    # validator 运行在 ToolRegistry 冻结参数之前，因此这里接收 JSON 解析得到的 list；
    # handler 真正执行时，注册表已经把它递归冻结成 tuple。
    if not isinstance(dependencies, (list, tuple)):
        return False
    if not all(isinstance(item, str) and CANONICAL_UUID.fullmatch(item) for item in dependencies):
        return False
    return len(dependencies) == len(set(dependencies))


def _normalize_subject(value: object) -> str:
    if not isinstance(value, str):
        raise TaskStorageError("任务 subject 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise TaskStorageError("任务 subject 不能为空")
    return normalized


def _normalize_description(value: object) -> str:
    if not isinstance(value, str):
        raise TaskStorageError("任务 description 必须是字符串")
    return value.strip()


def _normalize_dependencies(values: object) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TaskStorageError("任务 blocked_by 必须是 tuple")
    normalized = tuple(canonical_task_id(value) for value in values)
    if len(normalized) != len(set(normalized)):
        raise TaskGraphError("任务依赖不能重复")
    return normalized
