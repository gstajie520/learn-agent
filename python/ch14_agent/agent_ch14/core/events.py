"""运行时事件协议。

这是什么：后台任务完成后向主循环注入事件的通信协议
Java 类比：RuntimeEvent 类似事件接口，EventInbox 类似 BlockingQueue<RuntimeEvent>
为什么需要：后台线程不能直接修改 Agent 历史（线程安全问题），需要通过队列传递事件

核心机制：
- RuntimeEvent：强类型事件接口（Protocol），确保事件可序列化
- EventInbox：线程安全的 FIFO 队列，支持阻塞等待和立即取出
- runtime_event_message：把事件包装成 user 消息注入循环（不伪装成 tool 结果）
"""

from __future__ import annotations

import json
import threading
from collections import deque
from collections.abc import Mapping
from typing import Protocol

from .messages import ChatMessage, user_message


# ==================== 运行时事件接口 ====================

class RuntimeEvent(Protocol):
    """所有可以注入 Agent Loop 的事件都必须实现的接口。

    这是什么：定义后台事件必须提供的字段和方法
    Java 类比：interface RuntimeEvent { String getEventId(); Map<String, Object> toPayload(); }
    为什么需要：统一事件格式，确保事件可追踪、可序列化、支持幂等

    必需字段：
        event_id: 唯一标识符（用于去重和追踪）
        context_identity: 事件所属的上下文标识（可选）
        idempotency_key: 幂等键（可选，用于防止重复处理）
    """

    @property
    def event_id(self) -> str:
        """事件唯一 ID（必需）。

        这是什么：事件的全局唯一标识符
        Java 类比：类似 String getEventId()
        为什么需要：用于去重和追踪事件处理状态
        """
        ...

    @property
    def context_identity(self) -> str | None:
        """事件所属的上下文身份（可选）。

        这是什么：标识事件来自哪个后台任务或上下文
        Java 类比：类似 String getContextId()
        为什么需要：让主循环知道事件的来源，便于路由和过滤
        """
        ...

    @property
    def idempotency_key(self) -> str | None:
        """幂等键（可选）。

        这是什么：用于防止重复处理的去重键
        Java 类比：类似 String getIdempotencyKey()
        为什么需要：网络重传或多次调度时确保事件只处理一次
        """
        ...

    def to_payload(self) -> Mapping[str, object]:
        """把事件转换为只包含 JSON 基础类型的字典。

        这是什么：序列化方法，把事件转为纯数据
        Java 类比：类似 Map<String, Object> toJson()
        为什么需要：事件可能需要持久化或通过网络传输，必须可序列化
        """


def is_runtime_event(value: object) -> bool:
    """严格检查对象是否实现了事件接口，避免把普通字典误塞进队列。

    这是什么：运行时类型守卫，检查对象是否符合 RuntimeEvent 契约
    Java 类比：类似 boolean isRuntimeEvent(Object value)
    为什么需要：Python 的 Protocol 是静态类型检查，运行时需要手动验证
    """
    return (
        hasattr(value, "event_id")  # 必须有 event_id 属性
        and isinstance(value.event_id, str)  # event_id 必须是字符串
        and bool(value.event_id.strip())  # event_id 不能为空
        and callable(getattr(value, "to_payload", None))  # 必须有可调用的 to_payload 方法
    )


# ==================== 事件队列 ====================

