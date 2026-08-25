"""Mailbox 的 JSON 文件 Repository 实现。

每条消息独占一个 JSON 文件，目录名就是状态。Java 开发可以把 ``rename`` 理解成
数据库中的条件更新：只有拿到 ``processing`` 租约的消费者才能 ack/release。
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
    PROTOCOL_KINDS,
    MailboxItem,
    MailboxMessage,
    MailboxMessageKind,
    MailboxState,
    MailboxStorageError,
    ProtocolMailboxMessage,
    ProtocolMessageKind,
    canonical_agent_name,
    canonical_message_id,
    format_utc,
    messages_equal,
    new_message,
    protocol_messages_equal,
)

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class FileMailboxStore:
    """把四态 Mailbox 保存到 ``.agent_tutorial/mailboxes``。"""

    def __init__(
        self,
        workspace: str,
        *,
        id_generator: Callable[[], str] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()  # 受控工作区根目录。
        self.root = self.workspace / ".agent_tutorial" / "mailboxes"  # 所有邮箱共同根目录。
        self.lock_path = (
            self.workspace / ".agent_tutorial" / ".mailboxes.lock"
        )  # 跨实现可见的锁标记。
        self._id_generator = id_generator or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def send(
        self, sender: str, recipient: str, content: str, kind: MailboxMessageKind
    ) -> MailboxMessage:
        """原子写入接收者 ready 目录，并拒绝全工作区 UUID 冲突。"""
        with self._locked(create=True):
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
            if self._paths_for_id(message.id):
                raise MailboxStorageError(f"Mailbox 消息 id 已存在: {message.id}")
            self._atomic_write(directories["ready"] / f"{message.id}.json", self._to_json(message))
            return message

    def send_protocol(
        self,
        sender: str,
        recipient: str,
        content: str,
        kind: ProtocolMessageKind,
        *,
        request_id: str,
        approved: bool | None,
    ) -> ProtocolMailboxMessage:
        """原子写入 typed 协议消息，与普通消息共享四态目录。"""
        with self._locked(create=True):
            timestamp = self._clock().astimezone(dt.UTC)
            timestamp = timestamp.replace(microsecond=(timestamp.microsecond // 1000) * 1000)
            try:
                message = ProtocolMailboxMessage(
                    canonical_message_id(self._id_generator()),
                    canonical_agent_name(sender),
                    canonical_agent_name(recipient),
                    kind,
                    content,
                    timestamp,
                    canonical_message_id(request_id),
                    approved,
                )
            except Exception as error:
                raise MailboxStorageError(f"协议消息字段校验失败: {error}") from error
            directories = self._ensure_mailbox(message.recipient)
            if self._paths_for_id(message.id):
                raise MailboxStorageError(f"Mailbox 消息 id 已存在: {message.id}")
            self._atomic_write(directories["ready"] / f"{message.id}.json", self._to_json(message))
            return message

    def claim(self, recipient: str) -> MailboxItem | None:
        """按 ``created_at_utc, id`` 原子认领最早 ready 消息。"""
        recipient = canonical_agent_name(recipient)
        with self._locked(create=False):
            directories = self._existing_mailbox(recipient)
            if directories is None:
                return None
            candidates = self._valid_entries(directories, "ready", recipient)
            if not candidates:
                return None
            message, source = min(candidates, key=lambda item: (item[0].created_at_utc, item[0].id))
            self._move(source, directories["processing"] / source.name)
            return message

    def ack(self, message: MailboxItem) -> bool:
        """将 processing 消息迁移到 done；相同完整消息重复 ack 成功。"""
        return self._transition(message, "done")

    def release(self, message: MailboxItem) -> bool:
        """将 processing 租约退回 ready，供下次重试。"""
        return self._transition(message, "ready")

    def quarantine(self, message: MailboxItem) -> bool:
        """将不可重试消息移到 quarantine，保留审计证据。"""
        return self._transition(message, "quarantine")

    def recover_processing(self, recipient: str) -> int:
        """进程启动时把遗留 processing 消息全部恢复为 ready。"""
        recipient = canonical_agent_name(recipient)
        with self._locked(create=False):
            directories = self._existing_mailbox(recipient)
            if directories is None:
                return 0
            entries = self._valid_entries(directories, "processing", recipient)
            for _, source in sorted(entries, key=lambda item: (item[0].created_at_utc, item[0].id)):
                self._move(source, directories["ready"] / source.name)
            return len(entries)

    def _transition(self, message: MailboxItem, destination: MailboxState) -> bool:
        """校验完整快照后执行 processing 到目标状态的原子迁移。"""
        if not isinstance(message, (MailboxMessage, ProtocolMailboxMessage)):
            raise TypeError("message 必须是 MailboxItem")
        with self._locked(create=False):
            directories = self._existing_mailbox(message.recipient)
            if directories is None:
                return False
            source = directories["processing"] / f"{message.id}.json"
            if not source.exists():
                if destination != "done":
                    return False
                completed = directories["done"] / f"{message.id}.json"
                if not completed.exists():
                    return False
                if not self._equal(self._load(completed, message.recipient), message):
                    raise MailboxStorageError(f"消息与已完成记录不一致: {message.id}")
                return True
            if not self._equal(self._load(source, message.recipient), message):
                raise MailboxStorageError(f"消息与 processing 租约不一致: {message.id}")
            collisions = [path for path in self._paths_for_id(message.id) if path != source]
            if collisions:
                raise MailboxStorageError(f"同一消息 id 出现在多个状态: {message.id}")
            self._move(source, directories[destination] / source.name)
            return True

    def _locked(self, *, create: bool) -> threading.RLock:
        """返回工作区级进程锁，并按需创建可见的锁文件。"""
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
            self.lock_path.touch(exist_ok=True)
        with _LOCKS_GUARD:
            return _LOCKS.setdefault(str(self.workspace).lower(), threading.RLock())

    def _ensure_mailbox(self, recipient: str) -> dict[MailboxState, Path]:
        """创建一个接收者的四个完整状态目录。"""
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
    ) -> list[tuple[MailboxItem, Path]]:
        """读取合法消息，并把坏文件隔离而不是阻塞整个邮箱。"""
        valid: list[tuple[MailboxItem, Path]] = []
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

    def _load(self, path: Path, recipient: str) -> MailboxItem:
        """使用严格 UTF-8 和严格字段集合读取一条消息。"""
        if not path.is_file() or path.suffix != ".json":
            raise MailboxStorageError(f"Mailbox 消息文件无效: {path.name}")
        expected_id = canonical_message_id(path.stem)
        try:
            value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except Exception as error:
            raise MailboxStorageError(f"Mailbox JSON 无效: {path.name}") from error
        if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
            raise MailboxStorageError("Mailbox JSON 无效")
        protocol = value["kind"] in PROTOCOL_KINDS
        expected = (
            {
                "id",
                "sender",
                "recipient",
                "kind",
                "content",
                "created_at_utc",
                "request_id",
                "approved",
            }
            if protocol
            else {"id", "sender", "recipient", "kind", "content", "created_at_utc"}
        )
        if set(value) != expected:
            raise MailboxStorageError("Mailbox JSON 含有缺失或未知字段")
        if not all(isinstance(value[name], str) for name in expected - {"approved"}):
            raise MailboxStorageError("Mailbox JSON 字段类型无效")
        timestamp = value["created_at_utc"]
        if not timestamp.endswith("Z"):
            raise MailboxStorageError("created_at_utc 必须是 UTC Z 时间")
        try:
            created = dt.datetime.fromisoformat(timestamp)
            message: MailboxItem
            if protocol:
                approved = value["approved"]
                if approved is not None and not isinstance(approved, bool):
                    raise ValueError("approved 字段无效")
                message = ProtocolMailboxMessage(
                    value["id"],
                    value["sender"],
                    value["recipient"],
                    value["kind"],
                    value["content"],
                    created,
                    value["request_id"],
                    approved,
                )
            else:
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
            or (message.kind not in MAILBOX_KINDS and message.kind not in PROTOCOL_KINDS)
        ):
            raise MailboxStorageError("Mailbox 文件路径与消息内容不一致")
        return message

    def _paths_for_id(self, message_id: str) -> list[Path]:
        """跨所有接收者和状态目录查找同一 UUID。"""
        if not self.root.exists():
            return []
        return [path for path in self.root.glob(f"*/*/{message_id}.json") if path.is_file()]

    @staticmethod
    def _to_json(message: MailboxItem) -> str:
        """生成稳定 snake_case JSON，不修改原始 content。"""
        payload: dict[str, object] = {
            "id": message.id,
            "sender": message.sender,
            "recipient": message.recipient,
            "kind": message.kind,
            "content": message.content,
            "created_at_utc": format_utc(message.created_at_utc),
        }
        if isinstance(message, ProtocolMailboxMessage):
            payload.update({"request_id": message.request_id, "approved": message.approved})
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    @staticmethod
    def _equal(left: MailboxItem, right: MailboxItem) -> bool:
        """选择普通或协议的完整快照比较。"""
        if isinstance(left, ProtocolMailboxMessage) and isinstance(right, ProtocolMailboxMessage):
            return protocol_messages_equal(left, right)
        if isinstance(left, MailboxMessage) and isinstance(right, MailboxMessage):
            return messages_equal(left, right)
        return False

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
