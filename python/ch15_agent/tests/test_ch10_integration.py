from pathlib import Path

from agent_ch15.bootstrap import build_agent
from agent_ch15.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch15.core.model import ModelReply, ModelRequest
from agent_ch15.core.permissions import PermissionDecision, PermissionRequest
from agent_ch15.core.profiles import P10
from agent_ch15.features.memory import MemoryRecord, MemoryStore


class ScriptedModel:
    """顺序返回 selector、两次主循环和 extractor 的固定响应。"""

    def __init__(self, replies: list[ModelReply]) -> None:
        self._replies = replies
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        if not self._replies:
            raise AssertionError("模型脚本没有剩余响应")
        return self._replies.pop(0)


class AllowApproval:
    def decide(self, _request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision("allow", "测试允许", "test")


class NoopAudit:
    def record(self, _request: PermissionRequest, _decision: PermissionDecision) -> None:
        pass


def test_p10_uses_one_dynamic_prompt_across_tool_rounds(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "python-style"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: python-style\ndescription: Python 编码规范\n---\n# 私有正文\n",
        encoding="utf-8",
    )
    MemoryStore(str(tmp_path), id_generator=lambda: "memory").add(
        MemoryRecord("project-fact", "项目数据库规则", "project", "始终使用集成数据库。")
    )
    unknown = tool_call("unknown-1", "missing", "{}")
    model = ScriptedModel(
        [
            ModelReply(assistant_message('["project-fact"]'), "stop"),
            ModelReply(assistant_message(None, (unknown,)), "tool_calls"),
            ModelReply(assistant_message("完成"), "stop"),
            ModelReply(assistant_message("[]"), "stop"),
        ]
    )

    result = build_agent(
        P10,
        model,
        str(tmp_path),
        approval_provider=AllowApproval(),
        audit_sink=NoopAudit(),
    ).run("开始工作")

    first_main = model.requests[1]
    second_main = model.requests[2]
    prompt = first_main.messages[0].content
    assert result.final_text == "完成"
    assert "## identity" in prompt
    assert "## tools" in prompt
    assert "## workspace" in prompt
    assert "## skills" in prompt
    assert "## memory" in prompt
    assert "始终使用集成数据库" in prompt
    assert prompt.index("## identity") < prompt.index("## tools")
    assert prompt.index("## tools") < prompt.index("## workspace")
    assert prompt.index("## workspace") < prompt.index("## skills")
    assert prompt.index("## skills") < prompt.index("## memory")
    assert (
        sum("<relevant_memories>" in (message.content or "") for message in first_main.messages)
        == 1
    )
    assert second_main.messages[0] == first_main.messages[0]
    assert [tool.name for tool in first_main.tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
        "task",
        "load_skill",
    ]
    validate_tool_pairing(result.history)
    assert model._replies == []
