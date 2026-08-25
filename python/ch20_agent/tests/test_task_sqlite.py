"""第十九章 SQLite 任务仓库测试。"""

import multiprocessing
import os
from datetime import UTC, datetime, timedelta

import pytest

from agent_ch20.adapters.task_sqlite import SqliteTaskStore
from agent_ch20.features.tasks import CreateTaskInput, TaskGraphError, TaskStorageError
from agent_ch20.features.work_stealing import TaskClaimError, TaskLeaseExpiredError

IDS = iter(
    (
        "00000000-0000-4000-8000-000000001701",
        "00000000-0000-4000-8000-000000001702",
        "00000000-0000-4000-8000-000000001703",
    )
)
TOKENS = iter(
    (
        "00000000-0000-4000-8000-000000001711",
        "00000000-0000-4000-8000-000000001712",
    )
)


class FixedClock:
    """测试时钟：调用方直接推进 value，就能模拟租约过期。"""

    def __init__(self) -> None:
        self.value = datetime(2026, 7, 27, 14, tzinfo=UTC)

    def now(self) -> datetime:
        """返回当前固定时间的副本。"""
        return self.value


def _claim_in_process(workspace: str, owner: str, queue) -> None:  # type: ignore[no-untyped-def]
    """子进程入口：认领结果通过 multiprocessing Queue 返回父进程。"""
    claim = SqliteTaskStore(workspace).claim_next(owner)
    queue.put(None if claim is None else claim.task.id)


def test_sqlite_preserves_creation_order_and_dependency_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SqliteTaskStore(
        str(tmp_path), id_generator=lambda: next(IDS), claim_token_generator=lambda: next(TOKENS)
    )
    first = store.create_task(CreateTaskInput("第一步"))
    second = store.create_task(CreateTaskInput("第二步"))
    dependent = store.create_task(CreateTaskInput("最后一步", blocked_by=(first.id, second.id)))
    assert [task.id for task in store.list_tasks()] == [first.id, second.id, dependent.id]
    alice = store.claim_next("alice")
    bob = store.claim_next("bob")
    assert alice is not None and alice.task.id == first.id
    assert bob is not None and bob.task.id == second.id
    assert store.claim_next("charlie") is None
    store.complete_task(first.id, "alice", alice.claim_token)
    completion = store.complete_task(second.id, "bob", bob.claim_token)
    assert [task.id for task in completion.unblocked] == [dependent.id]


def test_sqlite_rejects_missing_dependency_without_partial_insert(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ids = iter(("00000000-0000-4000-8000-000000001701",))
    store = SqliteTaskStore(str(tmp_path), id_generator=lambda: next(ids))
    with pytest.raises(TaskGraphError):
        store.create_task(
            CreateTaskInput(
                "被阻塞任务",
                blocked_by=("00000000-0000-4000-8000-000000001799",),
            )
        )
    assert store.list_tasks() == ()


def test_lease_expiry_releases_task_but_old_token_cannot_complete(tmp_path) -> None:  # type: ignore[no-untyped-def]
    clock = FixedClock()
    ids = iter(("00000000-0000-4000-8000-000000001701",))
    tokens = iter(
        (
            "00000000-0000-4000-8000-000000001711",
            "00000000-0000-4000-8000-000000001712",
        )
    )
    store = SqliteTaskStore(
        str(tmp_path),
        id_generator=lambda: next(ids),
        claim_token_generator=lambda: next(tokens),
        clock=clock,
        lease_duration_seconds=30,
    )
    task = store.create_task(CreateTaskInput("短租约"))
    first = store.claim_next("alice")
    assert first is not None
    clock.value += timedelta(seconds=30)
    with pytest.raises(TaskLeaseExpiredError):
        store.complete_task(task.id, "alice", first.claim_token)
    replacement = store.claim_next("bob")
    assert replacement is not None
    with pytest.raises(TaskClaimError):
        store.complete_task(task.id, "alice", first.claim_token)


def test_repeated_claim_token_rolls_back_second_claim(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ids = iter(
        (
            "00000000-0000-4000-8000-000000001701",
            "00000000-0000-4000-8000-000000001702",
        )
    )
    token = "00000000-0000-4000-8000-000000001711"
    store = SqliteTaskStore(
        str(tmp_path), id_generator=lambda: next(ids), claim_token_generator=lambda: token
    )
    first = store.create_task(CreateTaskInput("第一项"))
    second = store.create_task(CreateTaskInput("第二项"))
    store.claim_task(first.id, "alice")
    with pytest.raises(TaskStorageError):
        store.claim_task(second.id, "bob")
    assert store.get_task(second.id).status == "pending"


def test_two_processes_can_claim_one_ready_task_only_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    task = SqliteTaskStore(str(tmp_path)).create_task(CreateTaskInput("并发竞争"))
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = (
        context.Process(target=_claim_in_process, args=(str(tmp_path), "alice", queue)),
        context.Process(target=_claim_in_process, args=(str(tmp_path), "bob", queue)),
    )
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    results = (queue.get(timeout=2), queue.get(timeout=2))
    assert results.count(task.id) == 1
    assert results.count(None) == 1


def test_database_hardlink_is_rejected_without_changing_outside_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    outside = tmp_path.parent / f"{tmp_path.name}-outside.sqlite3"
    outside.write_bytes(b"outside-bytes")
    state_root = tmp_path / ".agent_tutorial"
    state_root.mkdir()
    database = state_root / "tasks.sqlite3"
    os.link(outside, database)
    before = outside.read_bytes()
    try:
        with pytest.raises(TaskStorageError):
            SqliteTaskStore(str(tmp_path)).list_tasks()
        assert outside.read_bytes() == before
    finally:
        database.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)
