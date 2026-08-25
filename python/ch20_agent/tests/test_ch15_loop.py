"""第 15 章事件回合测试。"""

from agent_ch20.adapters.background_json import JsonBackgroundJobStore
from agent_ch20.adapters.cron_json import JsonCronStore
from agent_ch20.adapters.mailbox_json import FileMailboxStore
from agent_ch20.core.events import EventInbox
from agent_ch20.core.loop import AgentRunner
from agent_ch20.core.messages import assistant_message
from agent_ch20.core.model import ModelReply
from agent_ch20.core.tools import ToolRegistry
from agent_ch20.features.background import JobSupervisor
from agent_ch20.features.cron import CronRuntime
from agent_ch20.features.mailbox import MailboxStorageError
from agent_ch20.features.teammates import TeammateRuntime


class EventModel:
    """记录模型调用次数，验证 ack 重试不重复调用模型。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, _request):  # type: ignore[no-untyped-def]
        self.calls += 1
        return ModelReply(assistant_message("handled"), "stop")


def test_mailbox_event_is_ack_after_model_and_ack_retry_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(tmp_path)), inbox)
    cron = CronRuntime(JsonCronStore(str(tmp_path)), inbox, supervisor=supervisor)
    store = FileMailboxStore(str(tmp_path))
    runtime = TeammateRuntime(store, inbox, supervisor, cron)
    runner = AgentRunner(EventModel(), ToolRegistry(), "system", str(tmp_path), event_pump=runtime)
    store.send("alice", "lead", "report", "result")
    message = store.claim("lead")
    assert message is not None
    runtime.start = lambda: None  # type: ignore[method-assign]
    try:
        inbox.publish(message)
        original = store.ack
        failed = True

        def ack_once(value):  # type: ignore[no-untyped-def]
            nonlocal failed
            if failed:
                failed = False
                raise MailboxStorageError("ack 持久化失败")
            return original(value)

        store.ack = ack_once  # type: ignore[method-assign]
        try:
            runner.run_events()
        except MailboxStorageError:
            pass
        assert runner._model.calls == 1  # type: ignore[attr-defined]
        runner.run_events()
        assert runner._model.calls == 1  # type: ignore[attr-defined]
    finally:
        runner.close()
