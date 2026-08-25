"""第十八章任务认领工具和提示协议测试。"""

import json
import threading
from datetime import UTC, datetime

from agent_ch18.core.tools import ToolContext, ToolRegistry
from agent_ch18.features.tasks import CreateTaskInput, Task, TaskCompletion
from agent_ch18.features.work_stealing import (
    TaskClaim,
    WorkStealingRuntime,
    register_leased_task_tools,
    register_teammate_leased_task_tools,
)


class FakeStore:
    """只记录工具调用的最小仓库替身。"""

    def __init__(self) -> None:
        self.created: CreateTaskInput | None = None

    def create_task(self, value: CreateTaskInput) -> Task:
        self.created = value
        return Task(
            "00000000-0000-4000-8000-000000001701",
            value.subject,
            value.description,
            "pending",
            None,
            value.blocked_by,
        )

    def get_task(self, _task_id: str) -> Task:
        raise AssertionError("测试不应调用 get_task")

    def list_tasks(self) -> tuple[Task, ...]:
        return ()

    def claim_task(self, _task_id: str, _owner: str) -> TaskClaim:
        raise AssertionError("测试不应调用 claim_task")

    def claim_next(self, _owner: str) -> TaskClaim | None:
        return None

    def complete_task(self, _task_id: str, _owner: str, _token: str) -> TaskCompletion:
        raise AssertionError("测试不应调用 complete_task")


def test_lead_has_five_tools_but_teammate_cannot_create_task() -> None:
    store = FakeStore()
    runtime = WorkStealingRuntime(store)
    lead = ToolRegistry()
    register_leased_task_tools(lead, runtime.store, runtime.claim_service)
    teammate = ToolRegistry()
    register_teammate_leased_task_tools(teammate, runtime.store, runtime.claim_service)
    assert lead.names == ("create_task", "get_task", "list_tasks", "claim_task", "complete_task")
    assert teammate.names == ("get_task", "list_tasks", "claim_task", "complete_task")


def test_create_tool_maps_blocked_by_and_claim_prompt_contains_lease() -> None:
    store = FakeStore()
    runtime = WorkStealingRuntime(store)
    tools = ToolRegistry()
    register_leased_task_tools(tools, runtime.store, runtime.claim_service)
    call = tools.prepare(
        __import__("agent_ch18.core.messages", fromlist=["tool_call"]).tool_call(
            "call-1",
            "create_task",
            json.dumps(
                {
                    "subject": "依赖任务",
                    "description": "等待前置",
                    "blocked_by": ["00000000-0000-4000-8000-000000001702"],
                }
            ),
        )
    )
    result = tools.invoke(call, ToolContext(".", "lead"))
    assert result.is_error is False
    assert store.created is not None and store.created.blocked_by == (
        "00000000-0000-4000-8000-000000001702",
    )
    task = Task(
        "00000000-0000-4000-8000-000000001701", "任务", "", "in_progress", "alice", ()
    )
    prompt = runtime.render_claim_prompt(
        TaskClaim(task, "00000000-0000-4000-8000-000000001711", datetime(2026, 1, 1, tzinfo=UTC))
    )
    assert "<auto-claimed-task>" in prompt
    assert "claim_token" in prompt and "lease_expires_at_utc" in prompt


def test_sleeper_can_be_interrupted_by_event() -> None:
    runtime = WorkStealingRuntime(FakeStore(), poll_interval_seconds=10)
    wakeup = threading.Event()
    thread = threading.Thread(target=lambda: runtime.wait_for_poll(wakeup))
    thread.start()
    wakeup.set()
    thread.join(1)
    assert not thread.is_alive()
