"""第八章集成测试：验证 Skill 按需加载和路径安全边界。

这是什么：测试 P08 引入的 Skill 延迟加载功能
Java 类比：类似 Ch08SkillIntegrationTest 测试类
为什么需要：确保 Skill 不会在启动时全部加载，且文件访问受路径限制保护
"""

from pathlib import Path

from agent_ch08.bootstrap import build_agent
from agent_ch08.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch08.core.model import ModelReply
from agent_ch08.core.permissions import PermissionDecision, PermissionRequest
from agent_ch08.core.profiles import P08


class FakeModel:
    """按顺序返回预先准备的响应，等价于 Mockito 中的连续 thenReturn。"""

    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class UnexpectedApproval:
    def decide(self, _request: PermissionRequest) -> PermissionDecision:
        raise AssertionError("读取文件不应请求写入审批")


class Audit:
    def record(self, _request: PermissionRequest, _decision: PermissionDecision) -> None:
        pass


def test_p08_persists_large_tool_result_before_next_model_request(tmp_path: Path) -> None:
    """超过 30KB 的工具正文先落盘，下一轮模型只看到路径和有界预览。"""
    content = "甲" * 10_001
    (tmp_path / "large.txt").write_text(content, encoding="utf-8")
    model = FakeModel(
        [
            ModelReply(
                assistant_message(
                    None,
                    (tool_call("read-large", "read_file", '{"path":"large.txt"}'),),
                ),
                "tool_calls",
            ),
            ModelReply(assistant_message("已完成"), "stop"),
        ]
    )

    result = build_agent(
        P08,
        model,
        str(tmp_path),
        approval_provider=UnexpectedApproval(),
        audit_sink=Audit(),
    ).run("读取大文件")

    assert [tool.name for tool in model.requests[0].tools] == [
        "shell", "read_file", "write_file", "edit_file", "glob",
        "todo_write", "task", "load_skill",
    ]
    persisted = model.requests[1].messages[-1]
    assert persisted.role == "tool"
    assert "<persisted-tool-result>" in persisted.content
    path_line = next(line for line in persisted.content.splitlines() if line.startswith("path: "))
    relative_path = path_line.removeprefix("path: ")
    assert (tmp_path / Path(relative_path)).read_text(encoding="utf-8") == content
    assert result.history[2] == persisted
    validate_tool_pairing(list(result.history))
