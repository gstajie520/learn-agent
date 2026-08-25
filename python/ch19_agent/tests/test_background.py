"""第十三章后台任务的离线契约测试。"""

import json
import threading

import pytest

from agent_ch19.adapters.background_json import JsonBackgroundJobStore
from agent_ch19.core.events import EventInbox, runtime_event_message
from agent_ch19.core.tools import ToolResult, tool_success
from agent_ch19.features.background import (
    BackgroundError,
    BackgroundJob,
    BackgroundJobEvent,
    JobSupervisor,
    should_run_in_background,
)

JOB_ID = "00000000-0000-4000-8000-000000000301"
EVENT_ID = "00000000-0000-4000-8000-000000000302"


def test_three_state_background_decision() -> None:
    assert should_run_in_background("npm install", None)
    assert not should_run_in_background("Get-ChildItem", None)
    assert should_run_in_background("Get-ChildItem", True)
    assert not should_run_in_background("npm install", False)


def test_event_inbox_only_accepts_runtime_event() -> None:
    inbox = EventInbox()
    with pytest.raises(TypeError):
        inbox.publish({"event_id": "bad"})  # type: ignore[arg-type]
    event = BackgroundJobEvent(
        EVENT_ID, JOB_ID, "call-1", "shell", "completed", tool_success("完成")
    )
    inbox.publish(event)
    message = runtime_event_message(inbox.drain()[0])
    payload = json.loads(message.content or "")
    assert message.role == "user"
    assert payload["batch"] == {"index": 0, "total": 1}
    assert payload["runtime_event"]["job_id"] == JOB_ID


def test_background_job_enforces_state_invariants() -> None:
    with pytest.raises(BackgroundError):
        BackgroundJob(JOB_ID, "call", "shell", "running", tool_success("错误组合"))
    with pytest.raises(BackgroundError):
        BackgroundJob(JOB_ID, "call", "shell", "completed", ToolResult("失败", True, "x"))


def test_json_store_conditionally_finishes_and_recovers_once(tmp_path) -> None:
    store = JsonBackgroundJobStore(str(tmp_path))
    store.create_running(JOB_ID, "call-1", "shell")
    first = store.finish_running(JOB_ID, "completed", tool_success("完成"))
    second = store.finish_running(JOB_ID, "completed", tool_success("重复"))
    assert first is not None and first.status == "completed"
    assert second is None

    other = "00000000-0000-4000-8000-000000000303"
    store.create_running(other, "call-2", "shell")
    assert len(store.interrupt_running()) == 1
    assert store.interrupt_running() == ()


def test_supervisor_persists_before_worker_and_publishes_one_event(tmp_path) -> None:
    store = JsonBackgroundJobStore(str(tmp_path))
    inbox = EventInbox()
    observed: list[str] = []

    def operation(_: threading.Event) -> ToolResult:
        observed.append(store.get_job(JOB_ID).status)
        return tool_success("404 passed")

    supervisor = JobSupervisor(
        store,
        inbox,
        id_generator=lambda: JOB_ID,
        event_id_generator=lambda: EVENT_ID,
    )
    assert supervisor.submit("slow-call", "shell", operation) == JOB_ID
    assert supervisor.wait_idle(1)
    assert observed == ["running"]
    events = inbox.drain()
    assert len(events) == 1
    assert events[0].to_payload()["status"] == "completed"


def test_supervisor_cancel_returns_terminal_state(tmp_path) -> None:
    store = JsonBackgroundJobStore(str(tmp_path))
    started = threading.Event()

    def operation(cancel: threading.Event) -> ToolResult:
        started.set()
        cancel.wait(1)
        return tool_success("worker 已响应取消")

    supervisor = JobSupervisor(store, EventInbox(), id_generator=lambda: JOB_ID)
    supervisor.submit("call-1", "shell", operation)
    assert started.wait(1)
    assert supervisor.cancel(JOB_ID).status == "cancelled"
