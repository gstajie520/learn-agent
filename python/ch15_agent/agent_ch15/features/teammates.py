"""持久队友运行时。

Java 类比：``TeammateRuntime`` 类似一个受管的 WorkerService；每个队友有独立
Session/AgentRunner 和历史，MailboxStore 负责可靠投递，EventInbox 负责把结果送回 Lead。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..core.events import EventInbox, RuntimeEvent
from ..core.loop import AgentRunner
from ..core.tools import ToolContext, ToolDefinition, ToolResult, tool_error, tool_success
from .background import JobSupervisor
from .cron import CronRuntime
from .mailbox import (
    LEAD_NAME,
    MailboxMessage,
    MailboxStorageError,
    MailboxStore,
    canonical_agent_name,
)

TeammateStatus = Literal["running", "idle", "failed", "shutdown"]


@dataclass(frozen=True, slots=True)
class Teammate:
    """对外暴露的队友状态快照。"""

    name: str  # 队友安全 slug，也是 mailbox recipient。
    role: str  # 队友职责描述，用于构造 system prompt。
    status: TeammateStatus  # running、idle、failed、shutdown。


@dataclass(slots=True)
class _Worker:
    """内部 worker 状态；runner 和 history 在整个生命周期内复用。"""

    teammate: Teammate
    runner: AgentRunner
    thread: threading.Thread | None = None
    stop: threading.Event | None = None
    current: MailboxMessage | None = None
    cleanup_error: BaseException | None = None


RunnerFactory = Callable[[str, str, ToolDefinition], AgentRunner]


class TeammateRuntime:
    """管理持久队友、Mailbox 投递和 Lead 事件泵。"""

    def __init__(
        self,
        store: MailboxStore,
        inbox: EventInbox,
        supervisor: JobSupervisor,
        cron_runtime: CronRuntime,
        *,
        lead_name: str = LEAD_NAME,
    ) -> None:
        if cron_runtime.supervisor is not supervisor or cron_runtime.event_inbox is not inbox:
            raise ValueError("cron_runtime 必须共享 background supervisor 和 EventInbox")
        self.store = store  # 共享的消息 Repository。
        self.inbox = inbox  # Lead 唯一事件收件箱。
        self.supervisor = supervisor  # 共享后台资源所有者，用于组合根一致性校验。
        self.cron_runtime = cron_runtime  # 共享 Cron 的事件确认协议。
        self.lead_name = canonical_agent_name(lead_name)
        self._workers: dict[str, _Worker] = {}  # 当前进程创建过的队友注册表。
        self._queued: set[str] = set()  # 已发布到 Inbox 的 Lead mailbox 消息 ID。
        self._factory: RunnerFactory | None = None  # 一次性注入的队友 Runner 工厂。
        self._closed = False
        self._started = False
        self._lock = threading.RLock()
        self._spawn_definition = ToolDefinition(
            "spawn_teammate",
            "创建一个持久队友",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["name", "role", "prompt"],
                "additionalProperties": False,
            },
            "external",
            self._spawn_tool,
            self._validate_spawn,
        )
        self._send_definition = ToolDefinition(
            "send_message",
            "向队友发送持久消息",
            {
                "type": "object",
                "properties": {"to": {"type": "string"}, "content": {"type": "string"}},
                "required": ["to", "content"],
                "additionalProperties": False,
            },
            "external",
            self._send_tool,
            self._validate_send,
        )

    @property
    def spawn_tool_definition(self) -> ToolDefinition:
        """返回 Lead 使用的 spawn_teammate 工具定义。"""
        return self._spawn_definition

    @property
    def send_tool_definition(self) -> ToolDefinition:
        """返回 Lead 和队友使用的 send_message 工具定义。"""
        return self._send_definition

    @property
    def has_pending_work(self) -> bool:
        """判断共享事件队列或队友 worker 是否仍有工作。"""
        return bool(self._queued) or any(
            worker.thread is not None and worker.thread.is_alive()
            for worker in self._workers.values()
        )

    def configure_runner_factory(self, factory: RunnerFactory) -> None:
        """在 start 前配置一次独立 Runner 工厂。"""
        if self._factory is not None or self._started:
            raise RuntimeError("队友 Runner 工厂只能在启动前配置一次")
        self._factory = factory

    def start(self) -> None:
        """恢复 Lead 遗留租约并发布 ready 消息。"""
        if self._closed:
            raise RuntimeError("TeammateRuntime 已关闭")
        if self._factory is None:
            raise RuntimeError("尚未配置队友 Runner 工厂")
        if self._started:
            return
        self.store.recover_processing(self.lead_name)
        self._publish_lead()
        self._started = True

    def ready(self) -> None:
        """RuntimeEventPump 的启动屏障。"""
        self.start()

    def state(self, name: str) -> Teammate:
        """返回一个队友的不可变状态。"""
        worker = self._workers.get(canonical_agent_name(name))
        if worker is None:
            raise KeyError(f"找不到队友: {name}")
        return worker.teammate

    def spawn(self, name: str, role: str, prompt: str, *, sender: str) -> Teammate:
        """注册队友、写入首个 task，再异步启动 worker。"""
        self._ensure_open()
        name = canonical_agent_name(name)
        sender = canonical_agent_name(sender)
        if name == self.lead_name:
            raise ValueError("lead 是保留身份，不能创建同名队友")
        if not role.strip() or not prompt.strip():
            raise ValueError("队友 role 和 prompt 不能为空")
        with self._lock:
            if name in self._workers:
                raise ValueError(f"队友已经存在: {name}")
            if self._factory is None:
                raise RuntimeError("尚未配置队友 Runner 工厂")
            runner = self._factory(name, role, self._send_definition)
            worker = _Worker(Teammate(name, role, "running"), runner)
            self._workers[name] = worker
            try:
                self.store.recover_processing(name)
                self.store.send(sender, name, prompt, "task")
                self._start_worker(worker)
                return worker.teammate
            except Exception:
                self._workers.pop(name, None)
                runner.close()
                raise

    def send(self, to: str, content: str, *, sender: str) -> MailboxMessage:
        """持久发送普通 message，idle 队友会复用原 Runner 被唤醒。"""
        self._ensure_open()
        to = canonical_agent_name(to)
        sender = canonical_agent_name(sender)
        if to == sender or not content.strip():
            raise ValueError("sender/recipient 不能相同，消息正文不能为空")
        with self._lock:
            worker = None if to == self.lead_name else self._workers.get(to)
            if to != self.lead_name and worker is None:
                raise KeyError(f"找不到队友: {to}")
            if worker is not None and worker.teammate.status in {"failed", "shutdown"}:
                raise RuntimeError(f"队友当前状态不可接收消息: {worker.teammate.status}")
            message = self.store.send(sender, to, content, "message")
            if worker is not None and worker.teammate.status == "idle":
                worker.teammate = Teammate(worker.teammate.name, worker.teammate.role, "running")
                self._start_worker(worker)
        if to == self.lead_name:
            self._publish_lead()
        return message

    def drain_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """取出共享 Inbox 事件，并清除 mailbox 的内存入队标记。"""
        events = self.inbox.drain(limit)
        for event in events:
            if isinstance(event, MailboxMessage):
                self._queued.discard(event.id)
        return events

    def wait_for_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """阻塞等待共享 Inbox 事件。"""
        events = self.inbox.wait(limit)
        for event in events:
            if isinstance(event, MailboxMessage):
                self._queued.discard(event.id)
        return events

    def acknowledge_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """确认 Cron 与 mailbox 事件；mailbox ack 失败会抛错并等待重试。"""
        cron_events = tuple(event for event in events if not isinstance(event, MailboxMessage))
        if cron_events:
            self.cron_runtime.acknowledge_events(cron_events)
        for event in events:
            if isinstance(event, MailboxMessage) and not self.store.ack(event):
                raise MailboxStorageError(f"Mailbox 消息不在 processing 状态: {event.id}")

    def release_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """业务失败时把 mailbox processing 租约退回 ready。"""
        for event in events:
            if isinstance(event, MailboxMessage):
                self.store.release(event)
            else:
                self.cron_runtime.release_events((event,))

    def close(self) -> None:
        """取消所有 worker、释放 processing 消息并关闭独立 Runner。"""
        self._closed = True
        failures: list[BaseException] = []
        for worker in tuple(self._workers.values()):
            if worker.stop is not None:
                worker.stop.set()
            if worker.thread is not None:
                worker.thread.join(5)
            if worker.current is not None:
                try:
                    self.store.release(worker.current)
                    worker.current = None
                except Exception as error:  # noqa: BLE001
                    failures.append(error)
            try:
                worker.runner.close()
            except Exception as error:  # noqa: BLE001
                failures.append(error)
            worker.teammate = Teammate(worker.teammate.name, worker.teammate.role, "shutdown")
        if failures:
            raise failures[0]

    def _start_worker(self, worker: _Worker) -> None:
        """启动一个可复用的后台线程；同一队友不会并发运行两个 worker。"""
        if worker.thread is not None and worker.thread.is_alive():
            return
        worker.stop = threading.Event()
        worker.thread = threading.Thread(
            target=self._run_worker,
            args=(worker,),
            daemon=True,
            name=f"teammate-{worker.teammate.name}",
        )
        worker.thread.start()

    def _run_worker(self, worker: _Worker) -> None:
        """循环 claim -> run -> send result -> ack，失败则 quarantine。"""
        try:
            while not self._closed and worker.stop is not None and not worker.stop.is_set():
                message = self.store.claim(worker.teammate.name)
                if message is None:
                    worker.teammate = Teammate(worker.teammate.name, worker.teammate.role, "idle")
                    return
                worker.current = message
                try:
                    result = worker.runner.run(message.content, idempotency_key=message.id)
                    self.store.send(
                        worker.teammate.name, self.lead_name, result.final_text, "result"
                    )
                    if not self.store.ack(message):
                        raise MailboxStorageError(f"Mailbox ack 失败: {message.id}")
                    worker.current = None
                    worker.teammate = Teammate(worker.teammate.name, worker.teammate.role, "idle")
                    self._publish_lead()
                except Exception:
                    if self._closed or (worker.stop is not None and worker.stop.is_set()):
                        self.store.release(message)
                        worker.current = None
                        return
                    self.store.quarantine(message)
                    worker.current = None
                    raise
        except Exception as error:  # noqa: BLE001
            worker.teammate = Teammate(worker.teammate.name, worker.teammate.role, "failed")
            try:
                self.store.send(
                    worker.teammate.name,
                    self.lead_name,
                    f"队友 {worker.teammate.name} 执行失败: {error}",
                    "result",
                )
                self._publish_lead()
            except Exception:  # noqa: BLE001
                return

    def _publish_lead(self) -> None:
        """持续 claim Lead ready 消息并放入公共 EventInbox。"""
        while True:
            message = self.store.claim(self.lead_name)
            if message is None:
                return
            if message.id in self._queued:
                raise MailboxStorageError(f"Mailbox 消息重复入队: {message.id}")
            self._queued.add(message.id)
            self.inbox.publish(message)

    def _ensure_open(self) -> None:
        """拒绝关闭后的新操作。"""
        if self._closed:
            raise RuntimeError("TeammateRuntime 已关闭")

    def _spawn_tool(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """工具边界：sender 只能取自 ToolContext.identity。"""
        try:
            teammate = self.spawn(
                str(arguments["name"]),
                str(arguments["role"]),
                str(arguments["prompt"]),
                sender=context.identity,
            )
            return tool_success(
                json.dumps(
                    {"name": teammate.name, "role": teammate.role, "status": teammate.status},
                    ensure_ascii=False,
                )
            )
        except Exception as error:  # noqa: BLE001
            return tool_error("teammate_spawn_error", str(error))

    def _send_tool(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """工具边界：不能由模型伪造 sender。"""
        try:
            message = self.send(
                str(arguments["to"]), str(arguments["content"]), sender=context.identity
            )
            return tool_success(json.dumps(dict(message.to_payload()), ensure_ascii=False))
        except Exception as error:  # noqa: BLE001
            return tool_error("mailbox_send_error", str(error))

    @staticmethod
    def _validate_spawn(arguments: Mapping[str, Any]) -> bool:
        return set(arguments) == {"name", "role", "prompt"} and all(
            isinstance(value, str) and bool(value.strip()) for value in arguments.values()
        )

    @staticmethod
    def _validate_send(arguments: Mapping[str, Any]) -> bool:
        return set(arguments) == {"to", "content"} and all(
            isinstance(value, str) and bool(value.strip()) for value in arguments.values()
        )
