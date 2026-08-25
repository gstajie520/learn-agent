"""第 15 章 Mailbox Repository 测试。"""

import datetime as dt

import pytest

from agent_ch19.adapters.mailbox_json import FileMailboxStore
from agent_ch19.features.mailbox import MailboxStorageError, canonical_agent_name


def test_safe_agent_name_and_four_state_transition(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """消息应按 ready -> processing -> done 迁移，重复 ack 幂等成功。"""
    assert canonical_agent_name("api-writer") == "api-writer"
    for value in ("Lead", "../lead", "lead/other", "nul", "trailing.", "two_words"):
        with pytest.raises(ValueError):
            canonical_agent_name(value)
    store = FileMailboxStore(
        str(tmp_path),
        id_generator=lambda: "00000000-0000-4000-8000-000000000001",
        clock=lambda: dt.datetime(2026, 7, 30, 8, 0, tzinfo=dt.UTC),
    )
    message = store.send("lead", "alice", "保留原始空格 ", "task")
    assert store.claim("alice") == message
    assert store.ack(message) is True
    assert store.ack(message) is True
    assert (
        tmp_path / ".agent_tutorial" / "mailboxes" / "alice" / "done" / f"{message.id}.json"
    ).exists()


def test_bad_json_is_quarantined_without_blocking_valid_message(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """坏文件不能阻塞同一邮箱的合法消息。"""
    store = FileMailboxStore(
        str(tmp_path), id_generator=lambda: "00000000-0000-4000-8000-000000000002"
    )
    message = store.send("lead", "alice", "valid", "message")
    ready = tmp_path / ".agent_tutorial" / "mailboxes" / "alice" / "ready"
    (ready / "not-a-uuid.json").write_text("{", encoding="utf-8")
    assert store.claim("alice") == message
    assert (ready.parent / "quarantine" / "not-a-uuid.json").exists()


def test_duplicate_id_is_rejected(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """同一个工作区内 UUID 不能被第二条消息复用。"""
    generator = lambda: "00000000-0000-4000-8000-000000000003"
    first = FileMailboxStore(str(tmp_path), id_generator=generator)
    first.send("lead", "alice", "one", "task")
    with pytest.raises(MailboxStorageError):
        FileMailboxStore(str(tmp_path), id_generator=generator).send("bob", "lead", "two", "result")
