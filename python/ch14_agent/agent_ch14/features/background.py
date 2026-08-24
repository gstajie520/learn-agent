"""后台任务领域模型、Supervisor 和工具分流器。"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ..core.events import EventInbox, RuntimeEvent
from ..core.tools import (
    PreparedToolCall,
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)

CANONICAL_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
STATUSES = ("running", "completed", "failed", "timed_out", "cancelled", "interrupted")
BACKGROUND_MARKERS = ("cargo build", "compile", "deploy", "docker build", "npm install", "pip install", "pytest")


class BackgroundError(Exception):
    """后台任务的领域异常，``error_code`` 是稳定的机器可读错误码。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _uuid(value: str, label: str = "job_id") -> str:
    """校验 canonical UUID，防止任意字符串参与文件路径拼接。"""
    if not isinstance(value, str) or CANONICAL_UUID.fullmatch(value) is None:
        raise BackgroundError("background_contract_error", f"{label} 必须是 canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class BackgroundJob:
    """后台 Job 的持久化快照。Java 类比：不可变状态 DTO。"""

    id: str
    source_tool_call_id: str
    tool_name: str
    status: str
    result: ToolResult | None

    def __post_init__(self) -> None:
        _uuid(self.id)
        if not self.source_tool_call_id.strip() or not self.tool_name.strip():
            raise BackgroundError("background_contract_error", "工具调用 id 和工具名不能为空")
        if self.status not in STATUSES:
            raise BackgroundError("background_contract_error", "后台任务状态无效")
        if self.status == "running" and self.result is not None:
            raise BackgroundError("background_contract_error", "running 状态不能携带 result")
        if self.status != "running" and self.result is None:
            raise BackgroundError("background_contract_error", "终态必须携带 result")
        if self.status == "completed" and self.result is not None and self.result.is_error:
            raise BackgroundError("background_contract_error", "completed 必须是成功结果")
        if self.status != "completed" and self.status != "running" and self.result is not None and not self.result.is_error:
            raise BackgroundError("background_contract_error", "失败终态必须是错误结果")


class BackgroundJobStore(Protocol):
    """后台持久化接口，类似 Java Repository。"""

    def create_running(self, job_id: str, source_tool_call_id: str, tool_name: str) -> BackgroundJob: ...
    def finish_running(self, job_id: str, status: str, result: ToolResult) -> BackgroundJob | None: ...
    def interrupt_running(self) -> tuple[BackgroundJob, ...]: ...
    def get_job(self, job_id: str) -> BackgroundJob: ...
    def list_jobs(self) -> tuple[BackgroundJob, ...]: ...


class BackgroundOperation(Protocol):
    """后台线程实际执行的函数签名。"""

    def __call__(self, cancel_event: threading.Event) -> ToolResult: ...


@dataclass(frozen=True, slots=True)
class BackgroundJobEvent:
    """后台终态事件，供 EventInbox 注入主 Agent Loop。"""

    event_id: str
    job_id: str
    source_tool_call_id: str
    tool_name: str
    status: str
    result: ToolResult
    context_identity: str | None = None
    idempotency_key: str | None = None

    def to_payload(self) -> Mapping[str, object]:
        """生成模型可见的稳定 JSON 字段。"""
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "kind": "background_job",
            "result": {"content": self.result.content, "error_code": self.result.error_code, "is_error": self.result.is_error},
            "source_tool_call_id": self.source_tool_call_id,
            "status": self.status,
            "tool_name": self.tool_name,
        }


