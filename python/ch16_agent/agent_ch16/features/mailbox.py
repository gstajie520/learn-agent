"""Mailbox 领域模型。

Java 类比：``MailboxMessage`` 是不可变 record，``MailboxStore`` 是 Repository 接口。
本文件只定义消息规则和状态机，不关心消息最终使用文件、数据库还是消息队列保存。

第 16 章关键：ProtocolMailboxMessage 是 typed 协议消息，携带 request_id 和 approved 字段，
模型不需要解析自然语言就能识别协议类型和审批结果。
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

MailboxMessageKind = Literal["task", "message", "result"]  # 普通消息三种类型
ProtocolMessageKind = Literal[
    "shutdown_request", "shutdown_response", "plan_approval_request", "plan_approval_response"
]  # 结构化协议消息四种类型（请求/响应 × 关机/计划审批）
MailboxState = Literal["ready", "processing", "done", "quarantine"]  # 消息四态
MAILBOX_KINDS: tuple[MailboxMessageKind, ...] = ("task", "message", "result")
MAILBOX_STATES: tuple[MailboxState, ...] = ("ready", "processing", "done", "quarantine")
PROTOCOL_KINDS: tuple[ProtocolMessageKind, ...] = (
    "shutdown_request",
    "shutdown_response",
    "plan_approval_request",
    "plan_approval_response",
)
LEAD_NAME = "lead"  # Lead Agent 的固定身份名

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_AGENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # 安全的小写 slug
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}  # Windows 保留设备名，不能用作目录名


class MailboxError(Exception):
    """Mailbox 领域异常，``error_code`` 可用于工具的机器可读错误码。

    这是什么：Mailbox 系统的基础异常类
    Java 类比：类似自定义的 BusinessException，error_code 相当于枚举错误码
    为什么需要：让调用方能根据 error_code 精确识别失败原因并做针对性处理
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code  # 机器可读的错误码


class MailboxStorageError(MailboxError):
    """文件损坏、状态冲突或原子迁移失败。

    这是什么：Mailbox 持久化层的异常
    Java 类比：类似 DataAccessException
    为什么需要：区分领域错误和存储错误，存储错误通常需要重试或人工介入
    """

    def __init__(self, message: str) -> None:
        super().__init__("mailbox_storage_error", message)


def canonical_agent_name(value: str) -> str:
    """校验可安全用作目录名的 Agent 小写 slug。

    这是什么：规范化 Agent 身份名，确保可以安全用作目录名
    Java 类比：类似输入校验的静态工具方法
    为什么需要：防止目录穿越攻击和 Windows 保留设备名冲突
    """
    if (
        not isinstance(value, str)
        or _AGENT_NAME.fullmatch(value) is None
        or value.lower() in _WINDOWS_RESERVED
    ):
        raise ValueError("Agent 名必须是安全的小写 slug，例如 alice 或 api-writer")
    return value


