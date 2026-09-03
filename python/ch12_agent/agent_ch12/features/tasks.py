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

    这是什么：Task 领域模型的业务异常基类
    Java 类比：类似带 errorCode 字段的 BusinessException
    为什么需要：区分 Task 业务错误和系统错误，让调用方能精确处理不同失败场景

    字段说明：
        code: 稳定的错误码（如 "task_not_found"），供程序和模型判断
        message: 人类可读的中文错误说明，供学习者理解

    ``code`` 是给程序和模型判断的稳定错误码；中文 ``message`` 是给学习者看的说明。
    Java 中可以理解成带 ``errorCode`` 字段的业务异常基类。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code  # 类似 Java 异常的 errorCode 字段


class TaskNotFoundError(TaskError):
    """canonical UUID 合法，但磁盘任务图里没有该任务。

    这是什么：查询、认领或完成任务时，ID 不存在的异常
    Java 类比：类似 EntityNotFoundException
    为什么需要：区分 ID 格式错误（TaskGraphError）和 ID 不存在（TaskNotFoundError）
    """

    def __init__(self, message: str) -> None:
        super().__init__("task_not_found", message)  # code 固定为 "task_not_found"


class TaskGraphError(TaskError):
    """任务图存在缺边、自依赖、重复依赖、ID 碰撞或环。

    这是什么：DAG 拓扑结构违反约束的异常
    Java 类比：类似 GraphValidationException
    为什么需要：防止循环依赖（A 依赖 B，B 依赖 A）导致死锁

    触发场景：
        - 缺边：blocked_by 引用了不存在的任务 ID
        - 自依赖：任务依赖自己
        - 环：A → B → C → A 形成循环
        - ID 格式错误：不是合法的 canonical UUID
    """

    def __init__(self, message: str) -> None:
        super().__init__("task_graph_error", message)  # code 固定为 "task_graph_error"


class TaskStateError(TaskError):
    """当前状态不允许执行 claim 或 complete。

    这是什么：状态机转换非法的异常
    Java 类比：类似 IllegalStateException
    为什么需要：强制 Task 状态机约束（pending → in_progress → completed）

    非法转换示例：
        - pending 任务直接调用 complete（必须先 claim）
        - completed 任务再次调用 complete（幂等性检查）
        - in_progress 任务被其他人 claim（已被占用）
    """

    def __init__(self, message: str, code: str = "task_invalid_state") -> None:
        super().__init__(code, message)  # 允许子类覆盖 code


class TaskBlockedError(TaskStateError):
    """任务仍有未完成依赖，因此暂时不能认领。

    这是什么：DAG 依赖未满足的专用异常
    Java 类比：类似 PreconditionNotMetException
    为什么需要：确保任务按依赖顺序执行，防止乱序导致错误

    示例：任务 B blocked_by [A]，只有 A 完成后 B 才能认领
    """

    def __init__(self, task_id: str, blocked_by: Sequence[str]) -> None:
        self.task_id = task_id  # 被阻塞的任务 ID
        self.blocked_by = tuple(blocked_by)  # 未完成的依赖任务 ID 列表
        super().__init__(
            f"任务 {task_id} 仍被以下依赖阻塞: {', '.join(self.blocked_by)}",
            "task_blocked",  # 专用错误码，区别于普通 TaskStateError
        )


class TaskOwnershipError(TaskError):
    """只有认领任务的 owner 才能完成它。

    这是什么：任务所有权冲突的异常
    Java 类比：类似 AccessDeniedException
    为什么需要：防止多人同时执行同一任务，确保责任唯一

    触发场景：
        - 用户 A claim 了任务，用户 B 尝试 complete
        - owner 字段为空或格式错误
    """

    def __init__(self, message: str) -> None:
        super().__init__("task_owner_mismatch", message)