class JobSupervisor:
    """受控后台任务服务：容量、超时、取消、恢复、事件发布都集中在这里。"""

    def __init__(self, store: BackgroundJobStore, inbox: EventInbox, *, capacity: int = 4, timeout: float = 120.0, close_timeout: float = 10.0, id_generator: Callable[[], str] | None = None, event_id_generator: Callable[[], str] | None = None) -> None:
        if capacity <= 0 or timeout <= 0 or close_timeout <= 0:
            raise ValueError("capacity 和 timeout 必须是正数")
        self.store, self.inbox = store, inbox
        self.capacity, self.timeout, self.close_timeout = capacity, timeout, close_timeout
        self._id_generator = id_generator or (lambda: str(uuid.uuid4()))
        self._event_id_generator = event_id_generator or (lambda: str(uuid.uuid4()))
        self._controls: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._lock = threading.RLock()
        self._closed = False
        self._ready = False
        self._recover()

    def _recover(self) -> None:
        """启动时把上次进程遗留的 running 标记成 interrupted，只通知一次。"""
        for job in self.store.interrupt_running():
            if job.result is not None:
                self.inbox.publish(self._event(job))
        self._ready = True

    def _event(self, job: BackgroundJob) -> BackgroundJobEvent:
        """从终态 Job 创建一个事件。"""
        assert job.result is not None
        return BackgroundJobEvent(self._event_id_generator(), job.id, job.source_tool_call_id, job.tool_name, job.status, job.result)

    @property
    def ready(self) -> bool:
        """返回恢复是否完成。"""
        return self._ready

    @property
    def active_count(self) -> int:
        """返回当前受 Supervisor 管理的 worker 数量。"""
        with self._lock:
            return len(self._controls)

    @property
    def has_pending_work(self) -> bool:
        """判断是否还有运行中的后台任务。"""
        return self.active_count > 0

    def submit(self, source_tool_call_id: str, tool_name: str, operation: BackgroundOperation) -> str:
        """先容量检查、再落盘 running、最后启动 worker。"""
        with self._lock:
            if self._closed:
                raise BackgroundError("background_closed", "后台任务服务已关闭")
            if len(self._controls) >= self.capacity:
                raise BackgroundError("background_capacity", "后台任务容量已满")
            job_id = _uuid(self._id_generator())
            self.store.create_running(job_id, source_tool_call_id, tool_name)
            cancel_event = threading.Event()
            worker = threading.Thread(target=self._run_worker, args=(job_id, operation, cancel_event), daemon=True)
            self._controls[job_id] = (worker, cancel_event)
            worker.start()
            return job_id

    def _run_worker(self, job_id: str, operation: BackgroundOperation, cancel_event: threading.Event) -> None:
        """执行单个 worker，并通过条件迁移保证终态事件只发布一次。"""
        status, result = "completed", None
        started = time.monotonic()
        try:
            result = operation(cancel_event)
            if not isinstance(result, ToolResult):
                result = tool_error("background_contract_error", "后台操作返回了无效结果")
            if result.is_error:
                status = "failed"
        except Exception:  # noqa: BLE001
            status, result = "failed", tool_error("background_execution_error", "后台任务执行失败")
        if cancel_event.is_set() and status == "completed":
            status, result = "cancelled", tool_error("background_cancelled", "后台任务已取消")
        if time.monotonic() - started > self.timeout and status == "completed":
            status, result = "timed_out", tool_error("background_timeout", "后台任务执行超时")
        assert result is not None
        job = self.store.finish_running(job_id, status, result)
        with self._lock:
            self._controls.pop(job_id, None)
        if job is not None:
            self.inbox.publish(self._event(job))

    def cancel(self, job_id: str) -> BackgroundJob:
        """请求取消并等待 worker 收束，再返回最终持久化状态。"""
        job_id = _uuid(job_id)
        with self._lock:
            control = self._controls.get(job_id)
        if control is None:
            job = self.store.get_job(job_id)
            if job.status != "running":
                raise BackgroundError("background_job_state", "任务已经是终态")
            raise BackgroundError("background_job_not_found", "找不到正在运行的后台任务")
        control[1].set()
        control[0].join(self.close_timeout)
        return self.store.get_job(job_id)

    def get_job(self, job_id: str) -> BackgroundJob:
        """读取单个后台任务。"""
        return self.store.get_job(_uuid(job_id))

    def list_jobs(self) -> tuple[BackgroundJob, ...]:
        """读取全部后台任务。"""
        return self.store.list_jobs()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """等待所有 worker 结束，返回是否在超时前完成。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.has_pending_work:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self) -> None:
        """拒绝新任务，取消并等待已有 worker。"""
        with self._lock:
            self._closed = True
            controls = tuple(self._controls.values())
        for _, event in controls:
            event.set()
        for thread, _ in controls:
            thread.join(self.close_timeout)

    def drain_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """取走已完成事件。"""
        return self.inbox.drain(limit)

    def wait_for_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """阻塞等待完成事件。"""
        return self.inbox.wait(limit)

    def acknowledge_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """后台完成事件没有 durable outbox，确认操作只验证事件类型。"""
        if not all(hasattr(event, "event_id") for event in events):
            raise TypeError("events 必须是 RuntimeEvent")

    def release_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """后台事件失败时重新放回 Inbox，允许下一轮重试。"""
        for event in reversed(events):
            self.inbox.publish(event)


def should_run_in_background(command: str, requested: bool | None) -> bool:
    """实现 P13 三态规则：true 强制后台，false 强制同步，None 使用关键词启发式。"""
    if requested is not None:
        return requested
    lowered = command.lower()
    return any(marker in lowered for marker in BACKGROUND_MARKERS)


class BackgroundDispatcher:
    """在权限检查之后，把可后台工具分流给 JobSupervisor。"""

    def __init__(self, supervisor: JobSupervisor) -> None:
        self.supervisor = supervisor

    def dispatch(self, prepared: PreparedToolCall, context: ToolContext, tools: ToolRegistry) -> ToolResult | None:
        """后台提交成功返回 running 占位结果；不适用时返回 None。"""
        definition = prepared.definition
        if definition is None or definition.concurrency != "background_eligible" or prepared.arguments is None:
            return None
        arguments = dict(prepared.arguments)
        requested = arguments.pop("run_in_background", None)
        command = str(arguments.get("command", ""))
        if not should_run_in_background(command, requested):
            return None
        job_id = self.supervisor.submit(prepared.call.id, definition.name, lambda cancel: tools.invoke(PreparedToolCall(prepared.call, definition, arguments, None), context))
        return tool_success(f"后台任务已提交: job_id={job_id}; status=running")


def register_background_job_tools(registry: ToolRegistry, supervisor: JobSupervisor) -> None:
    """仅给 P13 主 Agent 注册查询和取消工具。"""
    def validate(value: Mapping[str, object]) -> bool:
        return set(value) == {"job_id"} and isinstance(value.get("job_id"), str) and CANONICAL_UUID.fullmatch(str(value["job_id"])) is not None
    def query(arguments: Mapping[str, object], _: ToolContext) -> ToolResult:
        try:
            job = supervisor.get_job(str(arguments["job_id"]))
            return tool_success(_job_text(job))
        except BackgroundError as error:
            return tool_error(error.error_code, str(error))
    def cancel(arguments: Mapping[str, object], _: ToolContext) -> ToolResult:
        try:
            return tool_success(_job_text(supervisor.cancel(str(arguments["job_id"]))))
        except BackgroundError as error:
            return tool_error(error.error_code, str(error))
    schema = {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"], "additionalProperties": False}
    registry.register(ToolDefinition("query_background_job", "查询后台任务当前状态", schema, "read", query, validate))
    registry.register(ToolDefinition("cancel_background_job", "取消正在运行的后台任务", schema, "write", cancel, validate))


def _job_text(job: BackgroundJob) -> str:
    """把 Job 转换成适合模型阅读的 JSON 文本。"""
    import json
    return json.dumps({"job_id": job.id, "status": job.status, "tool_name": job.tool_name, "source_tool_call_id": job.source_tool_call_id, "result": None if job.result is None else {"content": job.result.content, "error_code": job.result.error_code, "is_error": job.result.is_error}}, ensure_ascii=False)
