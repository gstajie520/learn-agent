"""Cron durable 状态的 JSON Repository。

Java 类比：一个带文件锁的 Repository。``state.json`` 同时保存计划和 outbox，
这样 one-shot 删除计划与写入事件要么一起成功，要么旧快照完整保留。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from ..features.cron import (
    CronError,
    CronEvent,
    CronJob,
    CronJobNotFoundError,
    CronStorageError,
    CronStore,
    canonical_cron_id,
    next_cron_occurrence,
    validate_cron_expression,
    validate_cron_timezone,
)

_LOCKS: dict[str, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()


class JsonCronStore(CronStore):
    """持久化到 ``workspace/.agent_tutorial/cron/state.json``。"""

    def __init__(self, workspace: str, *, id_generator: Callable[[], str] | None = None, event_id_generator: Callable[[], str] | None = None, outbox_capacity: int = 100) -> None:
        if outbox_capacity <= 0:
            raise ValueError("outbox_capacity 必须大于 0")
        self.workspace = Path(workspace).resolve()
        self.id_generator = id_generator or (lambda: str(uuid.uuid4()))
        self.event_id_generator = event_id_generator or (lambda: str(uuid.uuid4()))
        self.outbox_capacity = outbox_capacity
        self._session_jobs: dict[str, CronJob] = {}
        self._session_outbox: dict[str, CronEvent] = {}
        self._leader = False

    def schedule_cron(self, input: Mapping[str, object]) -> CronJob:
        """校验输入、计算下一槽位并保存计划。"""
        cron = validate_cron_expression(str(input["cron"]))
        timezone = validate_cron_timezone(str(input["timezone"]))
        prompt = str(input["prompt"]).strip()
        identity = str(input["identity"]).strip()
        now = _utc(input["now_utc"])
        recurring = input["recurring"]
        durable = input["durable"]
        if not prompt or not identity or not isinstance(recurring, bool) or not isinstance(durable, bool):
            raise CronStorageError("Cron 输入字段无效")
        job = CronJob(canonical_cron_id(str(self.id_generator())), cron, prompt, timezone, recurring, durable, identity, next_cron_occurrence(cron, timezone, now), None)
        with self._locked(create=True) as paths:
            jobs, events = self._load(paths)
            if durable:
                if any(item.id == job.id for item in jobs):
                    raise CronStorageError("Cron job id 已存在")
                self._write(paths, {"version": 1, "jobs": [*_serialize_jobs(jobs), _serialize_job(job)], "outbox": [_serialize_event(event) for event in events]})
            else:
                self._session_jobs[job.id] = job
        return job

    def get_job(self, job_id: str) -> CronJob:
        """读取 durable 或当前进程 session 计划。"""
        normalized = canonical_cron_id(job_id)
        with self._locked(create=False) as paths:
            jobs, _ = self._load(paths)
            for job in jobs:
                if job.id == normalized:
                    return job
            if normalized in self._session_jobs:
                return self._session_jobs[normalized]
        raise CronJobNotFoundError(f"找不到 Cron job: {normalized}")

    def list_jobs(self, include_durable: bool = True) -> tuple[CronJob, ...]:
        """返回按下一槽位和 ID 排序的计划。"""
        with self._locked(create=False) as paths:
            durable_jobs, _ = self._load(paths)
            jobs = ([*durable_jobs] if include_durable else []) + list(self._session_jobs.values())
        return tuple(sorted(jobs, key=lambda item: (item.next_run_at_utc, item.id)))

    def tick(self, now_utc: dt.datetime, include_durable: bool = True) -> tuple[CronEvent, ...]:
        """原子生成到期事件并推进或删除计划。"""
        now = _utc(now_utc)
        with self._locked(create=True) as paths:
            stored_jobs, stored_events = self._load(paths)
            durable_jobs = {job.id: job for job in stored_jobs}
            session_jobs = dict(self._session_jobs)
            durable_outbox = {event.event_id: event for event in stored_events}
            session_outbox = dict(self._session_outbox)
            jobs = list(durable_jobs.values()) if include_durable else []
            jobs.extend(session_jobs.values())
            known = set(durable_outbox) | set(session_outbox)
            if len(known) >= self.outbox_capacity:
                return ()
            created: list[CronEvent] = []
            for job in sorted((item for item in jobs if item.next_run_at_utc <= now), key=lambda item: (item.next_run_at_utc, item.id)):
                if len(known) + len(created) >= self.outbox_capacity:
                    break
                event_id = canonical_cron_id(str(self.event_id_generator()))
                if event_id in known:
                    raise CronStorageError("Cron event id 已存在")
                event = CronEvent(event_id, job.id, job.identity, job.prompt, job.timezone, job.durable, job.next_run_at_utc, context_identity=job.identity, idempotency_key=event_id)
                (durable_outbox if job.durable else session_outbox)[event_id] = event
                known.add(event_id)
                created.append(event)
                if job.recurring:
                    updated = CronJob(job.id, job.cron, job.prompt, job.timezone, job.recurring, job.durable, job.identity, next_cron_occurrence(job.cron, job.timezone, now), job.next_run_at_utc)
                    (durable_jobs if job.durable else session_jobs)[job.id] = updated
                elif job.durable:
                    durable_jobs.pop(job.id, None)
                else:
                    session_jobs.pop(job.id, None)
            self._session_jobs = session_jobs
            self._session_outbox = session_outbox
            if any(event.durable for event in created):
                self._write(paths, {"version": 1, "jobs": [_serialize_job(job) for job in durable_jobs.values()], "outbox": [_serialize_event(event) for event in durable_outbox.values()]})
            return tuple(created)

    def pending_events(self, include_durable: bool = True) -> tuple[CronEvent, ...]:
        """读取尚未确认的 outbox。"""
        with self._locked(create=False) as paths:
            _, stored_events = self._load(paths)
            events = ([*stored_events] if include_durable else []) + list(self._session_outbox.values())
        return tuple(sorted(events, key=lambda item: (item.slot_at_utc, item.event_id)))

    def ack_event(self, event_id: str) -> bool:
        """删除一个 pending event，重复确认返回 False。"""
        normalized = canonical_cron_id(event_id)
        if self._session_outbox.pop(normalized, None) is not None:
            return True
        with self._locked(create=False) as paths:
            stored_jobs, stored_events = self._load(paths)
            if not any(event.event_id == normalized for event in stored_events):
                return False
            self._write(paths, {"version": 1, "jobs": [_serialize_job(job) for job in stored_jobs], "outbox": [_serialize_event(event) for event in stored_events if event.event_id != normalized]})
            return True

    def try_acquire_leader(self) -> bool:
        """通过独占 marker 文件争夺 durable scheduler leader。"""
        if self._leader:
            return False
        root = self.workspace / ".agent_tutorial" / "cron"
        root.mkdir(parents=True, exist_ok=True)
        marker = root / "leader.lock"
        try:
            with marker.open("x", encoding="ascii") as handle:
                handle.write("leader")
        except FileExistsError:
            return False
        self._leader = True
        return True

    def release_leader(self) -> None:
        """释放独占 leader marker。"""
        self._leader = False
        (self.workspace / ".agent_tutorial" / "cron" / "leader.lock").unlink(missing_ok=True)

    @contextmanager
    def _locked(self, *, create: bool) -> Iterator[Path]:
        """取得 workspace 内的进程锁，并拒绝 Cron 目录符号链接。"""
        if not self.workspace.is_dir():
            raise CronStorageError("workspace 不是目录")
        root = self.workspace / ".agent_tutorial"
        directory = root / "cron"
        if create:
            root.mkdir(exist_ok=True)
            directory.mkdir(exist_ok=True)
        elif not directory.exists():
            yield directory
            return
        if root.is_symlink() or directory.is_symlink():
            raise CronStorageError("Cron 存储目录不能是符号链接")
        with _LOCK_GUARD:
            lock = _LOCKS.setdefault(str(directory), threading.RLock())
        with lock:
            yield directory

    def _load(self, paths: Path) -> tuple[list[CronJob], list[CronEvent]]:
        state_path = paths / "state.json"
        if not state_path.exists():
            return [], []
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8", errors="strict"))
            if not isinstance(payload, dict) or set(payload) != {"version", "jobs", "outbox"} or payload["version"] != 1:
                raise ValueError("state schema 无效")
            jobs = [_parse_job(item) for item in payload["jobs"]]
            events = [_parse_event(item) for item in payload["outbox"]]
            if any(not job.durable for job in jobs) or any(not event.durable for event in events):
                raise ValueError("durable state 不能包含 session 记录")
            return jobs, events
        except CronError:
            raise
        except Exception as error:
            raise CronStorageError("Cron state 无效") from error

    @staticmethod
    def _write(paths: Path, payload: Mapping[str, object]) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".state.", suffix=".tmp", dir=paths)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, paths / "state.json")
        except Exception as error:
            raise CronStorageError("Cron state 持久化失败") from error
        finally:
            temporary.unlink(missing_ok=True)


def _utc(value: object) -> dt.datetime:
    """把输入转换为带 UTC 语义的时间。"""
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise CronStorageError("Cron 时间必须带时区")
    return value.astimezone(dt.UTC)


def _serialize_jobs(jobs: list[CronJob]) -> list[dict[str, object]]:
    return [_serialize_job(job) for job in jobs]


def _serialize_job(job: CronJob) -> dict[str, object]:
    return {"id": job.id, "cron": job.cron, "prompt": job.prompt, "timezone": job.timezone, "recurring": job.recurring, "durable": job.durable, "identity": job.identity, "next_run_at_utc": _iso(job.next_run_at_utc), "last_slot_at_utc": None if job.last_slot_at_utc is None else _iso(job.last_slot_at_utc)}


def _serialize_event(event: CronEvent) -> dict[str, object]:
    return {"event_id": event.event_id, "job_id": event.job_id, "identity": event.identity, "prompt": event.prompt, "timezone": event.timezone, "durable": event.durable, "slot_at_utc": _iso(event.slot_at_utc)}


def _parse_job(value: object) -> CronJob:
    if not isinstance(value, dict):
        raise CronStorageError("Cron job JSON 无效")
    last = None if value["last_slot_at_utc"] is None else _parse_time(value["last_slot_at_utc"])
    return CronJob(str(value["id"]), validate_cron_expression(str(value["cron"])), str(value["prompt"]), validate_cron_timezone(str(value["timezone"])), bool(value["recurring"]), bool(value["durable"]), str(value["identity"]), _parse_time(value["next_run_at_utc"]), last)


def _parse_event(value: object) -> CronEvent:
    if not isinstance(value, dict):
        raise CronStorageError("Cron event JSON 无效")
    event_id = canonical_cron_id(str(value["event_id"]))
    job_id = canonical_cron_id(str(value["job_id"]))
    return CronEvent(event_id, job_id, str(value["identity"]), str(value["prompt"]), validate_cron_timezone(str(value["timezone"])), bool(value["durable"]), _parse_time(value["slot_at_utc"]), context_identity=str(value["identity"]), idempotency_key=event_id)


def _parse_time(value: object) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CronStorageError("Cron 时间必须是 UTC ISO 字符串")
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError as error:
        raise CronStorageError("Cron 时间格式无效") from error


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")
