"""Cron 定时任务领域模型与运行时。

Java 类比：

* ``CronJob`` 类似不可变的 Java record；
* ``CronStore`` 类似 Repository 接口；
* ``CronRuntime`` 类似 ``ScheduledExecutorService`` 外面包的一层领域服务；
* ``CronEvent`` 是投递到 ``BlockingQueue`` 的领域事件。

本章只负责“到点产生工作意图”，真正的模型调用和工具权限仍然回到 AgentRunner。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.events import EventInbox, RuntimeEvent
from ..core.tools import ToolContext, ToolDefinition, ToolResult, tool_error, tool_success

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CRON_MARKER = re.compile(r"^[0-9*/,?-]+$")


class CronError(Exception):
    """Cron 领域异常，携带稳定机器可读错误码。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class CronExpressionError(CronError):
    """表达式、时区或时间输入无效。"""

    def __init__(self, message: str) -> None:
        super().__init__("cron_expression_error", message)


class CronStorageError(CronError):
    """Cron 持久化或锁操作失败。"""

    def __init__(self, message: str) -> None:
        super().__init__("cron_storage_error", message)


class CronJobNotFoundError(CronError):
    """找不到指定的计划或事件。"""

    def __init__(self, message: str) -> None:
        super().__init__("cron_job_not_found", message)


class CronClosedError(CronError):
    """运行时关闭后继续调用。"""

    def __init__(self, message: str) -> None:
        super().__init__("cron_closed", message)


def canonical_cron_id(value: str) -> str:
    """校验 canonical UUID。"""
    if not isinstance(value, str) or UUID_RE.fullmatch(value) is None:
        raise CronStorageError("Cron id 必须是 canonical UUID")
    return value


def validate_cron_timezone(value: str) -> str:
    """校验 IANA 时区名称。"""
    if not isinstance(value, str) or not value.strip():
        raise CronExpressionError("Cron 时区不能为空")
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise CronExpressionError(f"未知 Cron 时区: {value}") from error
    return normalized


def _parse_field(value: str, minimum: int, maximum: int) -> tuple[set[int], bool]:
    """解析一个五段 Cron 字段，支持列表、范围、步进和星号。"""
    result: set[int] = set()
    wildcard = value == "*" or value.startswith("*/")
    for item in value.split(","):
        parts = item.split("/")
        if len(parts) > 2:
            raise CronExpressionError("Cron 步进格式无效")
        base, step_text = parts[0], parts[1] if len(parts) == 2 else None
        try:
            step = 1 if step_text is None else int(step_text)
        except ValueError as error:
            raise CronExpressionError("Cron 步进必须是整数") from error
        if step <= 0:
            raise CronExpressionError("Cron 步进必须大于 0")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            bounds = base.split("-")
            if len(bounds) != 2:
                raise CronExpressionError("Cron 范围格式无效")
            try:
                start, end = int(bounds[0]), int(bounds[1])
            except ValueError as error:
                raise CronExpressionError("Cron 范围必须是整数") from error
            if start > end:
                raise CronExpressionError("Cron 范围不能倒序")
        else:
            try:
                start = end = int(base)
            except ValueError as error:
                raise CronExpressionError("Cron 字段必须是数字") from error
        if start < minimum or end > maximum:
            raise CronExpressionError("Cron 字段超出允许范围")
        result.update(range(start, end + 1, step))
    if not result:
        raise CronExpressionError("Cron 字段不能为空")
    return result, wildcard


def validate_cron_expression(value: str) -> str:
    """严格验证五段 Cron 表达式，并返回归一化空格格式。"""
    if not isinstance(value, str) or not value.strip():
        raise CronExpressionError("Cron 表达式不能为空")
    normalized = " ".join(value.strip().split())
    fields = normalized.split(" ")
    if len(fields) != 5:
        raise CronExpressionError("Cron 表达式必须正好包含五段")
    if any(not CRON_MARKER.fullmatch(field) for field in fields):
        raise CronExpressionError("Cron 表达式包含不支持的字符")
    _parse_field(fields[0], 0, 59)
    _parse_field(fields[1], 0, 23)
    _parse_field(fields[2], 1, 31)
    _parse_field(fields[3], 1, 12)
    _parse_field(fields[4], 0, 7)
    return normalized


def _matches(local: dt.datetime, expression: str) -> bool:
    fields = expression.split(" ")
    minute, _ = _parse_field(fields[0], 0, 59)
    hour, _ = _parse_field(fields[1], 0, 23)
    dom, dom_wild = _parse_field(fields[2], 1, 31)
    month, _ = _parse_field(fields[3], 1, 12)
    dow, dow_wild = _parse_field(fields[4], 0, 7)
    weekday = (local.weekday() + 1) % 7
    dow_match = weekday in dow or (weekday == 0 and 7 in dow)
    day_match = local.day in dom
    if not (local.minute in minute and local.hour in hour and local.month in month):
        return False
    if dom_wild and dow_wild:
        return True
    if dom_wild:
        return dow_match
    if dow_wild:
        return day_match
    return day_match or dow_match


