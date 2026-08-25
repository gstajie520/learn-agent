"""P14 组合根和事件回合测试。"""

from agent_ch18.adapters.background_json import JsonBackgroundJobStore
from agent_ch18.adapters.cron_json import JsonCronStore
from agent_ch18.adapters.task_json import JsonTaskStore
from agent_ch18.bootstrap import build_agent
from agent_ch18.core.events import EventInbox
from agent_ch18.core.messages import assistant_message
from agent_ch18.core.model import ModelReply
from agent_ch18.core.profiles import P14, profile_for_chapter
from agent_ch18.features.background import JobSupervisor
from agent_ch18.features.cron import CronRuntime
from agent_ch18.features.recovery import RecoveryConfig


class StubModel:
    def complete(self, request):  # type: ignore[no-untyped-def]
        return ModelReply(assistant_message("事件已处理"), "stop")


class AllowApproval:
    def decide(self, request):  # type: ignore[no-untyped-def]
        from agent_ch18.core.permissions import PermissionDecision

        return PermissionDecision("allow", "测试允许", "test")


class Audit:
    def record(self, request, decision):  # type: ignore[no-untyped-def]
        return None


def test_p14_requires_shared_cron_runtime_and_registers_schedule_tool(tmp_path) -> None:  # type: ignore[no-untyped-def]
    inbox = EventInbox()
    supervisor = JobSupervisor(JsonBackgroundJobStore(str(tmp_path)), inbox)
    runtime = CronRuntime(JsonCronStore(str(tmp_path)), inbox, supervisor=supervisor)
    assert profile_for_chapter(14) is P14
    runner = build_agent(
        P14,
        StubModel(),
        str(tmp_path),
        approval_provider=AllowApproval(),
        audit_sink=Audit(),
        recovery_config=RecoveryConfig("main", "fallback"),
        task_store=JsonTaskStore(str(tmp_path)),
        background_store=JsonBackgroundJobStore(str(tmp_path)),
        background_supervisor=supervisor,
        cron_runtime=runtime,
    )
    assert "schedule_cron" in runner._tools.names
    runner.close()