class TaskStorageError(TaskError):
    """任务目录、JSON 文件、锁或原子写入边界损坏。

    这是什么：底层存储层的错误
    Java 类比：类似 DataAccessException
    为什么需要：区分业务逻辑错误和 I/O/文件系统错误

    触发场景：
        - JSON 文件损坏（格式错误）
        - 文件锁获取失败
        - 磁盘空间不足导致写入失败
    """

    def __init__(self, message: str) -> None:
        super().__init__("task_storage_error", message)


@dataclass(frozen=True, slots=True)
class Task:
    """一个不可变项目任务。

    这是什么：Task DAG 的核心领域实体
    Java 类比：类似不可变的 record Task(...) 或 @Entity 但只读
    为什么需要：持久化 workspace 级任务状态，支持 DAG 依赖关系

    与 TODO 的区别：
        - TODO：会话内步骤清单，进程退出丢失
        - Task：workspace 级状态，持久化到磁盘，进程重启后仍可恢复
        - Task 支持 DAG（blocked_by），TODO 只是顺序列表

    字段说明：
        id：canonical UUID（小写，带连字符），也是 JSON 文件名
        subject：短标题（1-200 字符），用于列表快速识别
        description：详细说明（可为空），用于完整工作描述
        status：三态状态机（pending → in_progress → completed）
        owner：认领者身份（pending 必须为 None，其他状态必须非空）
        blocked_by：依赖的上游任务 ID 列表（不允许重复，形成 DAG）

    ``frozen=True`` 类似 Java record 的 final 字段；创建后不能绕过状态机直接改属性。
    ``slots=True`` 减少内存占用，类似 Java 类没有动态字段。
    """

    id: str  # canonical UUID，如 "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    subject: str  # 短标题，必须非空且去除首尾空白
    description: str  # 详细描述，允许空字符串
    status: TaskStatus  # 只能是 "pending" | "in_progress" | "completed"
    owner: str | None  # 认领者（pending 为 None，其他状态非空）
    blocked_by: tuple[str, ...] = ()  # 依赖任务 ID（tuple = 不可变列表）

    def __post_init__(self) -> None:
        """dataclass 构造后的校验和标准化，类似 Java Bean Validation。

        这是什么：不可变对象创建后的一次性校验
        Java 类比：类似 @PostConstruct 或构造函数内的参数校验
        为什么需要：确保 Task 实例符合领域约束，拒绝非法状态
        """
        # 标准化 ID（校验 UUID 格式）
        object.__setattr__(self, "id", canonical_task_id(self.id))  # frozen=True 只能用 __setattr__
        # 标准化 subject（去除首尾空白，拒绝空字符串）
        object.__setattr__(self, "subject", _normalize_subject(self.subject))
        # 标准化 description（去除首尾空白，允许空字符串）
        object.__setattr__(self, "description", _normalize_description(self.description))
        # 校验 status 只能是三个合法值之一
        if self.status not in TASK_STATUSES:
            raise TaskStorageError("任务 status 只能是 pending、in_progress 或 completed")
        # 标准化 owner（去除空白，None 保持 None）
        normalized_owner = None if self.owner is None else normalize_owner(self.owner)
        object.__setattr__(self, "owner", normalized_owner)
        # 标准化依赖列表（去重，转为 tuple）
        object.__setattr__(self, "blocked_by", _normalize_dependencies(self.blocked_by))
        # 状态机约束 1：pending 任务不能有 owner
        if self.status == "pending" and normalized_owner is not None:
            raise TaskStorageError("pending 任务不能有 owner")
        # 状态机约束 2：in_progress 或 completed 任务必须有 owner
        if self.status != "pending" and normalized_owner is None:
            raise TaskStorageError("in_progress 或 completed 任务必须有 owner")


@dataclass(frozen=True, slots=True)
class CreateTaskInput:
    """创建任务的输入 DTO；ID、初始状态和 owner 不允许由模型指定。

    这是什么：create_task 工具的参数对象
    Java 类比：类似 CreateTaskRequest DTO
    为什么需要：限制模型只能指定业务字段，不能伪造 ID 和 owner

    ID 和 owner 由系统生成：
        - id：由存储层生成 UUID，保证唯一性
        - status：固定为 "pending"
        - owner：固定为 None（pending 任务未被认领）
    """

    subject: str  # 必填：任务标题
    description: str = ""  # 可选：详细描述（默认空字符串）
    blocked_by: tuple[str, ...] = ()  # 可选：依赖任务 ID 列表（默认无依赖）


