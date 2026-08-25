"""第十二章 JSON Task DAG 的领域、持久化和工具测试。"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_ch19.adapters.task_json import JsonTaskStore
from agent_ch19.core.messages import tool_call
from agent_ch19.core.tools import ToolContext, ToolRegistry
from agent_ch19.features.tasks import (
    CreateTaskInput,
    TaskBlockedError,
    TaskGraphError,
    TaskNotFoundError,
    TaskOwnershipError,
    TaskStateError,
    TaskStorageError,
    register_task_tools,
)

IDS = (
    "11111111-1111-4111-8111-111111111111",
    "22222222-2222-4222-8222-222222222222",
    "33333333-3333-4333-8333-333333333333",
    "44444444-4444-4444-8444-444444444444",
)


def _ids(values: tuple[str, ...] = IDS):
    remaining = list(values)

    def generate() -> str:
        if not remaining:
            raise AssertionError("测试 UUID 已用完")
        return remaining.pop(0)

    return generate


def _write_raw_task(root: Path, task_id: str, **updates: object) -> None:
    task_root = root / ".agent_tutorial" / ".tasks"
    task_root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "blocked_by": [],
        "description": "",
        "id": task_id,
        "owner": None,
        "status": "pending",
        "subject": "磁盘任务",
    }
    payload.update(updates)
    (task_root / f"{task_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def test_empty_reads_and_missing_mutations_do_not_create_storage(tmp_path: Path) -> None:
    store = JsonTaskStore(str(tmp_path))
    assert store.list_tasks() == ()
    with pytest.raises(TaskNotFoundError):
        store.get_task(IDS[0])
    with pytest.raises(TaskNotFoundError):
        store.claim_task(IDS[0], "worker")
    with pytest.raises(TaskNotFoundError):
        store.complete_task(IDS[0], "worker")
    assert not (tmp_path / ".agent_tutorial").exists()


def test_rejects_missing_and_self_dependencies_before_writing(tmp_path: Path) -> None:
    with pytest.raises(TaskGraphError, match="依赖不存在"):
        JsonTaskStore(str(tmp_path), id_generator=_ids((IDS[0],))).create_task(
            CreateTaskInput("缺失依赖", blocked_by=(IDS[1],))
        )
    with pytest.raises(TaskGraphError, match="不能依赖自己"):
        JsonTaskStore(str(tmp_path), id_generator=_ids((IDS[0],))).create_task(
            CreateTaskInput("自依赖", blocked_by=(IDS[0],))
        )
    assert JsonTaskStore(str(tmp_path)).list_tasks() == ()


def test_fails_closed_on_corrupt_invalid_or_cyclic_persisted_graph(tmp_path: Path) -> None:
    task_root = tmp_path / ".agent_tutorial" / ".tasks"
    task_root.mkdir(parents=True)
    (task_root / f"{IDS[0]}.json").write_text("{不是 JSON", encoding="utf-8")
    with pytest.raises(TaskStorageError, match=IDS[0]):
        JsonTaskStore(str(tmp_path)).list_tasks()

    (task_root / f"{IDS[0]}.json").unlink()
    _write_raw_task(tmp_path, IDS[0], blocked_by=[IDS[1]])
    _write_raw_task(tmp_path, IDS[1], blocked_by=[IDS[0]])
    with pytest.raises(TaskGraphError, match="存在环"):
        JsonTaskStore(str(tmp_path)).list_tasks()


def test_id_collision_and_failed_atomic_update_preserve_existing_bytes(tmp_path: Path) -> None:
    store = JsonTaskStore(str(tmp_path), id_generator=_ids((IDS[0],)))
    task = store.create_task(CreateTaskInput("保留", "原内容"))
    path = tmp_path / ".agent_tutorial" / ".tasks" / f"{task.id}.json"
    before = path.read_bytes()
    with pytest.raises(TaskGraphError, match="已存在"):
        JsonTaskStore(str(tmp_path), id_generator=_ids((IDS[0],))).create_task(
            CreateTaskInput("覆盖")
        )

    def fail_replace(_path: Path, _content: bytes) -> None:
        raise OSError("模拟磁盘故障")

    with pytest.raises(TaskStorageError, match="持久化失败"):
        JsonTaskStore(str(tmp_path), atomic_replace=fail_replace).claim_task(task.id, "worker")
    assert path.read_bytes() == before


def test_invalid_transitions_preserve_state_and_enforce_owner(tmp_path: Path) -> None:
    store = JsonTaskStore(str(tmp_path), id_generator=_ids((IDS[0],)))
    pending = store.create_task(CreateTaskInput("状态测试"))
    with pytest.raises(TaskStateError):
        store.complete_task(pending.id, "worker")
    claimed = store.claim_task(pending.id, "worker-a")
    with pytest.raises(TaskStateError):
        store.claim_task(pending.id, "worker-b")
    with pytest.raises(TaskOwnershipError, match="worker-a"):
        store.complete_task(pending.id, "worker-b")
    assert store.get_task(pending.id) == claimed


def test_rebuilds_graph_and_reports_only_direct_newly_unblocked_tasks(tmp_path: Path) -> None:
    store = JsonTaskStore(str(tmp_path), id_generator=_ids())
    schema = store.create_task(CreateTaskInput("schema"))
    endpoints = store.create_task(CreateTaskInput("endpoints", blocked_by=(schema.id,)))
    tests = store.create_task(CreateTaskInput("tests", blocked_by=(endpoints.id, schema.id)))
    docs = store.create_task(CreateTaskInput("docs", blocked_by=(schema.id,)))
    endpoint_path = tmp_path / ".agent_tutorial" / ".tasks" / f"{endpoints.id}.json"
    before = endpoint_path.read_bytes()
    with pytest.raises(TaskBlockedError):
        store.claim_task(endpoints.id, "worker")
    assert endpoint_path.read_bytes() == before

    store.claim_task(schema.id, "worker")
    completion = store.complete_task(schema.id, "worker")
    assert [task.id for task in completion.unblocked] == sorted((docs.id, endpoints.id))
    assert tests.id not in {task.id for task in completion.unblocked}
    assert store.get_task(endpoints.id).status == "pending"
    assert JsonTaskStore(str(tmp_path)).list_tasks() == store.list_tasks()


def test_two_store_instances_have_exactly_one_concurrent_claim_winner(tmp_path: Path) -> None:
    first = JsonTaskStore(str(tmp_path), id_generator=_ids((IDS[0],)))
    second = JsonTaskStore(str(tmp_path))
    task = first.create_task(CreateTaskInput("只能认领一次"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(first.claim_task, task.id, "worker-a"),
            executor.submit(second.claim_task, task.id, "worker-b"),
        ]
    successes = [future.result() for future in futures if future.exception() is None]
    failures = [future.exception() for future in futures if future.exception() is not None]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], TaskStateError)
    winner = first.get_task(task.id).owner
    assert winner in {"worker-a", "worker-b"}
    non_owner = "worker-b" if winner == "worker-a" else "worker-a"
    with pytest.raises(TaskOwnershipError):
        first.complete_task(task.id, non_owner)
    first.complete_task(task.id, str(winner))
    assert second.get_task(task.id).status == "completed"


def test_registers_five_strict_tools_and_runs_owner_checked_workflow(tmp_path: Path) -> None:
    store = JsonTaskStore(str(tmp_path), id_generator=_ids())
    registry = ToolRegistry()
    register_task_tools(registry, store)
    assert registry.names == (
        "create_task",
        "get_task",
        "list_tasks",
        "claim_task",
        "complete_task",
    )
    invalid = registry.prepare(tool_call("bad", "create_task", '{"subject":"x","owner":"伪造"}'))
    assert invalid.error is not None
    assert invalid.error.error_code == "invalid_arguments"

    context = ToolContext(str(tmp_path), "worker-a")

    def invoke(call_id: str, name: str, arguments: dict[str, object], identity: str = "worker-a"):
        prepared = registry.prepare(
            tool_call(call_id, name, json.dumps(arguments, ensure_ascii=False))
        )
        return registry.invoke(prepared, ToolContext(str(tmp_path), identity))

    schema = invoke("1", "create_task", {"subject": "schema"})
    endpoint = invoke("2", "create_task", {"subject": "endpoint", "blocked_by": [IDS[0]]})
    blocked = invoke("3", "claim_task", {"task_id": IDS[1]}, "worker-b")
    claimed = invoke("4", "claim_task", {"task_id": IDS[0]})
    wrong_owner = invoke("5", "complete_task", {"task_id": IDS[0]}, "worker-b")
    completed = invoke("6", "complete_task", {"task_id": IDS[0]})
    listed = invoke("7", "list_tasks", {})
    assert json.loads(schema.content)["status"] == "pending"
    assert json.loads(endpoint.content)["blocked_by"] == [IDS[0]]
    assert blocked.error_code == "task_blocked"
    assert json.loads(claimed.content)["owner"] == context.identity
    assert wrong_owner.error_code == "task_owner_mismatch"
    assert [task["id"] for task in json.loads(completed.content)["unblocked"]] == [IDS[1]]
    assert [task["id"] for task in json.loads(listed.content)["tasks"]] == [IDS[0], IDS[1]]
    assert (tmp_path / ".agent_tutorial" / ".tasks" / f"{IDS[0]}.json").read_bytes().endswith(b"\n")