class EventInbox:
    """线程安全的 FIFO 事件队列。

    这是什么：后台线程和主循环之间的通信管道
    Java 类比：类似 BlockingQueue<RuntimeEvent>（基于 ArrayDeque + ReentrantLock）
    为什么需要：后台线程完成任务后不能直接操作主循环状态，需要通过队列传递事件

    线程安全机制：
    - 使用 threading.Condition 保护队列（类似 Java 的 ReentrantLock + Condition）
    - publish 时唤醒所有等待线程（notify_all）
    - drain 立即取出所有就绪事件（非阻塞）
    - wait 阻塞直到有事件到达（可设置超时）
    """

    def __init__(self) -> None:
        """初始化空队列和条件变量。

        这是什么：创建 FIFO 队列和线程同步原语
        Java 类比：类似 new ArrayBlockingQueue<>() + new ReentrantLock()
        为什么需要：deque 本身不是线程安全的，需要 Condition 保护
        """
        self._events: deque[RuntimeEvent] = deque()  # 双端队列（FIFO）
        self._condition = threading.Condition()  # 条件变量（锁+信号量）

    def publish(self, event: RuntimeEvent) -> None:
        """发布一条事件，并唤醒正在等待的 Loop。

        这是什么：后台线程调用，向队列添加事件
        Java 类比：类似 queue.put(event); condition.signalAll()
        为什么需要：让后台任务能通知主循环有新事件到达

        参数：
            event: 必须实现 RuntimeEvent 接口的事件对象
        """
        if not is_runtime_event(event):
            raise TypeError("EventInbox 只接受 RuntimeEvent 对象")
        with self._condition:  # 加锁（类似 Java 的 synchronized 或 lock.lock()）
            self._events.append(event)  # 添加到队列尾部
            self._condition.notify_all()  # 唤醒所有等待的线程（类似 Java 的 notifyAll()）

    def drain(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """立即取出当前已就绪事件，保持 FIFO 顺序。

        这是什么：非阻塞取出事件，主循环调用
        Java 类比：类似 queue.drainTo(list, limit)
        为什么需要：主循环在请求模型前批量取出所有事件，避免阻塞

        参数：
            limit: 最多取出多少条（None 表示全部）

        返回：
            tuple[RuntimeEvent, ...]: 按 FIFO 顺序返回的事件列表（不可变）
        """
        if limit is not None and (isinstance(limit, bool) or limit <= 0):
            raise ValueError("limit 必须是正整数")
        with self._condition:  # 加锁
            count = len(self._events) if limit is None else min(limit, len(self._events))
            return tuple(self._events.popleft() for _ in range(count))  # 从队列头部取出

    def wait(self, limit: int | None = None, timeout: float | None = None) -> tuple[RuntimeEvent, ...]:
        """阻塞直到至少有一条事件，然后取出一批事件。

        这是什么：阻塞等待事件到达，用于后台监控线程
        Java 类比：类似 queue.take() 或 queue.poll(timeout)
        为什么需要：让监控线程能高效等待事件，而不是轮询

        参数：
            limit: 最多取出多少条（None 表示全部）
            timeout: 最长等待秒数（None 表示无限等待）

        返回：
            tuple[RuntimeEvent, ...]: 取出的事件（超时返回空元组）
        """
        with self._condition:  # 加锁
            if not self._events and not self._condition.wait(timeout):  # 等待事件或超时
                return ()  # 超时返回空
            return self.drain(limit)  # 有事件时取出


# ==================== 事件消息转换 ====================

def runtime_event_message(event: RuntimeEvent, index: int = 0, total: int = 1) -> ChatMessage:
    """把事件包装成普通 user 消息，绝不伪装成 tool result。

    这是什么：把后台事件转换为 Agent 循环可理解的 user 消息
    Java 类比：类似 ChatMessage wrapEvent(RuntimeEvent event)
    为什么需要：Agent 循环只接受标准消息，事件必须包装成 user 消息而不是伪造 tool 结果

    设计要点：
    - 使用 user 消息类型（不伪装成 tool，避免破坏消息配对契约）
    - JSON 包装（runtime_event 字段 + batch 信息）
    - 支持批处理（index/total 标识这是一批事件中的第几个）

    参数：
        event: 要包装的运行时事件
        index: 批处理中的索引（从 0 开始）
        total: 批处理的总数

    返回：
        ChatMessage: 包装成 user 消息的事件
    """
    if not is_runtime_event(event):
        raise TypeError("event 必须是 RuntimeEvent")
    if index < 0 or total <= 0 or index >= total:
        raise ValueError("batch 位置必须满足 0 <= index < total")

    # 构造 JSON payload：包含事件数据和批处理信息
    payload = {"runtime_event": dict(event.to_payload()), "batch": {"index": index, "total": total}}
    return user_message(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))  # 紧凑 JSON