@dataclass(frozen=True, slots=True)
class TaskCompletion:
    """完成结果：已完成任务，以及本次直接解锁的下游任务。

    这是什么：complete_task 的返回值对象
    Java 类比：类似 TaskCompletionResult DTO
    为什么需要：一次完成操作可能解锁多个下游任务，调用方需要知道这些变化

    示例：任务 B 和 C 都 blocked_by [A]，当 A 完成后：
        - task：A 的最新状态（status = "completed"）
        - unblocked：[B, C] 两个任务不再被阻塞（blocked_by 从 [A] 变为 []）
    """

    task: Task  # 刚完成的任务（status = "completed"）
    unblocked: tuple[Task, ...]  # 本次直接解锁的任务列表（blocked_by 减少了当前任务 ID）


class TaskStore(Protocol):
    """持久化任务仓库接口，类似 Java Repository interface。

    这是什么：Task 领域层的存储抽象
    Java 类比：类似 Spring Data 的 Repository<Task, String> 接口
    为什么需要：依赖倒置原则，领域层不依赖具体存储实现（JSON/SQLite/Redis）

    实现要求：
        - 所有方法必须是线程安全的（多进程访问需要文件锁）
        - create/claim/complete 必须原子执行（避免竞态条件）
        - DAG 校验必须在持久化前完成（防止存储损坏的图）

    工具层只依赖这些同步方法。第十二章使用 JSON 实现，后续章节可以换 SQLite，
    而五个工具和 Agent Loop 不需要跟着改变。
    """

    def create_task(self, value: CreateTaskInput) -> Task:
        """创建一个 pending 任务，系统生成 UUID 和初始状态。

        参数：
            value: 只包含 subject、description、blocked_by

        返回：
            新创建的 Task（id 由系统生成，status = "pending"，owner = None）

        异常：
            TaskGraphError: blocked_by 引用的 ID 不存在，或创建后形成环
            TaskStorageError: 磁盘写入失败
        """
        ...

    def get_task(self, task_id: str) -> Task:
        """按 canonical UUID 查询单个任务，只读不修改。

        参数：
            task_id: canonical UUID（小写，带连字符）

        返回：
            找到的 Task 对象

        异常：
            TaskNotFoundError: task_id 不存在
            TaskGraphError: task_id 格式非法
        """
        ...

    def list_tasks(self) -> tuple[Task, ...]:
        """列出所有任务，按 ID 稳定排序（用于创建依赖前查看全图）。

        返回：
            所有 Task 的不可变列表（tuple），按 id 字典序排序
        """
        ...

    def claim_task(self, task_id: str, owner: str) -> Task:
        """原子认领一个 pending 任务，状态转换为 in_progress。

        参数：
            task_id: 要认领的任务 ID
            owner: 认领者身份（来自 ToolContext.identity，不能伪造）

        返回：
            更新后的 Task（status = "in_progress"，owner = 传入值）

        异常：
            TaskNotFoundError: task_id 不存在
            TaskStateError: 任务不是 pending 状态（已被认领或已完成）
            TaskBlockedError: 任务仍有未完成的依赖（blocked_by 不为空）
            TaskStorageError: 并发冲突或磁盘写入失败
        """
        ...

    def complete_task(self, task_id: str, owner: str) -> TaskCompletion:
        """完成当前 identity 已认领的任务，返回解锁的下游任务。

        参数：
            task_id: 要完成的任务 ID
            owner: 完成者身份（必须与任务的 owner 一致）

        返回：
            TaskCompletion（包含完成的任务和解锁的下游任务列表）

        异常：
            TaskNotFoundError: task_id 不存在
            TaskStateError: 任务不是 in_progress 状态
            TaskOwnershipError: owner 与任务的 owner 不一致
            TaskStorageError: 磁盘写入失败
        """
        ...


