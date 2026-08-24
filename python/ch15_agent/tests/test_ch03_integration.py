from pathlib import Path

from agent_ch15.adapters.filesystem import LocalWorkspaceFileSystem
from agent_ch15.bootstrap import build_agent
from agent_ch15.core.commands import CommandResult
from agent_ch15.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch15.core.model import ModelReply
from agent_ch15.core.permissions import PermissionDecision, PermissionRequest
from agent_ch15.core.profiles import P02, P03


class FakeModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies

    def complete(self, _request):
        return self.replies.pop(0)


class FakeCommandRunner:
    def run(self, _command: str, _cwd: str, _timeout_ms: int | None = None) -> CommandResult:
        return CommandResult("unused", 0, False, False)


class Approval:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return PermissionDecision("allow", "用户批准一次", "approval")


class Audit:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.decisions: list[PermissionDecision] = []

    def record(self, _request: PermissionRequest, decision: PermissionDecision) -> None:
        if self.fail:
            raise RuntimeError("审计失败")
        self.decisions.append(decision)


def model_for_write(path: str = "note.txt") -> FakeModel:
    return FakeModel(
        [
            ModelReply(
                assistant_message(
                    None,
                    (
                        tool_call(
                            "write", "write_file", f'{{"path":"{path}","content":"chapter three"}}'
                        ),
                    ),
                ),
                "tool_calls",
            ),
            ModelReply(assistant_message("完成"), "stop"),
        ]
    )


def test_p03_requires_approval_and_audit(tmp_path: Path) -> None:
    try:
        build_agent(P03, FakeModel([]), str(tmp_path))
        raise AssertionError("应该要求 approval_provider")
    except ValueError as error:
        assert "approval_provider" in str(error)
    try:
        build_agent(P03, FakeModel([]), str(tmp_path), approval_provider=Approval())
        raise AssertionError("应该要求 audit_sink")
    except ValueError as error:
        assert "audit_sink" in str(error)


def test_only_p03_adds_write_approval_and_audit(tmp_path: Path) -> None:
    fs = LocalWorkspaceFileSystem()
    p02_approval, p02_audit = Approval(), Audit()
    build_agent(
        P02,
        model_for_write(),
        str(tmp_path),
        command_runner=FakeCommandRunner(),
        file_system=fs,
        approval_provider=p02_approval,
        audit_sink=p02_audit,
    ).run("写文件")
    assert p02_approval.requests == [] and p02_audit.decisions == []
    (tmp_path / "note.txt").unlink()
    approval, audit = Approval(), Audit()
    result = build_agent(
        P03,
        model_for_write(),
        str(tmp_path),
        command_runner=FakeCommandRunner(),
        file_system=fs,
        approval_provider=approval,
        audit_sink=audit,
    ).run("写文件")
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "chapter three"
    assert len(approval.requests) == 1 and len(audit.decisions) == 1
    validate_tool_pairing(result.history)


def test_audit_failure_returns_paired_error_and_skips_handler(tmp_path: Path) -> None:
    result = build_agent(
        P03,
        model_for_write(),
        str(tmp_path),
        file_system=LocalWorkspaceFileSystem(),
        approval_provider=Approval(),
        audit_sink=Audit(fail=True),
    ).run("写文件")
    assert not (tmp_path / "note.txt").exists()
    assert result.history[2].content == "工具执行错误 [permission_evaluation_error]: 权限评估失败"
    validate_tool_pairing(result.history)
