from pathlib import Path

from agent_ch06.bootstrap import build_agent
from agent_ch06.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch06.core.model import ModelReply
from agent_ch06.core.permissions import PermissionDecision, PermissionRequest
from agent_ch06.core.profiles import P05
from agent_ch06.features.todos import TODO_STALE_REMINDER


class FakeModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class UnexpectedApproval:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        raise AssertionError("todo_write 和读取工具不应申请审批")


class Audit:
    def __init__(self) -> None:
        self.decisions: list[PermissionDecision] = []

    def record(self, _request: PermissionRequest, decision: PermissionDecision) -> None:
        self.decisions.append(decision)


def test_p05_exposes_todo_and_returns_audited_snapshot_without_approval(tmp_path: Path) -> None:
    approval, audit = UnexpectedApproval(), Audit()
    model = FakeModel(
        [
            ModelReply(
                assistant_message(
                    None,
                    (
                        tool_call(
                            "todo-1",
                            "todo_write",
                            '{"todos":[{"content":"  编写测试  ","status":"in_progress"},{"content":"ship","status":"completed"}]}',
                        ),
                    ),
                ),
                "tool_calls",
            ),
            ModelReply(assistant_message("完成"), "stop"),
        ]
    )
    result = build_agent(
        P05, model, str(tmp_path), approval_provider=approval, audit_sink=audit
    ).run("规划工作")
    assert [tool.name for tool in model.requests[0].tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
    ]
    assert "todo_write" in model.requests[0].messages[0].content
    assert approval.requests == []
    assert audit.decisions == [PermissionDecision("allow", "没有权限规则阻止请求", "default")]
    assert result.history[2].content.startswith('{"todos":[')
    validate_tool_pairing(result.history)


def test_third_stale_round_injects_only_one_temporary_reminder(tmp_path: Path) -> None:
    (tmp_path / "note.txt").write_text("安全读取", encoding="utf-8")
    replies = [
        ModelReply(
            assistant_message(
                None, (tool_call(f"read-{index}", "read_file", '{"path":"note.txt"}'),)
            ),
            "tool_calls",
        )
        for index in range(1, 5)
    ]
    replies.append(ModelReply(assistant_message("完成"), "stop"))
    model = FakeModel(replies)
    result = build_agent(
        P05, model, str(tmp_path), approval_provider=UnexpectedApproval(), audit_sink=Audit()
    ).run("重复读取")
    assert len(model.requests) == 5
    assert all(
        not any(message.content == TODO_STALE_REMINDER for message in request.messages)
        for request in model.requests[:3]
    )
    assert [message.content for message in model.requests[3].messages].count(
        TODO_STALE_REMINDER
    ) == 1
    assert not any(message.content == TODO_STALE_REMINDER for message in model.requests[4].messages)
    assert not any(message.content == TODO_STALE_REMINDER for message in result.history)
    validate_tool_pairing(result.history)