def next_cron_occurrence(expression: str, timezone: str, after_utc: dt.datetime) -> dt.datetime:
    """计算严格晚于 ``after_utc`` 的下一次 UTC 触发时间。"""
    normalized = validate_cron_expression(expression)
    zone = ZoneInfo(validate_cron_timezone(timezone))
    if after_utc.tzinfo is None or after_utc.utcoffset() is None:
        raise CronExpressionError("Cron 时间必须带 UTC 时区")
    local_before = after_utc.astimezone(zone).replace(second=0, microsecond=0)
    if _matches(local_before, normalized):
        alternate = local_before.replace(fold=1).astimezone(dt.UTC)
        if alternate > after_utc.astimezone(dt.UTC):
            return alternate
    local_current = local_before.replace(tzinfo=None) + dt.timedelta(minutes=1)
    # 按业务时区的本地日历扫描。这样 DST gap/fold 不会被宿主机 UTC 扫描吞掉。
    for _ in range(5 * 366 * 24 * 60):
        if _matches(local_current.replace(tzinfo=zone), normalized):
            candidates = []
            for fold in (0, 1):
                candidate = local_current.replace(tzinfo=zone, fold=fold)
                roundtrip = candidate.astimezone(dt.UTC).astimezone(zone).replace(tzinfo=None)
                if roundtrip == local_current:
                    candidates.append(candidate.astimezone(dt.UTC))
            if candidates:
                valid = sorted(set(candidates))
                for candidate in valid:
                    if candidate > after_utc.astimezone(dt.UTC):
                        return candidate
            else:
                # 不存在的本地时刻（spring-forward gap）推进到首个有效分钟。
                probe = local_current
                for _ in range(180):
                    probe += dt.timedelta(minutes=1)
                    candidate = probe.replace(tzinfo=zone, fold=0)
                    if candidate.astimezone(dt.UTC).astimezone(zone).replace(tzinfo=None) == probe:
                        return candidate.astimezone(dt.UTC)
        local_current += dt.timedelta(minutes=1)
    raise CronExpressionError("Cron 表达式在扫描范围内没有下一次发生时间")


@dataclass(frozen=True, slots=True)
class CronJob:
    """持久化 Cron 计划。"""

    id: str
    cron: str
    prompt: str
    timezone: str
    recurring: bool
    durable: bool
    identity: str
    next_run_at_utc: dt.datetime
    last_slot_at_utc: dt.datetime | None

    def __post_init__(self) -> None:
        canonical_cron_id(self.id)
        validate_cron_expression(self.cron)
        validate_cron_timezone(self.timezone)
        if not self.prompt.strip() or not self.identity.strip():
            raise CronStorageError("Cron prompt 和 identity 不能为空")
        if self.next_run_at_utc.tzinfo is None or self.next_run_at_utc.utcoffset() is None:
            raise CronStorageError("Cron next_run_at_utc 必须带时区")
        if self.last_slot_at_utc is not None and self.last_slot_at_utc >= self.next_run_at_utc:
            raise CronStorageError("Cron next slot 必须晚于 last slot")


@dataclass(frozen=True, slots=True)
class CronEvent:
    """某一个已到期的 Cron 工作意图。"""

    event_id: str
    job_id: str
    identity: str
    prompt: str
    timezone: str
    durable: bool
    slot_at_utc: dt.datetime
    kind: str = "cron"
    context_identity: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        canonical_cron_id(self.event_id)
        canonical_cron_id(self.job_id)
        validate_cron_timezone(self.timezone)
        if not self.identity.strip() or not self.prompt.strip():
            raise CronStorageError("Cron event identity 和 prompt 不能为空")

    def to_payload(self) -> Mapping[str, object]:
        """生成稳定 snake_case 事件 JSON。"""
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "kind": "cron",
            "identity": self.identity,
            "prompt": self.prompt,
            "timezone": self.timezone,
            "durable": self.durable,
            "slot_at_utc": self.slot_at_utc.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        }


class CronStore(Protocol):
    """Cron Repository 接口。"""

    def schedule_cron(self, input: Mapping[str, object]) -> CronJob: ...
    def get_job(self, job_id: str) -> CronJob: ...
    def list_jobs(self, include_durable: bool = True) -> tuple[CronJob, ...]: ...
    def tick(self, now_utc: dt.datetime, include_durable: bool = True) -> tuple[CronEvent, ...]: ...
    def pending_events(self, include_durable: bool = True) -> tuple[CronEvent, ...]: ...
    def ack_event(self, event_id: str) -> bool: ...
    def try_acquire_leader(self) -> bool: ...
    def release_leader(self) -> None: ...


class CronClock(Protocol):
    """可注入时钟。"""

    def now(self) -> dt.datetime: ...


