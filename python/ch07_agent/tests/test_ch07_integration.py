from pathlib import Path

from agent_ch07.bootstrap import build_agent
from agent_ch07.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch07.core.model import ModelReply
from agent_ch07.core.permissions import PermissionDecision, PermissionRequest
from agent_ch07.core.profiles import P07
from agent_ch07.features.subagents import DEFAULT_SUBAGENT_SYSTEM_PROMPT


class FakeModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class UnexpectedApproval:
    def decide(self, _request: PermissionRequest) -> PermissionDecision:
        raise AssertionError("load_skill 不应请求文件写入审批")


class Audit:
    def __init__(self) -> None:
        self.tools: list[str] = []

    def record(self, request: PermissionRequest, _decision: PermissionDecision) -> None:
        assert request.prepared.definition is not None
        self.tools.append(request.prepared.definition.name)


def write_skill(workspace: Path) -> None:
    directory = workspace / "skills" / "python-style"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_bytes(
        b"---\nname: python-style\ndescription: Python project conventions\n---\n"
        b"# Python Style\n\nUse pathlib for filesystem paths.\n",
    )


def test_p07_exposes_catalog_and_loads_body_without_approval(tmp_path: Path) -> None:
    write_skill(tmp_path)
    load = tool_call("skill-1", "load_skill", '{"name":"python-style"}')
    model = FakeModel(
        [
            ModelReply(assistant_message(None, (load,)), "tool_calls"),
            ModelReply(assistant_message("完成"), "stop"),
        ]
    )
    audit = Audit()

    result = build_agent(
        P07,
        model,
        str(tmp_path),
        approval_provider=UnexpectedApproval(),
        audit_sink=audit,
    ).run("加载技能")

    assert [tool.name for tool in model.requests[0].tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
        "task",
        "load_skill",
    ]
    prompt = model.requests[0].messages[0].content
    assert "python-style" in prompt and "Python project conventions" in prompt
    assert "Use pathlib" not in prompt
    assert result.history[2].content == "# Python Style\n\nUse pathlib for filesystem paths.\n"
    assert audit.tools == ["load_skill"]
    validate_tool_pairing(result.history)


def test_p07_subagent_can_load_skill_without_recursive_task(tmp_path: Path) -> None:
    write_skill(tmp_path)
    parent_task = tool_call("task-1", "task", '{"description":"load the style"}')
    child_load = tool_call("child-skill", "load_skill", '{"name":"python-style"}')
    parent = FakeModel(
        [
            ModelReply(assistant_message(None, (parent_task,)), "tool_calls"),
            ModelReply(assistant_message("父结论"), "stop"),
        ]
    )
    child = FakeModel(
        [
            ModelReply(assistant_message(None, (child_load,)), "tool_calls"),
            ModelReply(assistant_message("子结论"), "stop"),
        ]
    )
    audit = Audit()

    result = build_agent(
        P07,
        parent,
        str(tmp_path),
        approval_provider=UnexpectedApproval(),
        audit_sink=audit,
        subagent_model_factory=lambda: child,
    ).run("委派加载")

    assert [tool.name for tool in child.requests[0].tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
        "load_skill",
    ]
    assert child.requests[0].messages[0].content == DEFAULT_SUBAGENT_SYSTEM_PROMPT
    assert (
        child.requests[1].messages[-1].content
        == "# Python Style\n\nUse pathlib for filesystem paths.\n"
    )
    assert result.history[2].content == "子结论"
    assert audit.tools == ["task", "load_skill"]
    validate_tool_pairing(result.history)
