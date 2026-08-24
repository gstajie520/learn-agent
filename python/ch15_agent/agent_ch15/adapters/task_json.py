"""第十二章 JSON TaskStore：整图锁、严格重建和原子文件替换。

Java 对照：``JsonTaskStore`` 是 Repository 的基础设施实现。每个公开方法都像一个
小事务：取得整张图的锁，在锁内重新读取全部 JSON，验证 DAG，再执行一次状态迁移。
它不是数据库事务，但可以保证合规 writer 之间不会同时认领同一个 Task。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from ..features.tasks import (
    CreateTaskInput,
    Task,
    TaskBlockedError,
    TaskCompletion,
    TaskError,
    TaskGraphError,
    TaskNotFoundError,
    TaskOwnershipError,
    TaskStateError,
    TaskStorageError,
    canonical_task_id,
    normalize_owner,
)

AtomicReplace = Callable[[Path, bytes], None]
IdGenerator = Callable[[], str]
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class JsonTaskStore:
    """把任务图保存到 ``workspace/.agent_tutorial/.tasks``。

    字段说明：
        ``_workspace_input``：调用方传入的 workspace，操作时每次重新 resolve。
        ``_id_generator``：默认生成 UUID v4；测试可注入固定序列。
        ``_atomic_replace``：默认同目录临时写入后 ``os.replace``；测试可注入失败点。
    """

    def __init__(
        self,
        workspace: str,
        *,
        id_generator: IdGenerator | None = None,
        atomic_replace: AtomicReplace | None = None,
    ) -> None:
        if not isinstance(workspace, str) or not workspace.strip():
            raise TypeError("workspace 必须是非空字符串")
        if id_generator is not None and not callable(id_generator):
            raise TypeError("id_generator 必须可调用")
        if atomic_replace is not None and not callable(atomic_replace):
            raise TypeError("atomic_replace 必须可调用")
        self._workspace_input = workspace
        self._id_generator = id_generator or (lambda: str(uuid.uuid4()))
        self._atomic_replace = atomic_replace or _atomic_replace

    def create_task(self, value: CreateTaskInput) -> Task:
        """在锁内生成 ID、校验整张候选图，然后原子写入新任务。"""
        paths = self._prepare_paths(create=True)
        if paths is None:
            raise TaskStorageError("无法创建 Task 存储目录")
        with self._locked(paths):
            graph = self._load_graph(paths)
            task_id = self._generated_id()
            if task_id in graph:
                raise TaskGraphError(f"task id 已存在: {task_id}")
            task = Task(
                task_id,
                value.subject,
                value.description,
                "pending",
                None,
                value.blocked_by,
            )
            candidate = dict(graph)
            candidate[task.id] = task
            _validate_graph(candidate)
            self._write_task(paths, task)
            return task

    def get_task(self, task_id: str) -> Task:
        """读取一致的整图快照，再从中返回目标任务。"""
        normalized = canonical_task_id(task_id)
        paths = self._prepare_paths(create=False)
        if paths is None:
            raise TaskNotFoundError(f"找不到任务: {normalized}")
        with self._locked(paths):
            task = self._load_graph(paths).get(normalized)
            if task is None:
                raise TaskNotFoundError(f"找不到任务: {normalized}")
            return task

    def list_tasks(self) -> tuple[Task, ...]:
        """返回按 ID 排序的完整不可变任务集合；空读不会创建存储目录。"""
        paths = self._prepare_paths(create=False)
        if paths is None:
            return ()
        with self._locked(paths):
            return tuple(sorted(self._load_graph(paths).values(), key=lambda task: task.id))

    def claim_task(self, task_id: str, owner: str) -> Task:
        """把 ready pending 任务原子迁移为 in_progress。"""
        normalized_id = canonical_task_id(task_id)
        normalized_owner = normalize_owner(owner)
        paths = self._prepare_paths(create=False)
        if paths is None:
            raise TaskNotFoundError(f"找不到任务: {normalized_id}")
        with self._locked(paths):
            graph = self._load_graph(paths)
            task = graph.get(normalized_id)
            if task is None:
                raise TaskNotFoundError(f"找不到任务: {normalized_id}")
            if task.status != "pending":
                raise TaskStateError(f"任务 {normalized_id} 必须是 pending 才能认领")
            blocked_by = tuple(
                dependency
                for dependency in task.blocked_by
                if graph.get(dependency) is None or graph[dependency].status != "completed"
            )
            if blocked_by:
                raise TaskBlockedError(task.id, blocked_by)
            claimed = Task(
                task.id,
                task.subject,
                task.description,
                "in_progress",
                normalized_owner,
                task.blocked_by,
            )
            self._write_task(paths, claimed)
            return claimed

    def complete_task(self, task_id: str, owner: str) -> TaskCompletion:
        """只有当前 owner 能完成，并只报告本次直接解锁的下游任务。"""
        normalized_id = canonical_task_id(task_id)
        normalized_owner = normalize_owner(owner)
        paths = self._prepare_paths(create=False)
        if paths is None:
            raise TaskNotFoundError(f"找不到任务: {normalized_id}")
        with self._locked(paths):
            graph = self._load_graph(paths)
            task = graph.get(normalized_id)
            if task is None:
                raise TaskNotFoundError(f"找不到任务: {normalized_id}")
            if task.status != "in_progress":
                raise TaskStateError(f"任务 {normalized_id} 必须是 in_progress 才能完成")
            if task.owner != normalized_owner:
                raise TaskOwnershipError(f"任务 {normalized_id} 当前属于 {task.owner}")
            completed = Task(
                task.id,
                task.subject,
                task.description,
                "completed",
                task.owner,
                task.blocked_by,
            )
            candidate = dict(graph)
            candidate[completed.id] = completed
            unblocked = tuple(
                sorted(
                    (
                        dependent
                        for dependent in candidate.values()
                        if dependent.status == "pending"
                        and completed.id in dependent.blocked_by
                        and all(
                            candidate[item].status == "completed" for item in dependent.blocked_by
                        )
                    ),
                    key=lambda value: value.id,
                )
            )
            self._write_task(paths, completed)
            return TaskCompletion(completed, unblocked)

    def _prepare_paths(self, *, create: bool) -> _TaskPaths | None:
        """解析并复查 workspace/root/tasks，拒绝 symlink 或 junction 逃逸。"""
        try:
            workspace = Path(self._workspace_input).resolve(strict=True)
            if not workspace.is_dir():
                raise TaskStorageError("workspace 不是目录")
            root = workspace / ".agent_tutorial"
            tasks = root / ".tasks"
            if create:
                root.mkdir(exist_ok=True)
                self._validate_directory(workspace, root, workspace)
                tasks.mkdir(exist_ok=True)
            else:
                if not root.exists():
                    return None
                self._validate_directory(workspace, root, workspace)
                if not tasks.exists():
                    return None
            self._validate_directory(workspace, tasks, root.resolve(strict=True))
            lock = root / ".tasks.lock"
            if lock.exists() and lock.is_symlink():
                raise TaskStorageError("Task 锁文件不能是符号链接")
            return _TaskPaths(workspace, root, tasks, lock)
        except TaskError:
            raise
        except OSError as error:
            raise TaskStorageError(f"Task 存储根目录无效: {error}") from error

    @staticmethod
    def _validate_directory(workspace: Path, path: Path, parent: Path) -> None:
        resolved = path.resolve(strict=True)
        if not resolved.is_dir() or not resolved.is_relative_to(workspace):
            raise TaskStorageError("Task 存储目录逃出了 workspace")
        if not resolved.is_relative_to(parent):
            raise TaskStorageError("Task 存储目录不在预期父目录内")

    @contextmanager
    def _locked(self, paths: _TaskPaths) -> Iterator[None]:
        """进程内 RLock 加操作系统文件锁，保护整张任务图。"""
        key = str(paths.tasks.resolve(strict=True))
        with _process_lock(key):
            paths.lock.parent.mkdir(exist_ok=True)
            try:
                with paths.lock.open("a+b") as handle:
                    _acquire_file_lock(handle)
                    try:
                        self._validate_directory(paths.workspace, paths.root, paths.workspace)
                        self._validate_directory(
                            paths.workspace, paths.tasks, paths.root.resolve(strict=True)
                        )
                        yield
                    finally:
                        _release_file_lock(handle)
            except TaskError:
                raise
            except OSError as error:
                raise TaskStorageError(f"Task 存储操作失败: {error}") from error

    def _load_graph(self, paths: _TaskPaths) -> dict[str, Task]:
        graph: dict[str, Task] = {}
        try:
            entries = sorted(paths.tasks.glob("*.json"), key=lambda path: path.name)
        except OSError as error:
            raise TaskStorageError("无法列出 Task 文件") from error
        for path in entries:
            try:
                if path.is_symlink() or not path.is_file():
                    raise TaskStorageError("Task 文件不是普通文件")
                # ``errors='strict'`` 明确拒绝坏 UTF-8，不用替换字符偷偷恢复。
                payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
                task = _parse_stored_task(payload)
            except TaskError as error:
                raise TaskStorageError(f"Task 文件无效: {path.name}: {error}") from error
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise TaskStorageError(f"Task 文件无效: {path.name}") from error
            if path.name != f"{task.id}.json":
                raise TaskStorageError(f"Task 文件名和 payload id 不一致: {path.name}")
            if task.id in graph:
                raise TaskStorageError(f"Task ID 重复: {task.id}")
            graph[task.id] = task
        _validate_graph(graph)
        return graph

    def _write_task(self, paths: _TaskPaths, task: Task) -> None:
        try:
            self._atomic_replace(paths.tasks / f"{task.id}.json", _serialize_task(task))
        except TaskError:
            raise
        except Exception as error:
            raise TaskStorageError(f"Task 文件持久化失败: {task.id}") from error

    def _generated_id(self) -> str:
        try:
            generated = self._id_generator()
        except Exception as error:
            raise TaskGraphError("Task ID 生成器执行失败") from error
        try:
            return canonical_task_id(generated)
        except TaskError as error:
            raise TaskGraphError("生成的 Task ID 必须是 canonical UUID") from error


class _TaskPaths:
    """内部路径 DTO；普通类足够，因为只在适配器私有方法间传递。"""

    def __init__(self, workspace: Path, root: Path, tasks: Path, lock: Path) -> None:
        self.workspace = workspace
        self.root = root
        self.tasks = tasks
        self.lock = lock


def _parse_stored_task(value: object) -> Task:
    expected = {"blocked_by", "description", "id", "owner", "status", "subject"}
    if not isinstance(value, dict) or set(value) != expected:
        raise TaskStorageError("Task JSON 必须恰好包含六个字段")
    blocked_by = value["blocked_by"]
    if not isinstance(blocked_by, list) or not all(isinstance(item, str) for item in blocked_by):
        raise TaskStorageError("Task blocked_by 必须是字符串数组")
    if not isinstance(value["id"], str) or not isinstance(value["subject"], str):
        raise TaskStorageError("Task id/subject 字段类型错误")
    if not isinstance(value["description"], str):
        raise TaskStorageError("Task description 字段类型错误")
    owner = value["owner"]
    if owner is not None and not isinstance(owner, str):
        raise TaskStorageError("Task owner 字段类型错误")
    status = value["status"]
    if status not in {"pending", "in_progress", "completed"}:
        raise TaskStorageError("Task status 字段值错误")
    return Task(
        value["id"],
        value["subject"],
        value["description"],
        status,
        owner,
        tuple(blocked_by),
    )


def _serialize_task(task: Task) -> bytes:
    payload = {
        "blocked_by": list(task.blocked_by),
        "description": task.description,
        "id": task.id,
        "owner": task.owner,
        "status": task.status,
        "subject": task.subject,
    }
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _validate_graph(graph: dict[str, Task]) -> None:
    """先检查缺边和自依赖，再用 DFS 检查整张图没有环。"""
    for task in graph.values():
        for dependency in task.blocked_by:
            if dependency == task.id:
                raise TaskGraphError(f"任务 {task.id} 不能依赖自己")
            if dependency not in graph:
                raise TaskGraphError(f"任务 {task.id} 的依赖不存在: {dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise TaskGraphError(f"任务图存在环，涉及 {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph[task_id].blocked_by:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)


def _atomic_replace(path: Path, content: bytes) -> None:
    """同目录临时文件先 flush/fsync，再用 os.replace 原子发布。"""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _process_lock(key: str) -> Iterator[None]:
    with _PROCESS_LOCKS_GUARD:
        lock = _PROCESS_LOCKS.setdefault(key, threading.RLock())
    with lock:
        yield


def _acquire_file_lock(handle: BinaryIO) -> None:
    """Windows 使用 msvcrt，Unix 使用 fcntl；循环等待保持调用语义简单。"""
    if os.name == "nt":
        import msvcrt

        while True:
            try:
                handle.seek(0)
                if handle.read(1) == b"":
                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.01)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]


def _release_file_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
