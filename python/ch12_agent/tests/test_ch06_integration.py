from pathlib import Path

from agent_ch12.bootstrap import build_agent
from agent_ch12.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch12.core.model import ModelReply
from agent_ch12.core.permissions import PermissionDecision, PermissionRequest
from agent_ch12.core.profiles import P06
from agent_ch12.features.subagents import DEFAULT_SUBAGENT_SYSTEM_PROMPT


class FakeModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class Approval:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return PermissionDecision("allow", "测试批准", "test-approval")


class Audit:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        self.records.append((request.prepared.call.name, decision.behavior))


def test_p06_isolates_child_history_and_preserves_file_side_effect(tmp_path: Path) -> None:
    parent_call = tool_call(
        "parent-task", "task", '{"description":" write child.txt with evidence "}'
    )
    child_write = tool_call(
        "child-write", "write_file", '{"path":"child.txt","content":"child evidence"}'
    )
    parent = FakeModel(
        [
            ModelReply(assistant_message(None, (parent_call,)), "tool_calls"),
            ModelReply(assistant_message("父结论"), "stop"),
        ]
    )
    child = FakeModel(
        [
            ModelReply(assistant_message(None, (child_write,)), "tool_calls"),
            ModelReply(assistant_message("子结论"), "stop"),
        ]
    )
    approval, audit = Approval(), Audit()
    result = build_agent(
        P06,
        parent,
        str(tmp_path),
        approval_provider=approval,
        audit_sink=audit,
        subagent_model_factory=lambda: child,
    ).run("委派写入")
    assert (tmp_path / "child.txt").read_text(encoding="utf-8") == "child evidence"
    assert [tool.name for tool in parent.requests[0].tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
        "task",
    ]
    assert [tool.name for tool in child.requests[0].tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
    ]
    assert child.requests[0].messages[0].content == DEFAULT_SUBAGENT_SYSTEM_PROMPT
    assert result.history[2].content == "子结论" and len(result.history) == 4
    assert [request.prepared.call.name for request in approval.requests] == ["write_file"]
    assert audit.records == [("task", "allow"), ("write_file", "allow")]
    validate_tool_pairing(result.history)


def test_child_cannot_escape_workspace_even_when_approval_allows(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-ch07.txt"
    outside.write_text("sentinel", encoding="utf-8")
    parent_call = tool_call("parent-task", "task", '{"description":"write outside"}')
    child_write = tool_call(
        "outside-write", "write_file", '{"path":"../outside-ch07.txt","content":"changed"}'
    )
    parent = FakeModel(
        [
            ModelReply(assistant_message(None, (parent_call,)), "tool_calls"),
            ModelReply(assistant_message("父结论"), "stop"),
        ]
    )
    child = FakeModel(
        [
            ModelReply(assistant_message(None, (child_write,)), "tool_calls"),
            ModelReply(assistant_message("写入被拒绝"), "stop"),
        ]
    )
    approval, audit = Approval(), Audit()
    result = build_agent(
        P06,
        parent,
        str(tmp_path),
        approval_provider=approval,
        audit_sink=audit,
        subagent_model_factory=lambda: child,
    ).run("危险委派")
    assert outside.read_text(encoding="utf-8") == "sentinel"
    assert approval.requests == []
    assert audit.records == [("task", "allow"), ("write_file", "deny")]
    assert (
        child.requests[1].messages[-1].content
        == "工具执行错误 [permission_denied]: 禁止写入工作区之外"
    )
    assert result.history[2].content == "写入被拒绝"
    validate_tool_pairing(result.history)