def canonical_task_id(value: object) -> str:
    """只接受 UUID 的小写 canonical 文本，路径字符串无法进入存储层。

    这是什么：Task ID 的格式校验和标准化函数
    Java 类比：类似 UUID.fromString() 的严格校验
    为什么需要：防止路径穿越（如 "../etc/passwd"），只允许合法 UUID

    合法格式：xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx（小写，带连字符）
    示例：
        - 合法："f47ac10b-58cc-4372-a567-0e02b2c3d479"
        - 非法："F47AC10B-58CC-4372-A567-0E02B2C3D479"（大写）
        - 非法："f47ac10b58cc4372a5670e02b2c3d479"（无连字符）
        - 非法："../task.json"（路径穿越）
    """
    if not isinstance(value, str) or CANONICAL_UUID.fullmatch(value) is None:
        raise TaskGraphError("task id 必须是小写 canonical UUID")
    return value  # 已经是 canonical 格式，直接返回


def normalize_owner(value: object) -> str:
    """清理可信运行时 identity；空白 owner 不能进入状态机。

    这是什么：owner 字段的标准化函数
    Java 类比：类似 StringUtils.trimToNull() + 非空校验
    为什么需要：owner 来自 ToolContext.identity，必须去除空白并拒绝空值

    处理逻辑：
        - "  alice  " → "alice"（去除首尾空白）
        - "" → 抛 TaskOwnershipError（空字符串非法）
        - "   " → 抛 TaskOwnershipError（纯空白非法）
    """
    if not isinstance(value, str):
        raise TaskOwnershipError("任务 owner 必须是字符串")
    normalized = value.strip()  # 去除首尾空白（类似 Java trim()）
    if not normalized:
        raise TaskOwnershipError("任务 owner 不能为空")
    return normalized


def register_task_tools(registry: ToolRegistry, store: TaskStore) -> None:
    """把五个 Task 工具按固定顺序注册到同一个 ToolRegistry。

    这是什么：批量注册五个工具的便利函数
    Java 类比：类似命令总线批量注册 CommandHandler
    为什么需要：确保五个工具按稳定顺序注册，避免遗漏或重复

    注册顺序：
        1. create_task（创建任务）
        2. get_task（查询单个）
        3. list_tasks（列出所有）
        4. claim_task（认领任务）
        5. complete_task（完成任务）
    """
    registry.register(_create_task_definition(store))  # 1. 创建
    registry.register(
        _task_id_definition(
            "get_task",
            "按 canonical UUID 读取一个持久项目任务；只读，不修改 status 或 owner。",
            "read",  # 权限级别：只读
            store,
        )
    )  # 2. 查询
    registry.register(
        ToolDefinition(
            "list_tasks",
            "列出按 ID 稳定排序的完整项目任务图；创建依赖或认领任务前先查看。",
            {"type": "object", "properties": {}, "additionalProperties": False},  # 无参数
            "read",  # 权限级别：只读
            lambda _arguments, _context: _task_operation(
                lambda: tool_success(
                    _encode_payload({"tasks": [_task_payload(task) for task in store.list_tasks()]})
                )
            ),
            _validate_empty_input,
        )
    )  # 3. 列出
    registry.register(
        _task_id_definition(
            "claim_task",
            "原子认领一个 ready 的 pending 任务；owner 由运行时 identity 写入，不能传参伪造。",
            "write",  # 权限级别：写入（修改状态）
            store,
        )
    )  # 4. 认领
    registry.register(
        ToolDefinition(
            "complete_task",
            "完成当前 identity 已认领的任务，并返回本次直接解锁的 pending 任务。",
            _task_id_parameters(),
            "write",  # 权限级别：写入（修改状态）
            lambda arguments, context: _task_operation(
                lambda: _complete_result(
                    store.complete_task(str(arguments["task_id"]), normalize_owner(context.identity))
                )
            ),
            _validate_task_id_input,
        )
    )  # 5. 完成


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
