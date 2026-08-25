"""第十九章组合根装配约束测试。"""

from agent_ch20.adapters.background_json import JsonBackgroundJobStore
from agent_ch20.adapters.cron_json import JsonCronStore
from agent_ch20.adapters.mailbox_json import FileMailboxStore
from agent_ch20.adapters.task_sqlite import SqliteTaskStore
from agent_ch20.bootstrap import build_agent
from agent_ch20.core.events import EventInbox
from agent_ch20.core.permissions import PermissionDecision
from agent_ch20.core.profiles import P17
from agent_ch20.features.background import JobSupervisor
from agent_ch20.features.cron import CronRuntime
from agent_ch20.features.protocol import JsonProtocolStore, ProtocolRuntime
from agent_ch20.features.recovery import RecoveryConfig
from agent_ch20.features.teammates import TeammateRuntime
from agent_ch20.features.work_stealing import WorkStealingRuntime


class Model:
    def complete(self, _request):  # type: ignore[no-untyped-def]
        from agent_ch20.core.messages import assistant_message
        from agent_ch20.core.model import ModelReply

        return ModelReply(assistant_message("完成"), "stop")


class Approval:
    def decide(self, _request):  # type: ignore[no-untyped-def]
        return PermissionDecision("allow", "测试允许", "test")


class Audit:
    def record(self, _request, _decision):  # type: ignore[no-untyped-def]
        return None


def test_p17_requires_work_stealing_and_shares_sqlite_store(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(tmp_path)), inbox)
    cron = CronRuntime(JsonCronStore(str(tmp_path)), inbox, supervisor=supervisor)
    mailbox = FileMailboxStore(str(tmp_path))
    teammates = TeammateRuntime(mailbox, inbox, supervisor, cron)
    protocol = ProtocolRuntime(JsonProtocolStore(str(tmp_path)), teammates)
    store = SqliteTaskStore(str(tmp_path))
    stealing = WorkStealingRuntime(store)
    common = {
        "model": Model(),
        "workspace": str(tmp_path),
        "background_supervisor": supervisor,
        "cron_runtime": cron,
        "mailbox_store": mailbox,
        "teammate_runtime": teammates,
        "protocol_runtime": protocol,
        "recovery_config": RecoveryConfig("primary", "fallback"),
        "task_store": store,
        "approval_provider": Approval(),
        "audit_sink": Audit(),
    }
    try:
        try:
            build_agent(P17, **common)  # type: ignore[arg-type]
        except ValueError as error:
            assert "work_stealing_runtime" in str(error)
        else:
            raise AssertionError("P17 缺少 work_stealing_runtime 时应拒绝启动")
        runner = build_agent(P17, **common, work_stealing_runtime=stealing)  # type: ignore[arg-type]
        assert runner is not None
        runner.close()
    finally:
        teammates.close()
        cron.close()
        supervisor.close()