class CronRuntime:
    """轮询 CronStore、发布 outbox 事件、注册 schedule_cron 工具的运行时。"""

    def __init__(
        self,
        store: CronStore,
        inbox: EventInbox,
        *,
        supervisor: object | None = None,
        clock: CronClock | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds 必须大于 0")
        self.store, self.inbox = store, inbox
        self._supervisor = supervisor
        self.clock = clock or SystemCronClock()
        self.poll_seconds = poll_seconds
        self._queued: set[str] = set()
        self._leader = False
        self._closed = False
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wakeup: Callable[[], None] | None = None

    @property
    def event_inbox(self) -> EventInbox:
        """返回共享事件队列。"""
        return self.inbox

    @property
    def supervisor(self) -> object | None:
        """返回组合根注入的共享后台 Supervisor。"""
        return self._supervisor

    @property
    def has_pending_work(self) -> bool:
        """Cron 本身不执行工具，pending 由 outbox 是否有事件决定。"""
        return bool(self.store.pending_events())

    @property
    def tool_definition(self) -> ToolDefinition:
        """返回 schedule_cron 工具定义。"""

        def handler(arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
            try:
                payload = dict(arguments)
                payload["identity"] = context.identity
                payload["now_utc"] = self.clock.now()
                job = self.store.schedule_cron(payload)
                return tool_success(json.dumps(_job_payload(job), ensure_ascii=False))
            except CronError as error:
                return tool_error(error.error_code, str(error))

        return ToolDefinition(
            "schedule_cron",
            "创建一个周期或一次性 Cron 计划",
            {
                "type": "object",
                "properties": {
                    "cron": {"type": "string"},
                    "prompt": {"type": "string"},
                    "timezone": {"type": "string"},
                    "recurring": {"type": "boolean"},
                    "durable": {"type": "boolean"},
                },
                "required": ["cron", "prompt", "timezone", "recurring", "durable"],
                "additionalProperties": False,
            },
            "write",
            handler,
            _schedule_args,
        )

    def tick(self) -> tuple[CronEvent, ...]:
        """执行一次 leader 竞争、到期迁移和 pending 事件发布。"""
        if self._closed:
            raise CronClosedError("CronRuntime 已关闭")
        if not self._leader:
            self._leader = self.store.try_acquire_leader()
        self.store.tick(self.clock.now(), self._leader)
        published: list[CronEvent] = []
        for event in self.store.pending_events(self._leader):
            if event.event_id not in self._queued:
                self.inbox.publish(event)
                self._queued.add(event.event_id)
                published.append(event)
        if published and self._wakeup is not None:
            self._wakeup()
        return tuple(published)

    def acknowledge_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """确认 Cron outbox 事件；确认失败时保留事件以便重试。"""
        for event in events:
            if isinstance(event, CronEvent):
                if not self.store.ack_event(event.event_id):
                    raise CronStorageError(f"Cron event 不再处于 pending: {event.event_id}")
                self._queued.discard(event.event_id)

    def release_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """处理失败时释放内存去重标记；下一次 tick 会重新发布 durable outbox。"""
        for event in events:
            if isinstance(event, CronEvent):
                self._queued.discard(event.event_id)

    def bind_wakeup(self, callback: Callable[[], None]) -> None:
        """绑定空闲 Agent 回合唤醒回调。"""
        self._wakeup = callback

    def start(self) -> None:
        """启动受控轮询线程。"""
        if self._closed:
            raise CronClosedError("CronRuntime 已关闭")
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cron-runtime", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """后台线程只 tick 和等待，不直接执行 prompt。"""
        while not self._stop.is_set() and not self._closed:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                time.sleep(self.poll_seconds)
            self._stop.wait(self.poll_seconds)

    def close(self) -> None:
        """停止线程并释放 leader lease。"""
        if self._closed and self._thread is None:
            return
        self._closed = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(max(1.0, self.poll_seconds * 2))
            self._thread = None
        if self._leader:
            self.store.release_leader()
            self._leader = False

    def drain_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """从共享 Inbox 取出事件。"""
        return self.inbox.drain(limit)

    def wait_for_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """等待共享 Inbox 事件。"""
        return self.inbox.wait(limit)


class SystemCronClock:
    """生产时钟。"""

    def now(self) -> dt.datetime:
        """返回当前带 UTC 时区的时间。"""
        return dt.datetime.now(dt.UTC)


def _schedule_args(value: Mapping[str, object]) -> bool:
    """严格检查 schedule_cron 五个输入字段。"""
    return (
        set(value) == {"cron", "prompt", "timezone", "recurring", "durable"}
        and all(
            isinstance(value[name], str) and bool(str(value[name]).strip())
            for name in ("cron", "prompt", "timezone")
        )
        and isinstance(value["recurring"], bool)
        and isinstance(value["durable"], bool)
    )


def _job_payload(job: CronJob) -> dict[str, object]:
    """把 CronJob 转为稳定 JSON 字段。"""
    return {
        "id": job.id,
        "cron": job.cron,
        "prompt": job.prompt,
        "timezone": job.timezone,
        "recurring": job.recurring,
        "durable": job.durable,
        "identity": job.identity,
        "next_run_at_utc": job.next_run_at_utc.astimezone(dt.UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "last_slot_at_utc": None
        if job.last_slot_at_utc is None
        else job.last_slot_at_utc.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
    }
