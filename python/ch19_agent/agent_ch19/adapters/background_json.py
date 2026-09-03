"""后台 Job 的 JSON Repository。

这是什么：后台任务的文件存储实现，每个任务保存为独立的 JSON 文件
Java 类比：这是一个文件版 ``BackgroundJobRepository``，类似 Spring Data Repository
为什么需要：后台任务需要持久化，进程重启后能恢复状态；每次写入都在同目录
          临时文件中完成 ``flush + fsync``，最后用原子替换发布，避免半截 JSON
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from ..core.tools import ToolResult
from ..features.background import BackgroundError, BackgroundJob, BackgroundJobStore

_LOCKS: dict[str, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


class JsonBackgroundJobStore(BackgroundJobStore):
    """把每个 Job 保存到 ``workspace/.agent_tutorial/background/<uuid>.json``。

    这是什么：后台任务存储的文件实现，每个任务一个 JSON 文件
    Java 类比：类似 JpaRepository<BackgroundJob, String>，但用文件代替数据库
    为什么需要：支持后台任务持久化，进程重启后能查询和恢复任务状态
    """

    def __init__(self, workspace: str, *, id_generator: Callable[[], str] | None = None) -> None:
        """初始化存储，指定工作目录和 ID 生成器。

        参数：
            workspace: 工作目录根路径
            id_generator: 任务 ID 生成函数，默认生成 UUID
        """
        self.workspace = Path(workspace).resolve()  # 转为绝对路径
        self.id_generator = id_generator or (lambda: str(uuid.uuid4()))  # 默认 UUID

    def create_running(
        self, job_id: str, source_tool_call_id: str, tool_name: str
    ) -> BackgroundJob:
        """创建并持久化 running Job。

        这是什么：创建新的后台任务并保存到文件
        Java 类比：repository.save(new BackgroundJob(...))
        为什么需要：工具提交后台任务时，立即持久化状态防止丢失

        参数：
            job_id: 任务唯一 ID
            source_tool_call_id: 触发任务的工具调用 ID
            tool_name: 工具名称
        """
        job = BackgroundJob(job_id, source_tool_call_id, tool_name, "running", None)
        with self._locked() as directory:  # 加锁保护并发写
            path = directory / f"{job.id}.json"
            if path.exists():  # 防止 ID 冲突
                raise BackgroundError("background_storage_error", "后台任务 ID 已存在")
            self._write(path, job)  # 原子写入
        return job

    def finish_running(self, job_id: str, status: str, result: ToolResult) -> BackgroundJob | None:
        """仅允许 running -> 终态；竞争写者拿不到已完成 Job。

        这是什么：更新任务状态为完成（success/failed/interrupted）
        Java 类比：类似乐观锁更新，if (job.status == RUNNING) { update(...); }
        为什么需要：保证状态机的线性转换，防止并发更新导致状态混乱

        参数：
            job_id: 任务 ID
            status: 终态（success/failed/interrupted）
            result: 工具执行结果

        返回：
            BackgroundJob: 更新后的任务（成功）
            None: 任务已不是 running 状态（竞争失败）
        """
        with self._locked() as directory:
            job = self._read(directory / f"{job_id}.json")
            if job.status != "running":  # 已被其他线程完成
                return None
            finished = BackgroundJob(job.id, job.source_tool_call_id, job.tool_name, status, result)
            self._write(directory / f"{job.id}.json", finished)  # 原子更新
            return finished

    def interrupt_running(self) -> tuple[BackgroundJob, ...]:
        """把重启时遗留的 running Job 一次性迁移为 interrupted。

        这是什么：启动时清理孤儿任务，将遗留的 running 状态标记为中断
        Java 类比：@PostConstruct void init() { cleanup(); }
        为什么需要：进程重启后，原来 running 的任务已无法继续，必须标记为中断

        返回：
            被标记为 interrupted 的任务列表
        """
        interrupted: list[BackgroundJob] = []
        with self._locked(create=False) as directory:
            for path in self._paths(directory):
                job = self._read(path)
                if job.status == "running":  # 遗留的 running 状态
                    result = ToolResult(
                        "后台任务因进程重启而中断", True, "background_execution_error"
                    )
                    job = BackgroundJob(
                        job.id, job.source_tool_call_id, job.tool_name, "interrupted", result
                    )
                    self._write(path, job)  # 更新为 interrupted
                    interrupted.append(job)
        return tuple(interrupted)

    def get_job(self, job_id: str) -> BackgroundJob:
        """读取指定 Job；不存在时返回稳定错误码。"""
        with self._locked(create=False) as directory:
            path = directory / f"{job_id}.json"
            if not path.exists():
                raise BackgroundError("background_job_not_found", f"找不到后台任务: {job_id}")
            return self._read(path)

    def list_jobs(self) -> tuple[BackgroundJob, ...]:
        """按文件名排序读取全部 Job。"""
        with self._locked(create=False) as directory:
            return tuple(self._read(path) for path in self._paths(directory))

    @contextmanager
    def _locked(self, *, create: bool = True) -> Iterator[Path]:
        """取得进程内锁；文件锁由同一进程快照负责，确保操作串行。"""
        if not self.workspace.exists() or not self.workspace.is_dir():
            raise BackgroundError("background_storage_error", "workspace 不是目录")
        root = self.workspace / ".agent_tutorial"
        directory = root / "background"
        if create:
            root.mkdir(exist_ok=True)
            directory.mkdir(exist_ok=True)
        elif not directory.exists():
            yield directory
            return
        if root.is_symlink() or directory.is_symlink():
            raise BackgroundError("background_storage_error", "后台存储目录不能是符号链接")
        key = str(directory)
        with _LOCK_GUARD:
            lock = _LOCKS.setdefault(key, threading.RLock())
        with lock:
            yield directory

    def _paths(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(directory.glob("*.json"), key=lambda path: path.name)

    def _read(self, path: Path) -> BackgroundJob:
        try:
            if path.is_symlink() or not path.is_file() or path.name != f"{path.stem}.json":
                raise ValueError("文件路径无效")
            payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
            expected = {"id", "source_tool_call_id", "tool_name", "status", "result"}
            if not isinstance(payload, dict) or set(payload) != expected:
                raise ValueError("JSON 字段不完整")
            raw = payload["result"]
            result = None
            if raw is not None:
                if not isinstance(raw, dict) or set(raw) != {"content", "is_error", "error_code"}:
                    raise ValueError("result 字段无效")
                result = ToolResult(str(raw["content"]), bool(raw["is_error"]), raw["error_code"])
            job = BackgroundJob(
                str(payload["id"]),
                str(payload["source_tool_call_id"]),
                str(payload["tool_name"]),
                str(payload["status"]),
                result,
            )
            if path.name != f"{job.id}.json":
                raise ValueError("文件名和 payload id 不一致")
            return job
        except BackgroundError:
            raise
        except Exception as error:
            raise BackgroundError(
                "background_storage_error", f"后台任务文件无效: {path.name}"
            ) from error

    @staticmethod
    def _write(path: Path, job: BackgroundJob) -> None:
        payload = {
            "id": job.id,
            "source_tool_call_id": job.source_tool_call_id,
            "tool_name": job.tool_name,
            "status": job.status,
            "result": None
            if job.result is None
            else {
                "content": job.result.content,
                "is_error": job.result.is_error,
                "error_code": job.result.error_code,
            },
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception as error:
            raise BackgroundError("background_storage_error", "后台任务持久化失败") from error
        finally:
            temporary.unlink(missing_ok=True)
