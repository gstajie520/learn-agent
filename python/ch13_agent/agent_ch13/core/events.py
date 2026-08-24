"""运行时事件协议。

Java 类比：``RuntimeEvent`` 类似事件接口，``EventInbox`` 类似
``BlockingQueue<RuntimeEvent>``。后台线程完成任务后不能直接修改 Agent 历史，
而是先把一个强类型事件放入队列，主循环在下一次请求模型前统一取出。
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Mapping
from typing import Protocol

from .messages import ChatMessage, user_message


class RuntimeEvent(Protocol):
    """所有可以注入 Agent Loop 的事件都必须实现的接口。"""

    @property
    def event_id(self) -> str: ...

    @property
    def context_identity(self) -> str | None: ...

    @property
    def idempotency_key(self) -> str | None: ...

    def to_payload(self) -> Mapping[str, object]:
        """把事件转换为只包含 JSON 基础类型的字典。"""


def is_runtime_event(value: object) -> bool:
    """严格检查对象是否实现了事件接口，避免把普通字典误塞进队列。"""
    return (
        hasattr(value, "event_id")
        and isinstance(value.event_id, str)
        and bool(value.event_id.strip())
        and callable(getattr(value, "to_payload", None))
    )


class EventInbox:
    """线程安全的 FIFO 事件队列。"""

    def __init__(self) -> None:
        self._events: deque[RuntimeEvent] = deque()
        self._condition = threading.Condition()

    def publish(self, event: RuntimeEvent) -> None:
        """发布一条事件，并唤醒正在等待的 Loop。"""
        if not is_runtime_event(event):
            raise TypeError("EventInbox 只接受 RuntimeEvent 对象")
        with self._condition:
            self._events.append(event)
            self._condition.notify_all()

    def drain(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """立即取出当前已就绪事件，保持 FIFO 顺序。"""
        if limit is not None and (isinstance(limit, bool) or limit <= 0):
            raise ValueError("limit 必须是正整数")
        with self._condition:
            count = len(self._events) if limit is None else min(limit, len(self._events))
            return tuple(self._events.popleft() for _ in range(count))

    def wait(self, limit: int | None = None, timeout: float | None = None) -> tuple[RuntimeEvent, ...]:
        """阻塞直到至少有一条事件，然后取出一批事件。"""
        with self._condition:
            if not self._events and not self._condition.wait(timeout):
                return ()
            return self.drain(limit)


def runtime_event_message(event: RuntimeEvent, index: int = 0, total: int = 1) -> ChatMessage:
    """把事件包装成普通 ``user`` 消息，绝不伪装成 tool result。"""
    if not is_runtime_event(event):
        raise TypeError("event 必须是 RuntimeEvent")
    if index < 0 or total <= 0 or index >= total:
        raise ValueError("batch 位置必须满足 0 <= index < total")
    payload = {"runtime_event": dict(event.to_payload()), "batch": {"index": index, "total": total}}
    return user_message(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
