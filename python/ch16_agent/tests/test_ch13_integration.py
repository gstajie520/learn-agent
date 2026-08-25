"""P13 Profile 和工具表的组合测试。"""

from pathlib import Path

from agent_ch16.adapters.background_json import JsonBackgroundJobStore
from agent_ch16.adapters.task_json import JsonTaskStore
from agent_ch16.bootstrap import build_agent
from agent_ch16.core.messages import assistant_message
from agent_ch16.core.model import ModelReply
from agent_ch16.core.profiles import P13, profile_for_chapter
from agent_ch16.features.recovery import RecoveryConfig


class StubModel:
    def complete(self, request):  # type: ignore[no-untyped-def]
        return ModelReply(assistant_message("完成"), "stop")


class AllowApproval:
    def decide(self, request):  # type: ignore[no-untyped-def]
        from agent_ch16.core.permissions import PermissionDecision

        return PermissionDecision("allow", "测试允许", "test")


class Audit:
    def record(self, request, decision):  # type: ignore[no-untyped-def]
        return None


def test_p13_profile_and_main_tools(tmp_path: Path) -> None:
    assert profile_for_chapter(13) is P13
    runner = build_agent(
        P13,
        StubModel(),
        str(tmp_path),
        approval_provider=AllowApproval(),
        audit_sink=Audit(),
        recovery_config=RecoveryConfig("main", "fallback"),
        task_store=JsonTaskStore(str(tmp_path)),
        background_store=JsonBackgroundJobStore(str(tmp_path)),
    )
    names = runner._tools.names
    assert names[-2:] == ("query_background_job", "cancel_background_job")
    shell = runner._tools.snapshot().openai_tools()[0]
    assert "run_in_background" in shell.parameters["properties"]
    runner.close()
