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

# ==================== 类型定义 ====================
# Java 对照：这些类似 enum 或字面量类型

MailboxMessageKind = Literal["task", "message", "result"]  # 消息类型：任务、普通消息、结果
MailboxState = Literal["ready", "processing", "done", "quarantine"]  # 四态状态机
MAILBOX_KINDS: tuple[MailboxMessageKind, ...] = ("task", "message", "result")
MAILBOX_STATES: tuple[MailboxState, ...] = ("ready", "processing", "done", "quarantine")
LEAD_NAME = "lead"  # Lead Agent 的保留身份

# UUID 正则：标准格式 8-4-4-4-12（小写十六进制）
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Agent 名正则：小写字母数字，可用连字符分隔（例如 api-writer）
_AGENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Windows 保留设备名（这些名字不能用作目录名）
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),  # com1 到 com9
    *(f"lpt{i}" for i in range(1, 10)),  # lpt1 到 lpt9
}


# ==================== 异常定义 ====================

class MailboxError(Exception):
    """Mailbox 领域异常，``error_code`` 可用于工具的机器可读错误码。

    这是什么：Mailbox 相关的基础异常类
    Java 类比：类似自定义的 MailboxException 基类
    为什么需要：区分 Mailbox 业务错误和系统错误，提供机器可读的错误码
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class MailboxStorageError(MailboxError):
    """文件损坏、状态冲突或原子迁移失败。

    这是什么：存储层异常（文件 I/O、状态冲突）
    Java 类比：类似 DataAccessException 或 StorageException
    为什么需要：标识底层存储问题，让上层决定是否重试
    """

    def __init__(self, message: str) -> None:
        super().__init__("mailbox_storage_error", message)


# ==================== 校验函数 ====================

def canonical_agent_name(value: str) -> str:
    """校验可安全用作目录名的 Agent 小写 slug。

    这是什么：Agent 名称的安全校验函数
    Java 类比：类似 Bean Validation 的 @Pattern(regexp="^[a-z0-9-]+$")
    为什么需要：防止路径注入攻击（如 ../lead）和 Windows 保留设备名冲突

    规则：
        - 必须是小写字母和数字
        - 可用连字符分隔（例如 api-writer）
        - 不能是 Windows 保留设备名（con、prn、aux、nul、com1-9、lpt1-9）

    参数：
        value: 待校验的 Agent 名称

    返回：
        原值（校验通过时）

    异常：
        ValueError: 格式不符合规则
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

    这是什么：消息 ID 的格式校验函数
    Java 类比：类似 UUID.fromString() 的校验逻辑
    为什么需要：message.id 有三重身份（消息主键、事件 ID、幂等键），必须全局唯一

    规则：
        - 必须是标准 UUID 格式（8-4-4-4-12，小写十六进制）
        - 例如：00000000-0000-4000-8000-000000000001

    参数：
        value: 待校验的消息 ID

    返回：
        原值（校验通过时）

    异常：
        ValueError: 不是合法的 UUID 格式
    """
    if not isinstance(value, str) or _UUID.fullmatch(value) is None:
        raise ValueError("Mailbox 消息 id 必须是 canonical UUID")
    return value


# ==================== 领域模型 ====================

@dataclass(frozen=True, slots=True)  # frozen=True 表示不可变，类似 Java record
class MailboxMessage:
    """一条可持久化、可作为 RuntimeEvent 注入 Agent Loop 的消息。

    这是什么：不可变消息对象，包含完整的消息元数据
    Java 类比：record MailboxMessage(String id, String sender, String recipient, ...)
    为什么需要：消息是系统通信的基本单元，不可变性保证线程安全和一致性

    message.id 的三重身份：
        1. 消息主键（全局唯一，存储层使用）
        2. 事件去重 ID（AgentRunner._seen_event_ids 防止重复注入）
        3. 工具幂等键（ToolContext.idempotency_key 让工具副作用去重）

    四态状态机（由 MailboxStore 管理）：
        ready → processing → done
                          ↘ quarantine
    """

    id: str  # 全局唯一消息主键，也是事件去重 ID 和幂等键
    sender: str  # 发送方 Agent 身份，例如 lead、alice（由 ToolContext.identity 保证可信）
    recipient: str  # 接收方 Agent 身份，同时决定邮箱目录（例如 mailboxes/alice/）
    kind: MailboxMessageKind  # task（spawn 任务）、message（普通消息）或 result（队友结果）
    content: str  # 原始正文；保存时不自动 strip，避免改变业务文本
    created_at_utc: dt.datetime  # 带 UTC 时区的创建时间，用于 FIFO 排序

    def __post_init__(self) -> None:
        """构造后校验所有字段（dataclass 自动调用）。

        Java 类比：类似 record 的 compact constructor 或 @PostConstruct
        """
        canonical_message_id(self.id)  # 校验 UUID 格式
        canonical_agent_name(self.sender)  # 校验发送方名称
        canonical_agent_name(self.recipient)  # 校验接收方名称
        if self.kind not in MAILBOX_KINDS:
            raise ValueError("Mailbox 消息 kind 必须是 task、message 或 result")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValueError("Mailbox 消息正文不能为空")
        if self.created_at_utc.tzinfo is None or self.created_at_utc.utcoffset() != dt.timedelta(0):
            raise ValueError("created_at_utc 必须是带 UTC 时区的时间")

    @property
    def event_id(self) -> str:
        """RuntimeEvent 的稳定去重 ID。

        Java 类比：类似 @Id 注解的主键字段
        为什么需要：AgentRunner._seen_event_ids 用它防止同一消息重复注入历史
        """
        return self.id

    @property
    def context_identity(self) -> str:
        """事件回合使用接收方身份，Lead 消息因此以 lead 执行。

        Java 类比：类似 Spring Security 的 @AuthenticationPrincipal
        为什么需要：队友消息用队友身份执行，Lead 消息用 lead 身份执行，实现身份隔离
        """
        return self.recipient

    @property
    def idempotency_key(self) -> str:
        """工具副作用使用消息 UUID 去重。

        Java 类比：类似分布式系统的幂等键（Idempotency Token）
        为什么需要：防止工具副作用（如创建队友、发送消息）因重试而重复执行
        """
        return self.id

    @property
    def prompt(self) -> str:
        """队友或 Lead 真正交给模型处理的正文。

        Java 类比：类似 DTO 的 getter 方法
        为什么需要：RuntimeEvent 接口要求提供 prompt 属性
        """
        return self.content

    def to_payload(self) -> Mapping[str, object]:
        """转换为事件消息中的稳定 JSON 字段。

        Java 类比：类似 toDTO() 或序列化方法
        为什么需要：RuntimeEvent 需要提供可序列化的 payload
        """
        return {
            "kind": "mailbox",
            "message_id": self.id,
            "sender": self.sender,
            "recipient": self.recipient,
            "message_kind": self.kind,
            "content": self.content,
            "created_at_utc": format_utc(self.created_at_utc),
        }


# ==================== Repository 接口 ====================

class MailboxStore(Protocol):
    """Mailbox Repository 协议；状态迁移由实现保证原子性。

    这是什么：定义消息存储的契约（接口）
    Java 类比：interface MailboxRepository { ... }
    为什么需要：领域模型不依赖具体存储技术（文件、数据库、消息队列均可实现）

    四态状态机操作：
        send()           - 原子写入 ready 目录
        claim()          - 原子迁移 ready → processing（获取租约）
        ack()            - 原子迁移 processing → done（释放租约）
        release()        - 原子迁移 processing → ready（重试）
        quarantine()     - 原子迁移 processing → quarantine（隔离坏消息）
        recover_processing() - 启动时恢复遗留租约
    """

    def send(
        self, sender: str, recipient: str, content: str, kind: MailboxMessageKind
    ) -> MailboxMessage:
        """发送消息到接收方的 ready 邮箱。

        Java 类比：save() 或 persist()
        为什么需要：原子写入，保证消息不会丢失
        """
        ...

    def claim(self, recipient: str) -> MailboxMessage | None:
        """从接收方邮箱原子获取一条 ready 消息，迁移到 processing（获取租约）。

        Java 类比：类似消息队列的 poll() 或数据库的 SELECT FOR UPDATE
        为什么需要：租约机制防止多个消费者同时处理同一条消息

        返回：
            MailboxMessage: 获取到的消息（已迁移到 processing）
            None: 邮箱为空
        """
        ...

    def ack(self, message: MailboxMessage) -> bool:
        """确认消息已处理完成，原子迁移 processing → done（释放租约）。

        Java 类比：类似 Kafka 的 commit() 或 RabbitMQ 的 basicAck()
        为什么需要：只有处理成功后才标记为 done，保证 at-least-once 语义

        参数：
            message: 完整消息快照（用于校验租约持有者）

        返回：
            True: 确认成功
            False: 租约已被释放或消息不存在
        """
        ...

    def release(self, message: MailboxMessage) -> bool:
        """释放租约，原子迁移 processing → ready（重试）。

        Java 类比：类似 RabbitMQ 的 basicNack(requeue=true)
        为什么需要：处理失败时让消息回到队列，等待下次重试

        参数：
            message: 完整消息快照

        返回：
            True: 释放成功
            False: 租约已被释放或消息不存在
        """
        ...

    def quarantine(self, message: MailboxMessage) -> bool:
        """隔离坏消息，原子迁移 processing → quarantine。

        Java 类比：类似 RabbitMQ 的 Dead Letter Queue
        为什么需要：JSON 损坏或不可重试错误的消息需要隔离，不能阻塞其他消息

        参数：
            message: 完整消息快照

        返回：
            True: 隔离成功
            False: 租约已被释放或消息不存在
        """
        ...

    def recover_processing(self, recipient: str) -> int:
        """启动时恢复遗留租约，把所有 processing 消息退回 ready。

        Java 类比：类似 Spring 的 @EventListener(ContextRefreshedEvent)
        为什么需要：进程崩溃后，processing 消息的原消费者已不存在，需要重新处理

        参数：
            recipient: 接收方名称

        返回：
            恢复的消息数量
        """
        ...


# ==================== 工具函数 ====================

def new_message(
    sender: str,
    recipient: str,
    content: str,
    kind: MailboxMessageKind,
    *,
    message_id: str | None = None,
    now: dt.datetime | None = None,
) -> MailboxMessage:
    """创建通过统一领域校验的消息。

    这是什么：消息工厂方法
    Java 类比：类似静态工厂方法 MailboxMessage.create(...)
    为什么需要：集中处理 UUID 生成、时间戳截断和字段校验

    参数：
        sender: 发送方 Agent 名称
        recipient: 接收方 Agent 名称
        content: 消息正文
        kind: 消息类型（task/message/result）
        message_id: 可选的自定义 UUID（测试时使用）
        now: 可选的自定义时间戳（测试时使用）

    返回：
        MailboxMessage: 校验通过的消息对象
    """
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
    """输出严格带 ``Z`` 的 UTC ISO 字符串。

    这是什么：时间戳格式化函数
    Java 类比：类似 DateTimeFormatter.ISO_INSTANT
    为什么需要：保证跨语言、跨系统的时间戳一致性
    """
    return value.astimezone(dt.UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def messages_equal(left: MailboxMessage, right: MailboxMessage) -> bool:
    """按完整快照比较，防止只凭相同 ID 错误确认不同正文。

    这是什么：消息相等性校验函数
    Java 类比：类似重写的 equals() 方法
    为什么需要：ack() 时必须校验完整快照，防止确认了错误的消息版本

    场景：
        1. 消息 A 写入 processing
        2. 进程崩溃，recover_processing 退回 ready
        3. 消息 A 被重新处理，写入新的 processing
        4. 旧进程恢复，尝试 ack 旧消息
        → 完整快照比较确保 ack 的是当前正在处理的消息
    """
    return left == right
