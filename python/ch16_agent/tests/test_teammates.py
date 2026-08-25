"""第 15 章持久队友测试。"""

import time

from agent_ch16.adapters.background_json import JsonBackgroundJobStore
from agent_ch16.adapters.cron_json import JsonCronStore
from agent_ch16.adapters.mailbox_json import FileMailboxStore
from agent_ch16.core.events import EventInbox
from agent_ch16.core.loop import AgentRunner
from agent_ch16.core.messages import assistant_message
from agent_ch16.core.model import ModelReply
from agent_ch16.core.tools import ToolRegistry
from agent_ch16.features.background import JobSupervisor
from agent_ch16.features.cron import CronRuntime
from agent_ch16.features.teammates import TeammateRuntime


class ResultModel:
    """测试模型：每次调用返回队列中的一个文本。"""

    def __init__(self, *results: str) -> None:
        self.results = list(results)
        self.calls = 0

    def complete(self, _request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ModelReply(assistant_message(self.results.pop(0)), "stop")


def _runtime(root):  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(root)), inbox)
    cron = CronRuntime(JsonCronStore(str(root)), inbox, supervisor=supervisor)
    runtime = TeammateRuntime(FileMailboxStore(str(root)), inbox, supervisor, cron)
    return runtime, cron, supervisor


def test_worker_delivers_result_and_reuses_runner(tmp_path) -> None:  # type: ignore[no-untyped-def]
    runtime, cron, supervisor = _runtime(tmp_path)
    model = ResultModel("第一次结果", "第二次结果")
    runners: list[AgentRunner] = []

    def factory(name: str, role: str, send):  # type: ignore[no-untyped-def]
        tools = ToolRegistry()
        tools.register(send)
        runner = AgentRunner(
            model, tools, f"你是 {name}，职责是 {role}", str(tmp_path), identity=name
        )
        runners.append(runner)
        return runner

    runtime.configure_runner_factory(factory)
    try:
        runtime.start()
        runtime.spawn("alice", "writer", "draft", sender="lead")
        deadline = time.time() + 3
        while not runtime.has_pending_work and time.time() < deadline:
            time.sleep(0.01)
        event = runtime.wait_for_events(1)[0]
        assert event.to_payload()["content"] == "第一次结果"
        runtime.acknowledge_events((event,))
        assert runtime.state("alice").status == "idle"
        runtime.send("alice", "revise", sender="lead")
        event2 = runtime.wait_for_events(1)[0]
        assert event2.to_payload()["content"] == "第二次结果"
        runtime.acknowledge_events((event2,))
        assert len(runners) == 1
    finally:
        runtime.close()
        cron.close()
        supervisor.close()


def test_failed_worker_reports_result_and_becomes_failed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    runtime, cron, supervisor = _runtime(tmp_path)

    def factory(name: str, role: str, send):  # type: ignore[no-untyped-def]
        return AgentRunner(
            type(
                "FailModel",
                (),
                {"complete": lambda *_args: (_ for _ in ()).throw(RuntimeError("模型失败"))},
            )(),
            ToolRegistry(),
            f"{name}/{role}",
            str(tmp_path),
            identity=name,
        )

    runtime.configure_runner_factory(factory)
    try:
        runtime.start()
        runtime.spawn("alice", "writer", "fail", sender="lead")
        event = runtime.wait_for_events(1)[0]
        assert "执行失败" in str(event.to_payload()["content"])
        assert runtime.state("alice").status == "failed"
    finally:
        runtime.close()
        cron.close()
        supervisor.close()
