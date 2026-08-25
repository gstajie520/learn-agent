"""第十八章队友自动认领运行时测试。"""

import json
import time

import pytest

from agent_ch18.adapters.background_json import JsonBackgroundJobStore
from agent_ch18.adapters.cron_json import JsonCronStore
from agent_ch18.adapters.mailbox_json import FileMailboxStore
from agent_ch18.adapters.task_sqlite import SqliteTaskStore
from agent_ch18.core.events import EventInbox
from agent_ch18.core.loop import RunResult
from agent_ch18.features.background import JobSupervisor
from agent_ch18.features.cron import CronRuntime
from agent_ch18.features.protocol import JsonProtocolStore, ProtocolRuntime
from agent_ch18.features.tasks import CreateTaskInput
from agent_ch18.features.teammates import TeammateRuntime
from agent_ch18.features.work_stealing import WorkStealingRuntime


class CompletingRunner:
    """模拟会主动调用 complete_task 的队友 AgentRunner。"""

    def __init__(self, store: SqliteTaskStore, owner: str) -> None:
        self.store = store
        self.owner = owner
        self.prompts: list[str] = []
        self.closed = False

    def run(self, prompt: str, *, idempotency_key: str | None = None) -> RunResult:
        """普通 mailbox 只回复；自动任务则解析 token 并完成 SQLite 任务。"""
        self.prompts.append(prompt)
        if prompt.startswith("<auto-claimed-task>"):
            payload = json.loads(prompt.splitlines()[1])
            self.store.complete_task(
                payload["task"]["id"], self.owner, payload["claim_token"]
            )
            text = "自动任务已完成"
        else:
            text = "Mailbox 任务已完成"
        return RunResult(text, (), 1)

    def close(self) -> None:
        """记录资源已经被 TeammateRuntime 关闭。"""
        self.closed = True


def test_work_stealing_requires_protocol_runtime_first(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(tmp_path)), inbox)
    cron = CronRuntime(JsonCronStore(str(tmp_path)), inbox, supervisor=supervisor)
    teammates = TeammateRuntime(FileMailboxStore(str(tmp_path)), inbox, supervisor, cron)
    try:
        with pytest.raises(RuntimeError, match="ProtocolRuntime"):
            teammates.configure_work_stealing(
                WorkStealingRuntime(SqliteTaskStore(str(tmp_path)))
            )
    finally:
        teammates.close()
        cron.close()
        supervisor.close()


def test_idle_teammate_claims_and_completes_ready_sqlite_task(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(tmp_path)), inbox)
    cron = CronRuntime(JsonCronStore(str(tmp_path)), inbox, supervisor=supervisor)
    mailbox = FileMailboxStore(str(tmp_path))
    task_store = SqliteTaskStore(str(tmp_path))
    work_stealing = WorkStealingRuntime(
        task_store, poll_interval_seconds=0.01, max_idle_polls=100
    )
    teammates = TeammateRuntime(mailbox, inbox, supervisor, cron)
    protocol = ProtocolRuntime(JsonProtocolStore(str(tmp_path)), teammates)
    teammates.configure_protocol(protocol)
    teammates.configure_work_stealing(work_stealing)
    runners: dict[str, CompletingRunner] = {}

    def factory(name: str, _role: str, _send):  # type: ignore[no-untyped-def]
        runner = CompletingRunner(task_store, name)
        runners[name] = runner
        return runner

    teammates.configure_runner_factory(factory)  # type: ignore[arg-type]
    teammates.start()
    task = task_store.create_task(CreateTaskInput("读取 README 并总结"))
    try:
        teammates.spawn("alice", "writer", "先报告已上线", sender="lead")
        for _ in range(300):
            if task_store.get_task(task.id).status == "completed":
                break
            time.sleep(0.01)
        assert task_store.get_task(task.id).status == "completed"
        assert any(prompt.startswith("<auto-claimed-task>") for prompt in runners["alice"].prompts)
        assert runners["alice"].prompts[0] == "先报告已上线"
    finally:
        teammates.close()
        cron.close()
        supervisor.close()


def test_pending_plan_blocks_automatic_claim(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(tmp_path)), inbox)
    cron = CronRuntime(JsonCronStore(str(tmp_path)), inbox, supervisor=supervisor)
    mailbox = FileMailboxStore(str(tmp_path))
    task_store = SqliteTaskStore(str(tmp_path))
    teammates = TeammateRuntime(mailbox, inbox, supervisor, cron)
    protocol = ProtocolRuntime(JsonProtocolStore(str(tmp_path)), teammates)
    teammates.configure_protocol(protocol)
    teammates.configure_work_stealing(
        WorkStealingRuntime(task_store, poll_interval_seconds=0.01, max_idle_polls=10)
    )
    teammates.configure_runner_factory(
        lambda name, _role, _send: CompletingRunner(task_store, name)  # type: ignore[arg-type]
    )
    teammates.start()
    task = task_store.create_task(CreateTaskInput("必须等待审批"))
    protocol.store.create_request("plan_approval", "alice", "lead", "执行任务")
    try:
        teammates.spawn("alice", "writer", "先上线", sender="lead")
        time.sleep(0.2)
        assert task_store.get_task(task.id).status == "pending"
    finally:
        teammates.close()
        cron.close()
        supervisor.close()
