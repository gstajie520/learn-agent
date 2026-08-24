"""Mailbox 领域模型。

Java 类比：``MailboxMessage`` 是不可变 record，``MailboxStore`` 是 Repository 接口。
本文件只定义消息规则和状态机，不关心消息最终使用文件、数据库还是消息队列保存。
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

MailboxMessageKind = Literal["task", "message", "result"]
MailboxState = Literal["ready", "processing", "done", "quarantine"]
MAILBOX_KINDS: tuple[MailboxMessageKind, ...] = ("task", "message", "result")
MAILBOX_STATES: tuple[MailboxState, ...] = ("ready", "processing", "done", "quarantine")
LEAD_NAME = "lead"

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_AGENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class MailboxError(Exception):
    """Mailbox 领域异常，``error_code`` 可用于工具的机器可读错误码。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class MailboxStorageError(MailboxError):
    """文件损坏、状态冲突或原子迁移失败。"""

    def __init__(self, message: str) -> None:
        super().__init__("mailbox_storage_error", message)


def canonical_agent_name(value: str) -> str:
    """校验可安全用作目录名的 Agent 小写 slug。"""
    if (
        not isinstance(value, str)
        or _AGENT_NAME.fullmatch(value) is None
        or value.lower() in _WINDOWS_RESERVED
    ):
        raise ValueError("Agent 名必须是安全的小写 slug，例如 alice 或 api-writer")
    return value


def canonical_message_id(value: str) -> str:
    """校验 canonical UUID；它同时充当事件 ID 和幂等键。"""
    if not isinstance(value, str) or _UUID.fullmatch(value) is None:
        raise ValueError("Mailbox 消息 id 必须是 canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class MailboxMessage:
    """一条可持久化、可作为 RuntimeEvent 注入 Agent Loop 的消息。"""

    id: str  # 全局唯一消息主键，也是事件去重 ID。
    sender: str  # 发送方 Agent 身份，例如 lead、alice。
    recipient: str  # 接收方 Agent 身份，同时决定邮箱目录。
    kind: MailboxMessageKind  # task、message 或 result。
    content: str  # 原始正文；保存时不自动 strip，避免改变业务文本。
    created_at_utc: dt.datetime  # 带 UTC 时区的创建时间，用于 FIFO 排序。

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


class MailboxStore(Protocol):
    """Mailbox Repository 协议；状态迁移由实现保证原子性。"""

    def send(
        self, sender: str, recipient: str, content: str, kind: MailboxMessageKind
    ) -> MailboxMessage: ...
    def claim(self, recipient: str) -> MailboxMessage | None: ...
    def ack(self, message: MailboxMessage) -> bool: ...
    def release(self, message: MailboxMessage) -> bool: ...
    def quarantine(self, message: MailboxMessage) -> bool: ...
    def recover_processing(self, recipient: str) -> int: ...


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
