"""第十七章 SQLite 任务仓库：保存 DAG、认领令牌和有限租约。

Java 对照：``SqliteTaskStore`` 可以理解成一个直接使用 JDBC 的 Repository。
每个公开方法都会打开一个短事务；涉及状态修改时使用 ``BEGIN IMMEDIATE``，
让“查询 ready 任务”和“把它改成 in_progress”成为不可分割的一步。

本模块只使用 Python 标准库 ``sqlite3``。这样学习者可以先看清事务和 SQL，
不需要同时理解 ORM、Session、Entity 映射等额外概念。
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from ..features.tasks import (
    CreateTaskInput,
    Task,
    TaskBlockedError,
    TaskCompletion,
    TaskError,
    TaskGraphError,
    TaskNotFoundError,
    TaskStateError,
    TaskStorageError,
    canonical_task_id,
    normalize_owner,
)
from ..features.work_stealing import (
    TaskClaim,
    TaskClaimError,
    TaskLeaseExpiredError,
    canonical_claim_token,
)

IdGenerator = Callable[[], str]


class SqliteClock(Protocol):
    """可注入时钟，作用类似 Java 的 ``Clock`` 接口。"""

    def now(self) -> datetime:
        """返回当前 UTC 时间；测试可以用固定时钟控制租约是否过期。"""


class SystemUtcClock:
    """生产环境时钟，始终返回带 UTC 时区的 ``datetime``。"""

    def now(self) -> datetime:
        """读取一次系统 UTC 时间。"""
        return datetime.now(UTC)


class SqliteTaskStore:
    """把第十七章项目任务保存到 ``.agent_tutorial/tasks.sqlite3``。

    字段说明：
        ``_workspace_input``：调用方传入的工作区路径，只在真正操作时解析。
        ``_id_generator``：生成 Task UUID；测试可注入固定序列。
        ``_claim_token_generator``：生成一次性认领令牌，与 Task ID 分开负责。
        ``_clock``：决定租约开始和过期时间，类似 Java ``Clock``。
        ``_lease_duration``：一次认领最多持有任务多久，默认 60 秒。

    ``_`` 前缀是 Python 的“内部字段”约定，类似 Java ``private``，但不是语法级强制。
    """

    def __init__(
        self,
        workspace: str,
        *,
        id_generator: IdGenerator | None = None,
        claim_token_generator: IdGenerator | None = None,
        clock: SqliteClock | None = None,
        lease_duration_seconds: float = 60.0,
    ) -> None:
        """保存依赖配置；构造阶段不创建目录，也不连接数据库。"""
        if not isinstance(workspace, str) or not workspace.strip():
            raise TypeError("workspace 必须是非空字符串")
        if id_generator is not None and not callable(id_generator):
            raise TypeError("id_generator 必须可调用")
        if claim_token_generator is not None and not callable(claim_token_generator):
            raise TypeError("claim_token_generator 必须可调用")
        if clock is not None and not callable(getattr(clock, "now", None)):
            raise TypeError("clock 必须实现 now() 方法")
        if not isinstance(lease_duration_seconds, (int, float)) or isinstance(
            lease_duration_seconds, bool
        ):
            raise TypeError("lease_duration_seconds 必须是数字")
        if lease_duration_seconds <= 0:
            raise ValueError("lease_duration_seconds 必须大于 0")
        self._workspace_input = workspace
        self._id_generator = id_generator or (lambda: str(uuid.uuid4()))
        self._claim_token_generator = claim_token_generator or (lambda: str(uuid.uuid4()))
        self._clock = clock or SystemUtcClock()
        self._lease_duration = timedelta(seconds=float(lease_duration_seconds))

    @property
    def database_path(self) -> Path:
        """返回展示用数据库路径；真正访问前仍会重新做安全校验。"""
        return Path(self._workspace_input).resolve() / ".agent_tutorial" / "tasks.sqlite3"

    def create_task(self, value: CreateTaskInput) -> Task:
        """创建 pending 任务，并在同一事务中验证所有依赖都已存在。"""
        task_id = self._next_task_id()
        task = Task(task_id, value.subject, value.description, "pending", None, value.blocked_by)
        if task.id in task.blocked_by:
            raise TaskGraphError(f"任务 {task.id} 不能依赖自己")
        with self._transaction() as connection:
            if self._task_exists(connection, task.id):
                raise TaskGraphError(f"task id 已存在: {task.id}")
            missing = tuple(
                dependency
                for dependency in task.blocked_by
                if not self._task_exists(connection, dependency)
            )
            if missing:
                raise TaskGraphError(f"任务依赖不存在: {', '.join(missing)}")
            connection.execute(
                """
                INSERT INTO tasks(
                    id, subject, description, status, owner,
                    claim_token, lease_expires_at_utc
                ) VALUES (?, ?, ?, 'pending', NULL, NULL, NULL)
                """,
                (task.id, task.subject, task.description),
            )
            connection.executemany(
                """
                INSERT INTO task_dependencies(task_id, dependency_id, position)
                VALUES (?, ?, ?)
                """,
                tuple(
                    (task.id, dependency, position)
                    for position, dependency in enumerate(task.blocked_by)
                ),
            )
        return task

    def get_task(self, task_id: str) -> Task:
        """读取一个任务；读取前会把已经到期的旧租约释放回 pending。"""
        normalized_id = canonical_task_id(task_id)
        with self._transaction() as connection:
            self._release_expired(connection, self._now())
            return self._get_existing(connection, normalized_id)

    def list_tasks(self) -> tuple[Task, ...]:
        """按 SQLite 自增 sequence 返回稳定的创建顺序。"""
        with self._transaction() as connection:
            self._release_expired(connection, self._now())
            return self._load_tasks(connection)

    def claim_task(self, task_id: str, owner: str) -> TaskClaim:
        """由指定 owner 原子认领一个 ready 的 pending 任务。"""
        normalized_id = canonical_task_id(task_id)
        normalized_owner = normalize_owner(owner)
        with self._transaction() as connection:
            now = self._now()
            self._release_expired(connection, now)
            task = self._get_existing(connection, normalized_id)
            return self._claim(connection, task, normalized_owner, now)

    def claim_next(self, owner: str) -> TaskClaim | None:
        """按创建顺序认领第一个 ready 任务；没有候选任务时返回 ``None``。

        ``None`` 类似 Java 的 ``Optional.empty()``。Python 常用 ``T | None`` 表示
        “可能有一个 T，也可能没有值”。
        """
        normalized_owner = normalize_owner(owner)
        with self._transaction() as connection:
            now = self._now()
            self._release_expired(connection, now)
            tasks = self._load_tasks(connection)
            by_id = {task.id: task for task in tasks}
            for task in tasks:
                if task.status != "pending":
                    continue
                if any(by_id[dependency].status != "completed" for dependency in task.blocked_by):
                    continue
                return self._claim(connection, task, normalized_owner, now)
            return None

    def complete_task(self, task_id: str, owner: str, claim_token: str) -> TaskCompletion:
        """使用当前 owner 和 claim token 完成任务，并返回本次解锁的下游任务。"""
        normalized_id = canonical_task_id(task_id)
        normalized_owner = normalize_owner(owner)
        normalized_token = canonical_claim_token(claim_token)
        with self._transaction() as connection:
            now = self._now()
            row = connection.execute(
                """
                SELECT status, owner, claim_token, lease_expires_at_utc
                FROM tasks WHERE id = ?
                """,
                (normalized_id,),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"找不到任务: {normalized_id}")
            lease = _parse_time(row["lease_expires_at_utc"])
            if row["status"] == "in_progress" and lease is not None and now >= lease:
                self._release_expired(connection, now)
                # 在事务提交后抛出也可以，但这里抛出会回滚“释放租约”。因此先显式提交释放，
                # 再抛业务异常，让后续 worker 能重新认领。
                connection.commit()
                raise TaskLeaseExpiredError(f"任务 {normalized_id} 的认领租约已经过期")
            self._release_expired(connection, now)
            task = self._get_existing(connection, normalized_id)
            if task.status != "in_progress":
                raise TaskStateError(
                    f"任务 {normalized_id} 当前是 {task.status}，只有 in_progress 才能完成"
                )
            if task.owner != normalized_owner or row["claim_token"] != normalized_token:
                raise TaskClaimError(f"任务 {normalized_id} 的 owner 或 claim token 不匹配")
            changed = connection.execute(
                """
                UPDATE tasks
                SET status = 'completed', claim_token = NULL, lease_expires_at_utc = NULL
                WHERE id = ? AND status = 'in_progress' AND owner = ? AND claim_token = ?
                """,
                (normalized_id, normalized_owner, normalized_token),
            ).rowcount
            if changed != 1:
                raise TaskClaimError(f"任务 {normalized_id} 的当前认领已经发生变化")
            completed = Task(
                task.id,
                task.subject,
                task.description,
                "completed",
                task.owner,
                task.blocked_by,
            )
            tasks = self._load_tasks(connection)
            by_id = {candidate.id: candidate for candidate in tasks}
            unblocked = tuple(
                candidate
                for candidate in tasks
                if candidate.status == "pending"
                and normalized_id in candidate.blocked_by
                and all(by_id[dependency].status == "completed" for dependency in candidate.blocked_by)
            )
            return TaskCompletion(completed, unblocked)

    def _claim(
        self,
        connection: sqlite3.Connection,
        task: Task,
        owner: str,
        now: datetime,
    ) -> TaskClaim:
        """事务内部认领步骤；调用方必须已经持有 ``BEGIN IMMEDIATE`` 写锁。"""
        if task.status != "pending":
            raise TaskStateError(f"任务 {task.id} 当前是 {task.status}，只有 pending 才能认领")
        rows = connection.execute(
            """
            SELECT d.dependency_id, t.status
            FROM task_dependencies AS d
            JOIN tasks AS t ON t.id = d.dependency_id
            WHERE d.task_id = ?
            ORDER BY d.position
            """,
            (task.id,),
        ).fetchall()
        blocked_by = tuple(row["dependency_id"] for row in rows if row["status"] != "completed")
        if blocked_by:
            raise TaskBlockedError(task.id, blocked_by)
        token = self._next_claim_token()
        expires_at = now + self._lease_duration
        try:
            connection.execute(
                "INSERT INTO task_claim_tokens(token, task_id) VALUES (?, ?)",
                (token, task.id),
            )
        except sqlite3.IntegrityError as error:
            raise TaskStorageError("生成的 claim token 已经使用过，不能重复使用") from error
        changed = connection.execute(
            """
            UPDATE tasks
            SET status = 'in_progress', owner = ?, claim_token = ?, lease_expires_at_utc = ?
            WHERE id = ? AND status = 'pending' AND owner IS NULL
            """,
            (owner, token, _encode_time(expires_at), task.id),
        ).rowcount
        if changed != 1:
            raise TaskStateError(f"任务 {task.id} 未能原子认领，请重新读取任务状态")
        claimed = Task(task.id, task.subject, task.description, "in_progress", owner, task.blocked_by)
        return TaskClaim(claimed, token, expires_at)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """统一管理连接、建表、写事务、提交和回滚。

        ``with`` 是 Python 上下文管理器，类似 Java ``try-with-resources``。
        离开代码块时一定关闭连接；发生异常时一定回滚。
        """
        database = self._prepare_database_path()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            self._create_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            if connection.in_transaction:
                connection.commit()
        except TaskError:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise
        except (OSError, sqlite3.Error) as error:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise TaskStorageError("SQLite Task 操作失败") from error
        finally:
            if connection is not None:
                connection.close()

    def _prepare_database_path(self) -> Path:
        """创建状态目录，并拒绝符号链接、junction 和数据库硬链接逃逸。"""
        try:
            workspace = Path(self._workspace_input).resolve(strict=True)
            if not workspace.is_dir():
                raise TaskStorageError("workspace 不是目录")
            root = workspace / ".agent_tutorial"
            root.mkdir(exist_ok=True)
            if root.is_symlink() or not root.is_dir():
                raise TaskStorageError("SQLite Task 状态目录不安全")
            resolved_root = root.resolve(strict=True)
            if not _is_inside(workspace, resolved_root):
                raise TaskStorageError("SQLite Task 状态目录逃出了 workspace")
            database = resolved_root / "tasks.sqlite3"
            if database.exists():
                info = database.lstat()
                if database.is_symlink() or not database.is_file():
                    raise TaskStorageError("SQLite Task 数据库必须是普通文件")
                if info.st_nlink != 1:
                    raise TaskStorageError("SQLite Task 数据库不能是硬链接")
            return database
        except TaskError:
            raise
        except OSError as error:
            raise TaskStorageError("SQLite Task 状态目录无效") from error

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        """幂等创建三张表；相当于本章最小数据库 migration。"""
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                subject TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending', 'in_progress', 'completed')),
                owner TEXT,
                claim_token TEXT,
                lease_expires_at_utc TEXT
            );
            CREATE TABLE IF NOT EXISTS task_dependencies (
                task_id TEXT NOT NULL,
                dependency_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY(task_id, dependency_id),
                UNIQUE(task_id, position),
                FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY(dependency_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS task_claim_tokens (
                token TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            """
        )

    @staticmethod
    def _task_exists(connection: sqlite3.Connection, task_id: str) -> bool:
        """判断任务是否存在，不把整行数据加载进 Python。"""
        return connection.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is not None

    def _get_existing(self, connection: sqlite3.Connection, task_id: str) -> Task:
        """从当前事务快照读取一个任务，不存在时抛稳定领域异常。"""
        for task in self._load_tasks(connection):
            if task.id == task_id:
                return task
        raise TaskNotFoundError(f"找不到任务: {task_id}")

    @staticmethod
    def _load_tasks(connection: sqlite3.Connection) -> tuple[Task, ...]:
        """一次读取完整 DAG，并把依赖按原始位置装回不可变 ``Task``。"""
        dependencies: dict[str, list[str]] = {}
        for row in connection.execute(
            "SELECT task_id, dependency_id FROM task_dependencies ORDER BY task_id, position"
        ):
            dependencies.setdefault(row["task_id"], []).append(row["dependency_id"])
        rows = connection.execute(
            "SELECT id, subject, description, status, owner FROM tasks ORDER BY sequence"
        ).fetchall()
        return tuple(
            Task(
                row["id"],
                row["subject"],
                row["description"],
                row["status"],
                row["owner"],
                tuple(dependencies.get(row["id"], ())),
            )
            for row in rows
        )

    @staticmethod
    def _release_expired(connection: sqlite3.Connection, now: datetime) -> None:
        """把 ``lease <= now`` 的 in_progress 任务恢复成可认领状态。"""
        connection.execute(
            """
            UPDATE tasks
            SET status = 'pending', owner = NULL, claim_token = NULL, lease_expires_at_utc = NULL
            WHERE status = 'in_progress'
              AND lease_expires_at_utc IS NOT NULL
              AND lease_expires_at_utc <= ?
            """,
            (_encode_time(now),),
        )

    def _next_task_id(self) -> str:
        """生成并规范化 Task UUID，测试替身也不能绕过领域校验。"""
        try:
            return canonical_task_id(self._id_generator())
        except TaskError as error:
            raise TaskGraphError("id_generator 返回的不是 canonical UUID") from error

    def _next_claim_token(self) -> str:
        """生成一次性 canonical UUID claim token。"""
        try:
            return canonical_claim_token(self._claim_token_generator())
        except TaskError as error:
            raise TaskStorageError("claim_token_generator 返回了无效 UUID") from error

    def _now(self) -> datetime:
        """读取并复制 UTC 时间，拒绝无时区或无效的测试时钟结果。"""
        value = self._clock.now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TaskStorageError("Work stealing 时钟必须返回带时区的 datetime")
        return value.astimezone(UTC)


def _encode_time(value: datetime) -> str:
    """把 UTC 时间编码为可按文本比较的固定 ISO-8601 格式。"""
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: object) -> datetime | None:
    """把数据库租约文本还原成 UTC 时间；NULL 对应 ``None``。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TaskStorageError("数据库中的 lease_expires_at_utc 不是字符串")
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError as error:
        raise TaskStorageError("数据库中的 lease_expires_at_utc 格式无效") from error


def _is_inside(parent: Path, child: Path) -> bool:
    """判断 child 是否位于 parent 内；Windows 路径比较使用 ``normcase``。"""
    try:
        return os.path.commonpath((os.path.normcase(parent), os.path.normcase(child))) == os.path.normcase(
            parent
        )
    except ValueError:
        return False
