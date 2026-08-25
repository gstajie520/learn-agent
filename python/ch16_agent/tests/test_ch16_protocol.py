"""第 16 章协议状态机测试。"""

import time

from agent_ch16.adapters.background_json import JsonBackgroundJobStore
from agent_ch16.adapters.cron_json import JsonCronStore
from agent_ch16.adapters.mailbox_json import FileMailboxStore
from agent_ch16.adapters.protocol_json import JsonProtocolStore
from agent_ch16.core.events import EventInbox
from agent_ch16.core.loop import AgentRunner
from agent_ch16.core.messages import assistant_message
from agent_ch16.core.model import ModelReply
from agent_ch16.core.tools import ToolRegistry
from agent_ch16.features.background import JobSupervisor
from agent_ch16.features.cron import CronRuntime
from agent_ch16.features.mailbox import ProtocolMailboxMessage
from agent_ch16.features.protocol import ProtocolRuntime
from agent_ch16.features.teammates import TeammateRuntime


class Model:
    """返回固定结果并记录调用次数。"""

    def __init__(self, *values: str) -> None:
        self.values = list(values)
        self.calls = 0

    def complete(self, _request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ModelReply(assistant_message(self.values.pop(0) if self.values else "done"), "stop")


def create_runtime(root, model):  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(root)), inbox)
    cron = CronRuntime(JsonCronStore(str(root)), inbox, supervisor=supervisor)
    mailbox = FileMailboxStore(str(root))
    teammates = TeammateRuntime(mailbox, inbox, supervisor, cron)
    protocol = ProtocolRuntime(JsonProtocolStore(str(root)), teammates)
    teammates.configure_protocol(protocol)

    def factory(name: str, role: str, send):  # type: ignore[no-untyped-def]
        tools = ToolRegistry()
        tools.register(send)
        tools.register(protocol.submit_plan_tool_definition)
        return AgentRunner(model, tools, f"{name}/{role}", str(root), identity=name)

    teammates.configure_runner_factory(factory)
    teammates.start()
    return teammates, protocol, mailbox, cron, supervisor


def wait_event(runtime: TeammateRuntime):
    """轮询等待一个 Lead 事件，避免测试依赖线程调度时序。"""
    for _ in range(200):
        events = runtime.drain_events(1)
        if events:
            return events[0]
        time.sleep(0.01)
    raise AssertionError("等待协议事件超时")


def test_plan_approval_resumes_same_runner_and_shutdown_skips_model(tmp_path) -> None:  # type: ignore[no-untyped-def]
    model = Model("initial", "approved work")
    teammates, protocol, _mailbox, cron, supervisor = create_runtime(tmp_path, model)
    try:
        teammates.spawn("alice", "writer", "draft", sender="lead")
        initial = wait_event(teammates)
        teammates.acknowledge_events((initial,))
        request = protocol.submit_plan("alice", "write the config")
        plan = wait_event(teammates)
        assert isinstance(plan, ProtocolMailboxMessage)
        teammates.acknowledge_events((plan,))
        protocol.review_plan(request.id, True)
        result = wait_event(teammates)
        assert result.to_payload()["content"] == "approved work"
        assert model.calls == 2
        teammates.acknowledge_events((result,))
        shutdown = protocol.request_shutdown("alice")
        response = wait_event(teammates)
        assert isinstance(response, ProtocolMailboxMessage)
        assert response.kind == "shutdown_response"
        assert model.calls == 2
        teammates.acknowledge_events((response,))
        assert protocol.store.get_request(shutdown.id).status == "approved"
    finally:
        teammates.close()
        cron.close()
        supervisor.close()


def test_latest_unapproved_plan_blocks_effectful_tools(tmp_path) -> None:  # type: ignore[no-untyped-def]
    teammates, protocol, _mailbox, cron, supervisor = create_runtime(tmp_path, Model("done"))
    try:
        assert protocol.plan_allows_effectful("alice") is True
        request = protocol.store.create_request("plan_approval", "alice", "lead", "write")
        assert request.status == "pending"
        assert protocol.plan_allows_effectful("alice") is False
    finally:
        teammates.close()
        cron.close()
        supervisor.close()
