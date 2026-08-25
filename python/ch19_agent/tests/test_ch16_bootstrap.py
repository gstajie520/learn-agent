"""第 16 章组合根测试。"""

from agent_ch19.adapters.background_json import JsonBackgroundJobStore
from agent_ch19.adapters.cron_json import JsonCronStore
from agent_ch19.adapters.mailbox_json import FileMailboxStore
from agent_ch19.adapters.protocol_json import JsonProtocolStore
from agent_ch19.adapters.task_json import JsonTaskStore
from agent_ch19.bootstrap import build_agent
from agent_ch19.core.events import EventInbox
from agent_ch19.core.permissions import PermissionDecision
from agent_ch19.core.profiles import P15, P16
from agent_ch19.features.background import JobSupervisor
from agent_ch19.features.cron import CronRuntime
from agent_ch19.features.protocol import ProtocolRuntime
from agent_ch19.features.recovery import RecoveryConfig
from agent_ch19.features.teammates import TeammateRuntime


class Model:
    def complete(self, _request):  # type: ignore[no-untyped-def]
        from agent_ch19.core.messages import assistant_message
        from agent_ch19.core.model import ModelReply

        return ModelReply(assistant_message("done"), "stop")


class Approval:
    """测试审批器：允许组合根创建完整 P16 策略。"""

    def decide(self, _request):  # type: ignore[no-untyped-def]
        return PermissionDecision("allow", "测试允许", "test")


class Audit:
    """测试审计器。"""

    def record(self, _request, _decision):  # type: ignore[no-untyped-def]
        return None


def test_p16_requires_protocol_and_appends_tools(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(tmp_path)), inbox)
    cron = CronRuntime(JsonCronStore(str(tmp_path)), inbox, supervisor=supervisor)
    mailbox = FileMailboxStore(str(tmp_path))
    teammates = TeammateRuntime(mailbox, inbox, supervisor, cron)
    protocol = ProtocolRuntime(JsonProtocolStore(str(tmp_path)), teammates)
    common = {
        "model": Model(),
        "workspace": str(tmp_path),
        "background_supervisor": supervisor,
        "cron_runtime": cron,
        "mailbox_store": mailbox,
        "teammate_runtime": teammates,
        "recovery_config": RecoveryConfig("primary", "fallback"),
        "task_store": JsonTaskStore(str(tmp_path)),
        "approval_provider": Approval(),
        "audit_sink": Audit(),
    }
    try:
        try:
            build_agent(P16, **common)  # type: ignore[arg-type]
        except ValueError as error:
            assert "protocol_runtime" in str(error)
        else:
            raise AssertionError("缺少 protocol_runtime 时应拒绝启动")
        assert P15.chapter == 15
        runner = build_agent(P16, **common, protocol_runtime=protocol)  # type: ignore[arg-type]
        assert runner is not None
        runner.close()
    finally:
        teammates.close()
        cron.close()
        supervisor.close()