def canonical_message_id(value: str) -> str:
    """校验 canonical UUID；它同时充当事件 ID 和幂等键。

    这是什么：校验消息 ID 格式，必须是标准 UUID
    Java 类比：类似 UUID.fromString() 的校验逻辑
    为什么需要：消息 ID 同时用于去重和幂等，必须保证全局唯一性和格式一致性
    """
    if not isinstance(value, str) or _UUID.fullmatch(value) is None:
        raise ValueError("Mailbox 消息 id 必须是 canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class MailboxMessage:
    """一条可持久化、可作为 RuntimeEvent 注入 Agent Loop 的消息。

    这是什么：普通 Mailbox 消息，不可变 record
    Java 类比：类似不可变 record MailboxMessage(id, sender, recipient, kind, content, createdAt)
    为什么需要：作为队友间通信的基础消息载体，支持持久化和事件驱动
    """

    id: str  # 全局唯一消息主键（UUID），也是事件去重 ID 和幂等键
    sender: str  # 发送方 Agent 身份，例如 lead、alice
    recipient: str  # 接收方 Agent 身份，同时决定邮箱目录（.agent_tutorial/mailbox/{recipient}/）
    kind: MailboxMessageKind  # task（任务分配）、message（普通消息）或 result（结果反馈）
    content: str  # 原始正文；保存时不自动 strip，避免改变业务文本
    created_at_utc: dt.datetime  # 带 UTC 时区的创建时间，用于 FIFO 排序

    def __post_init__(self) -> None:
        canonical_message_id(self.id)
        canonical_agent_name(self.sender)
        canonical_agent_name(self.recipient)
        if self.kind not in MAILBOX_KINDS:
            raise ValueError("Mailbox 消息 kind 必须是 task、message 或 result")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("Mailbox 消息正文不能为空")
        if self.created_at_utc.tzinfo is None or self.created_at_utc.utcoffset() != dt.timedelta(0):
            raise ValueError("created_at_utc 必须是带 UTC 时区的时间")

    @property
    def event_id(self) -> str:
        """RuntimeEvent 的稳定去重 ID。"""
        return self.id

    @property
    def context_identity(self) -> str:
        """事件回合使用接收方身份，Lead 消息因此以 lead 执行。"""
        return self.recipient

    @property
    def idempotency_key(self) -> str:
        """工具副作用使用消息 UUID 去重。"""
        return self.id

    @property
    def prompt(self) -> str:
        """队友或 Lead 真正交给模型处理的正文。"""
        return self.content

    def to_payload(self) -> Mapping[str, object]:
        """转换为事件消息中的稳定 JSON 字段。"""
        return {
            "kind": "mailbox",
            "message_id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "message_kind": self.kind,
            "content": self.content,
            "created_at_utc": format_utc(self.created_at_utc),
        }


@dataclass(frozen=True, slots=True)
class ProtocolMailboxMessage:
    """带 request_id/approved 的结构化协议消息。

    这是什么：类型化的协议消息，携带结构化字段用于计划审批和优雅关机
    Java 类比：类似带领域字段的事件 record，ProtocolMailboxMessage extends MailboxMessage
    为什么需要：让模型不需要解析自然语言就能识别协议类型和审批结果，避免理解歧义

    第 16 章核心：
    - request_id 关联 ProtocolRequest，保证消息与持久化请求的一致性
    - approved 字段是机器可读的审批结论（True=批准，False=拒绝）
    - kind 区分请求/响应和关机/计划审批四种类型
    """

    id: str  # 当前传输消息 UUID（每次传输生成新 ID）
    sender: str  # 发送方身份（请求：队友，响应：lead / 关机请求：lead，响应：队友）
    recipient: str  # 接收方身份（请求：lead，响应：队友 / 关机请求：队友，响应：lead）
    kind: ProtocolMessageKind  # shutdown/plan_approval 的 request/response 四种类型
    content: str  # 展示给对方的正文或反馈（人类可读）
    created_at_utc: dt.datetime  # 传输创建时间（UTC）
    request_id: str  # 关联 ProtocolRequest 的 UUID（同一协议请求的请求和响应共享此 ID）
    approved: bool | None  # 请求必须为 None，响应必须为 bool（True=批准，False=拒绝）

    def __post_init__(self) -> None:
        canonical_message_id(self.id)
        canonical_message_id(self.request_id)
        canonical_agent_name(self.sender)
        canonical_agent_name(self.recipient)
        if self.kind not in PROTOCOL_KINDS:
            raise ValueError("协议消息 kind 无效")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("协议消息正文不能为空")
        if self.created_at_utc.tzinfo is None or self.created_at_utc.utcoffset() != dt.timedelta(0):
            raise ValueError("created_at_utc 必须是 UTC 时间")
        response = self.kind.endswith("_response")
        if response != isinstance(self.approved, bool):
            raise ValueError("协议响应 approved 必须是 bool，请求必须是 None")

    @property
    def event_id(self) -> str:
        """RuntimeEvent 去重 ID。"""
        return self.id

    @property
    def context_identity(self) -> str:
        """事件回合使用收件方身份。"""
        return self.recipient

    @property
    def idempotency_key(self) -> str:
        """协议副作用幂等键。"""
        return self.id

    @property
    def prompt(self) -> str:
        """协议路由后的模型提示由运行时另行生成。"""
        return self.content

    def to_payload(self) -> Mapping[str, object]:
        """转换为带协议标记的事件字段。"""
        return {
            "kind": "protocol",
            "message_id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "protocol_kind": self.kind,
            "content": self.content,
            "created_at_utc": format_utc(self.created_at_utc),
            "request_id": self.request_id,
            "approved": self.approved,
        }


MailboxItem = MailboxMessage | ProtocolMailboxMessage


class MailboxStore(Protocol):
    """Mailbox Repository 协议；状态迁移由实现保证原子性。

    这是什么：Mailbox 的持久化接口，定义消息的 CRUD 和状态迁移
    Java 类比：类似 Repository<MailboxMessage> 接口
    为什么需要：抽象持久化层，让领域逻辑不依赖具体存储实现（文件/数据库/消息队列）

    四态状态机：
    - ready: 新消息，等待被领取
    - processing: 已被 claim，正在处理
    - done: 已被 ack，处理完成
    - quarantine: 处理失败，需要人工介入
    """

    def send(
        self, sender: str, recipient: str, content: str, kind: MailboxMessageKind
    ) -> MailboxMessage:
        """创建并保存新消息到 ready 状态。"""
        ...
    def claim(self, recipient: str) -> MailboxItem | None:
        """原子领取一条 ready 消息，迁移到 processing 状态。"""
        ...
    def ack(self, message: MailboxItem) -> bool:
        """确认消息已处理完成，从 processing 迁移到 done。"""
        ...
    def release(self, message: MailboxItem) -> bool:
        """释放消息租约，从 processing 迁移回 ready（处理失败时使用）。"""
        ...
    def quarantine(self, message: MailboxItem) -> bool:
        """标记消息为隔离状态，从 processing 迁移到 quarantine（需要人工介入）。"""
        ...
    def recover_processing(self, recipient: str) -> int:
        """恢复僵尸 processing 消息到 ready（进程崩溃后使用）。"""
        ...


def new_message(
    sender: str,
    recipient: str,
    content: str,
    kind: MailboxMessageKind,
    *,
    message_id: str | None = None,
    now: dt.datetime | None = None,
) -> MailboxMessage:
    """创建通过统一领域校验的消息。"""
    timestamp = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    # JSON 协议只保存毫秒；构造时就截断微秒，保证内存对象和磁盘读回对象完全相等。
    timestamp = timestamp.replace(microsecond=(timestamp.microsecond // 1000) * 1000)
    return MailboxMessage(
        canonical_message_id(message_id or str(uuid.uuid4())),
        canonical_agent_name(sender),
        canonical_agent_name(recipient),
        kind,
        content,
        timestamp,
    )


def format_utc(value: dt.datetime) -> str:
    """输出严格带 ``Z`` 的 UTC ISO 字符串。"""
    return value.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def messages_equal(left: MailboxMessage, right: MailboxMessage) -> bool:
    """按完整快照比较，防止只凭相同 ID 错误确认不同正文。"""
    return left == right


def is_protocol_message(value: object) -> bool:
    """判断事件是否为 typed 协议消息。"""
    return isinstance(value, ProtocolMailboxMessage)


def protocol_messages_equal(left: ProtocolMailboxMessage, right: ProtocolMailboxMessage) -> bool:
    """按完整协议消息比较，防止错误 ack。"""
    return left == right
