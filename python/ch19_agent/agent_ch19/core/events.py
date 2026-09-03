"""运行时事件协议。

这是什么：定义事件接口和线程安全队列，让后台任务能安全地通知主循环
Java 类比：``RuntimeEvent`` 类似事件接口，``EventInbox`` 类似 ``BlockingQueue<RuntimeEvent>``
为什么需要：后台线程不能直接修改 Agent 历史（线程不安全），需要通过队列传递事件，
          主循环在安全点（消息配对完整后）统一取出并包装成 user 消息
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Mapping
from typing import Protocol

from .messages import ChatMessage, user_message


class RuntimeEvent(Protocol):
    """所有可以注入 Agent Loop 的事件都必须实现的接口。

    这是什么：事件的统一协议，定义所有运行时事件必须具备的字段
    Java 类比：interface RuntimeEvent { String getEventId(); Map<String, Object> toPayload(); }
    为什么需要：统一事件格式，让主循环能用同一套逻辑处理不同来源的事件（后台任务、定时器、邮箱）
    """

    @property
    def event_id(self) -> str:
        """事件唯一标识，用于去重。

        Java 类比：类似 UUID.randomUUID().toString()
        为什么需要：防止重启或重试导致事件重复处理（幂等性保证）
        """
        ...

    @property
    def context_identity(self) -> str | None:
        """事件关联的用户身份，None 表示系统事件。

        Java 类比：类似 String getUserId()，返回 null 表示系统级事件
        为什么需要：区分系统事件（随时注入）和用户上下文事件（只在该用户回合注入），防止上下文混淆
        """
        ...

    @property
    def idempotency_key(self) -> str | None:
        """业务级幂等键，如邮件 message_id。

        Java 类比：类似 String getIdempotencyKey()，用于业务去重
        为什么需要：防止同一业务操作被重复执行（如同一封邮件不应被处理两次）
        """
        ...

    def to_payload(self) -> Mapping[str, object]:
        """把事件转换为只包含 JSON 基础类型的字典。

        这是什么：序列化方法，返回可 JSON 化的字典
        Java 类比：Map<String, Object> toMap()，只包含基础类型
        为什么需要：事件需要持久化到文件/数据库，且要让模型能读懂事件内容
        """


def is_runtime_event(value: object) -> bool:
    """严格检查对象是否实现了事件接口，避免把普通字典误塞进队列。

    这是什么：类型守卫函数，运行时检查对象是否符合 RuntimeEvent 协议
    Java 类比：类似 instanceof RuntimeEvent，但 Python 的 Protocol 是鸭子类型，需要手动检查
    为什么需要：防止把普通 dict 当事件发布，导致后续 event_id 访问失败
    """
    return (
        hasattr(value, "event_id")  # 必须有 event_id 属性
        and isinstance(value.event_id, str)  # event_id 必须是字符串
        and bool(value.event_id.strip())  # event_id 不能为空
        and callable(getattr(value, "to_payload", None))  # 必须有 to_payload 方法
    )


class EventInbox:
    """线程安全的 FIFO 事件队列。

    这是什么：生产者-消费者队列，后台线程发布事件，主循环消费事件
    Java 类比：类似 BlockingQueue<RuntimeEvent> + Condition，支持阻塞等待
    为什么需要：解耦事件生产（后台线程）和消费（主循环），保证线程安全
    """

    def __init__(self) -> None:
        # deque 是双端队列，popleft() 是 O(1)，而 list.pop(0) 是 O(n)
        self._events: deque[RuntimeEvent] = deque()  # 存储事件的队列
        self._condition = threading.Condition()  # 条件变量，用于阻塞等待和通知

    def publish(self, event: RuntimeEvent) -> None:
        """发布一条事件，并唤醒正在等待的 Loop。

        这是什么：生产者方法，后台线程调用此方法发布事件
        Java 类比：queue.put(event); condition.signalAll()
        为什么需要：后台任务完成后通知主循环，而不是直接修改历史
        """
        if not is_runtime_event(event):
            raise TypeError("EventInbox 只接受 RuntimeEvent 对象")
        with self._condition:  # 自动加锁和释放锁，类似 Java 的 synchronized
            self._events.append(event)  # 追加到队列尾部
            self._condition.notify_all()  # 唤醒所有等待的线程

    def drain(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """立即取出当前已就绪事件，保持 FIFO 顺序。

        这是什么：非阻塞取事件方法，立即返回当前队列中的事件（可能为空）
        Java 类比：List<Event> events = new ArrayList<>(); queue.drainTo(events, limit);
        为什么需要：主循环在安全点轮询事件，不阻塞在这里
        """
        if limit is not None and (isinstance(limit, bool) or limit <= 0):
            raise ValueError("limit 必须是正整数")
        with self._condition:  # 加锁保护队列操作
            count = len(self._events) if limit is None else min(limit, len(self._events))
            # popleft() 从队头取出，保持 FIFO 顺序
            return tuple(self._events.popleft() for _ in range(count))

    def wait(
        self, limit: int | None = None, timeout: float | None = None
    ) -> tuple[RuntimeEvent, ...]:
        """阻塞直到至少有一条事件，然后取出一批事件。

        这是什么：阻塞取事件方法，等待直到有事件或超时
        Java 类比：condition.await(timeout, TimeUnit.SECONDS); 然后 drainTo
        为什么需要：当主循环确认有待处理工作时，阻塞等待事件到达，避免忙轮询
        """
        with self._condition:
            # 如果队列为空，阻塞等待直到有事件发布或超时
            if not self._events and not self._condition.wait(timeout):
                return ()  # 超时返回空元组
            return self.drain(limit)  # 有事件后非阻塞取出


def runtime_event_message(event: RuntimeEvent, index: int = 0, total: int = 1) -> ChatMessage:
    """把事件包装成普通 ``user`` 消息，绝不伪装成 tool result。

    这是什么：将事件转换为主循环能识别的 user 消息
    Java 类比：UserMessage wrapEvent(RuntimeEvent event) { return new UserMessage(toJson(event)); }
    为什么需要：事件是外部输入（后台任务完成、定时器触发），不是 Agent 主动调用工具的结果，
             包装成 user 消息保持消息配对完整性（每个 tool_call 必须有对应 tool 结果）

    参数：
        event: 要包装的事件
        index: 批次索引（同时注入多条事件时的位置）
        total: 批次总数
    """
    if not is_runtime_event(event):
        raise TypeError("event 必须是 RuntimeEvent")
    if index < 0 or total <= 0 or index >= total:
        raise ValueError("batch 位置必须满足 0 <= index < total")
    # 构造 JSON payload，包含事件内容和批次信息
    payload = {"runtime_event": dict(event.to_payload()), "batch": {"index": index, "total": total}}
    # ensure_ascii=False 保留中文，separators 去掉空格压缩 JSON
    return user_message(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
