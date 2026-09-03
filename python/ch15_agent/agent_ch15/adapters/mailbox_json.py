"""Mailbox 的 JSON 文件 Repository 实现。

每条消息独占一个 JSON 文件，目录名就是状态。Java 开发可以把 ``rename`` 理解成
数据库中的条件更新：只有拿到 ``processing`` 租约的消费者才能 ack/release。

Java 类比：
    - FileMailboxStore = 文件版 MailboxRepository 实现
    - _atomic_write = Files.move(tmp, target, ATOMIC_MOVE)
    - _move = UPDATE WHERE state='processing' AND id=?
    - _locked = @Transactional 或 ReentrantLock
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from ..features.mailbox import (
    MAILBOX_KINDS,
    MAILBOX_STATES,
    MailboxMessage,
    MailboxMessageKind,
    MailboxState,
    MailboxStorageError,
    canonical_agent_name,
    canonical_message_id,
    format_utc,
    messages_equal,
    new_message,
)

# 全局进程锁注册表（每个工作区一把锁）
# Java 类比：类似 ConcurrentHashMap<String, ReentrantLock>
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()  # 保护 _LOCKS 字典的元锁


class FileMailboxStore:
    """把四态 Mailbox 保存到 ``.agent_tutorial/mailboxes``。

    这是什么：MailboxStore Protocol 的文件系统实现
    Java 类比：类似 JPA Repository 的文件版实现
    为什么需要：提供可靠的消息持久化和原子状态迁移

    目录结构：
        .agent_tutorial/mailboxes/
            {recipient}/
                ready/{id}.json        # 等待被消费
                processing/{id}.json   # 正在处理（租约）
                done/{id}.json         # 已完成
                quarantine/{id}.json   # 隔离坏消息

    核心设计：
        - 目录名即状态：状态迁移 = 文件 rename
        - 临时文件 + fsync + rename：原子写入三段式
        - 全工作区锁：防止并发写入冲突
        - processing 状态即租约：只有持有者可迁移
    """

    def __init__(
        self,
        workspace: str,
        *,
        id_generator: Callable[[], str] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        """初始化 Mailbox 文件存储。

        参数：
            workspace: 工作区根目录
            id_generator: 可选的 UUID 生成器（测试时注入固定 ID）
            clock: 可选的时钟函数（测试时注入固定时间）
        """
        self.workspace = Path(workspace).resolve()  # 受控工作区根目录
        self.root = self.workspace / ".agent_tutorial" / "mailboxes"  # 所有邮箱共同根目录
        self.lock_path = (
            self.workspace / ".agent_tutorial" / ".mailboxes.lock"  # 跨实现可见的锁标记
        )
        self._id_generator = id_generator or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def send(
        self, sender: str, recipient: str, content: str, kind: MailboxMessageKind
    ) -> MailboxMessage:
        """原子写入接收者 ready 目录，并拒绝全工作区 UUID 冲突。

        这是什么：发送消息到接收方邮箱
        Java 类比：类似 repository.save(message)
        为什么需要：原子写入保证消息不丢失，UUID 冲突检测防止重复

        参数：
            sender: 发送方 Agent 名称
            recipient: 接收方 Agent 名称
            content: 消息正文
            kind: 消息类型（task/message/result）

        返回：
            MailboxMessage: 已持久化的消息对象

        异常：
            MailboxStorageError: 字段校验失败或 UUID 冲突
        """
        with self._locked(create=True):  # 获取工作区级锁
            try:
                message = new_message(
                    sender,
                    recipient,
                    content,
                    kind,
                    message_id=self._id_generator(),
                    now=self._clock(),
                )
            except Exception as error:
                raise MailboxStorageError(f"Mailbox 消息字段校验失败: {error}") from error
            directories = self._ensure_mailbox(message.recipient)
            # 全工作区 UUID 唯一性检查
            if self._paths_for_id(message.id):
                raise MailboxStorageError(f"Mailbox 消息 id 已存在: {message.id}")
            # 原子写入 ready 目录
            self._atomic_write(directories["ready"] / f"{message.id}.json", self._to_json(message))
            return message

    def claim(self, recipient: str) -> MailboxMessage | None:
        """按 ``created_at_utc, id`` 原子认领最早 ready 消息。

        这是什么：从邮箱取出一条消息，获取租约
        Java 类比：类似 SELECT FOR UPDATE 或消息队列的 poll()
        为什么需要：租约机制防止多个消费者同时处理同一条消息

        参数：
            recipient: 接收方 Agent 名称

        返回：
            MailboxMessage: 获取到的消息（已迁移到 processing）
            None: 邮箱为空

        原子操作：ready/{id}.json → processing/{id}.json
        """
        recipient = canonical_agent_name(recipient)
        with self._locked(create=False):  # 获取工作区级锁
            directories = self._existing_mailbox(recipient)
            if directories is None:
                return None
            # 读取所有 ready 消息（自动隔离坏文件）
            candidates = self._valid_entries(directories, "ready", recipient)
            if not candidates:
                return None
            # 按时间戳和 ID 排序，取最早的一条
            message, source = min(candidates, key=lambda item: (item[0].created_at_utc, item[0].id))
            # 原子迁移到 processing（获取租约）
            self._move(source, directories["processing"] / source.name)
            return message

    def ack(self, message: MailboxMessage) -> bool:
        """将 processing 消息迁移到 done；相同完整消息重复 ack 成功。

        这是什么：确认消息已处理完成，释放租约
        Java 类比：类似 Kafka 的 commit() 或 RabbitMQ 的 basicAck()
        为什么需要：只有处理成功后才标记为 done，保证 at-least-once 语义

        参数：
            message: 完整消息快照（用于校验租约持有者）

        返回：
            True: 确认成功
            False: 租约已被释放或消息不存在

        原子操作：processing/{id}.json → done/{id}.json
        """
        return self._transition(message, "done")

    def release(self, message: MailboxMessage) -> bool:
        """将 processing 租约退回 ready，供下次重试。

        这是什么：释放租约，让消息回到队列
        Java 类比：类似 RabbitMQ 的 basicNack(requeue=true)
        为什么需要：处理失败时让消息可以被重新消费

        参数：
            message: 完整消息快照

        返回：
            True: 释放成功
            False: 租约已被释放或消息不存在

        原子操作：processing/{id}.json → ready/{id}.json
        """
        return self._transition(message, "ready")

    def quarantine(self, message: MailboxMessage) -> bool:
        """将不可重试消息移到 quarantine，保留审计证据。

        这是什么：隔离坏消息
        Java 类比：类似 RabbitMQ 的 Dead Letter Queue
        为什么需要：JSON 损坏或不可重试错误的消息需要隔离，不能阻塞其他消息

        参数：
            message: 完整消息快照

        返回：
            True: 隔离成功
            False: 租约已被释放或消息不存在

        原子操作：processing/{id}.json → quarantine/{id}.json
        """
        return self._transition(message, "quarantine")

    def recover_processing(self, recipient: str) -> int:
        """进程启动时把遗留 processing 消息全部恢复为 ready。

        这是什么：恢复遗留租约
        Java 类比：类似 Spring 的 @EventListener(ContextRefreshedEvent)
        为什么需要：进程崩溃后，processing 消息的原消费者已不存在，需要重新处理

        调用时机：
            - TeammateRuntime.start() - 恢复 Lead 租约
            - TeammateRuntime.spawn() - 恢复队友租约

        参数：
            recipient: 接收方名称

        返回：
            恢复的消息数量

        原子操作：所有 processing/{id}.json → ready/{id}.json
        """
        recipient = canonical_agent_name(recipient)
        with self._locked(create=False):
            directories = self._existing_mailbox(recipient)
            if directories is None:
                return 0
            # 读取所有 processing 消息
            entries = self._valid_entries(directories, "processing", recipient)
            # 按时间戳和 ID 排序，逐个退回 ready
            for _, source in sorted(entries, key=lambda item: (item[0].created_at_utc, item[0].id)):
                self._move(source, directories["ready"] / source.name)
            return len(entries)

    def _transition(self, message: MailboxMessage, destination: MailboxState) -> bool:
        """校验完整快照后执行 processing 到目标状态的原子迁移。

        这是什么：状态迁移的通用实现
        Java 类比：类似数据库的 UPDATE WHERE state='processing' AND id=?
        为什么需要：只有租约持有者可以迁移，防止并发冲突

        核心逻辑：
            1. 检查 processing 目录是否存在该消息
            2. 读取消息内容，完整快照比较
            3. 检查 UUID 冲突（同一 ID 不能出现在多个状态）
            4. 原子迁移到目标状态

        特殊处理（ack 幂等）：
            如果目标是 done 且 processing 不存在，检查 done 目录
            → 重复 ack 成功（幂等性）
        """
        if not isinstance(message, MailboxMessage):
            raise TypeError("message 必须是 MailboxMessage")
        with self._locked(create=False):
            directories = self._existing_mailbox(message.recipient)
            if directories is None:
                return False
            source = directories["processing"] / f"{message.id}.json"
            if not source.exists():
                # 特殊处理：ack 幂等（重复 ack 成功）
                if destination != "done":
                    return False
                completed = directories["done"] / f"{message.id}.json"
                if not completed.exists():
                    return False
                # 完整快照比较，防止确认不同正文的消息
                if not messages_equal(self._load(completed, message.recipient), message):
                    raise MailboxStorageError(f"消息与已完成记录不一致: {message.id}")
                return True
            # 完整快照比较，确保是当前租约持有者
            if not messages_equal(self._load(source, message.recipient), message):
                raise MailboxStorageError(f"消息与 processing 租约不一致: {message.id}")
            # UUID 冲突检测（同一 ID 不能出现在多个状态）
            collisions = [path for path in self._paths_for_id(message.id) if path != source]
            if collisions:
                raise MailboxStorageError(f"同一消息 id 出现在多个状态: {message.id}")
            # 原子迁移到目标状态
            self._move(source, directories[destination] / source.name)
            return True

    def _locked(self, *, create: bool) -> threading.RLock:
        """返回工作区级进程锁，并按需创建可见的锁文件。

        这是什么：获取工作区级可重入锁
        Java 类比：类似 ReentrantLock 或 @Transactional
        为什么需要：防止同一进程内并发写入冲突

        参数：
            create: 是否创建目录和锁文件

        返回：
            threading.RLock: 可重入锁
        """
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
            self.lock_path.touch(exist_ok=True)
        with _LOCKS_GUARD:  # 元锁保护 _LOCKS 字典
            return _LOCKS.setdefault(str(self.workspace).lower(), threading.RLock())

    def _ensure_mailbox(self, recipient: str) -> dict[MailboxState, Path]:
        """创建一个接收者的四个完整状态目录。

        这是什么：初始化邮箱目录结构
        Java 类比：类似数据库的 CREATE TABLE IF NOT EXISTS
        为什么需要：确保四态目录都存在
        """
        result: dict[MailboxState, Path] = {}
        for state in MAILBOX_STATES:
            path = self.root / recipient / state
            path.mkdir(parents=True, exist_ok=True)
            result[state] = path
        return result

    def _existing_mailbox(self, recipient: str) -> dict[MailboxState, Path] | None:
        """读取既有邮箱；缺少任一状态目录都视为存储损坏。"""
        base = self.root / recipient
        if not base.exists():
            return None
        result: dict[MailboxState, Path] = {}
        for state in MAILBOX_STATES:
            path = base / state
            if not path.is_dir():
                raise MailboxStorageError(f"邮箱 {recipient} 缺少 {state} 目录")
            result[state] = path
        return result

    def _valid_entries(
        self, directories: dict[MailboxState, Path], state: MailboxState, recipient: str
    ) -> list[tuple[MailboxMessage, Path]]:
        """读取合法消息，并把坏文件隔离而不是阻塞整个邮箱。"""
        valid: list[tuple[MailboxMessage, Path]] = []
        for source in sorted(directories[state].iterdir(), key=lambda path: path.name):
            try:
                valid.append((self._load(source, recipient), source))
            except Exception:  # noqa: BLE001
                destination = directories["quarantine"] / source.name
                index = 1
                while destination.exists():
                    destination = (
                        directories["quarantine"]
                        / f"{source.stem}.quarantine-{index}{source.suffix}"
                    )
                    index += 1
                self._move(source, destination)
        for message, source in valid:
            collisions = [path for path in self._paths_for_id(message.id) if path != source]
            if collisions:
                raise MailboxStorageError(f"同一消息 id 出现在多个状态: {message.id}")
        return valid

    def _load(self, path: Path, recipient: str) -> MailboxMessage:
        """使用严格 UTF-8 和严格字段集合读取一条消息。"""
        if not path.is_file() or path.suffix != ".json":
            raise MailboxStorageError(f"Mailbox 消息文件无效: {path.name}")
        expected_id = canonical_message_id(path.stem)
        try:
            value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except Exception as error:
            raise MailboxStorageError(f"Mailbox JSON 无效: {path.name}") from error
        expected = {"id", "sender", "recipient", "kind", "content", "created_at_utc"}
        if not isinstance(value, dict) or set(value) != expected:
            raise MailboxStorageError("Mailbox JSON 含有缺失或未知字段")
        if not all(isinstance(value[name], str) for name in expected):
            raise MailboxStorageError("Mailbox JSON 字段类型无效")
        timestamp = value["created_at_utc"]
        if not timestamp.endswith("Z"):
            raise MailboxStorageError("created_at_utc 必须是 UTC Z 时间")
        try:
            created = dt.datetime.fromisoformat(timestamp)
            message = MailboxMessage(
                value["id"],
                value["sender"],
                value["recipient"],
                value["kind"],
                value["content"],
                created,
            )
        except Exception as error:
            raise MailboxStorageError("Mailbox 消息字段校验失败") from error
        if (
            message.id != expected_id
            or message.recipient != recipient
            or message.kind not in MAILBOX_KINDS
        ):
            raise MailboxStorageError("Mailbox 文件路径与消息内容不一致")
        return message

    def _paths_for_id(self, message_id: str) -> list[Path]:
        """跨所有接收者和状态目录查找同一 UUID。"""
        if not self.root.exists():
            return []
        return [path for path in self.root.glob(f"*/*/{message_id}.json") if path.is_file()]

    @staticmethod
    def _to_json(message: MailboxMessage) -> str:
        """生成稳定 snake_case JSON，不修改原始 content。"""
        return (
            json.dumps(
                {
                    "id": message.id,
                    "sender": message.sender,
                    "recipient": message.recipient,
                    "kind": message.kind,
                    "content": message.content,
                    "created_at_utc": format_utc(message.created_at_utc),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """临时文件写入、flush、fsync 后原子 replace。"""
        temporary = path.with_name(f".{path.name}.{uuid.uuid4()}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception as error:
            raise MailboxStorageError("Mailbox 消息持久化失败") from error
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        """拒绝覆盖目标后执行原子 rename，失败时源文件仍然存在。"""
        if destination.exists():
            raise MailboxStorageError(f"Mailbox 目标状态已存在: {destination.name}")
        try:
            source.rename(destination)
        except Exception as error:
            raise MailboxStorageError("Mailbox 状态迁移失败") from error
