from pathlib import Path

from agent_ch13.bootstrap import build_agent
from agent_ch13.core.messages import assistant_message
from agent_ch13.core.model import ModelReply, ModelRequest
from agent_ch13.core.permissions import PermissionDecision, PermissionRequest
from agent_ch13.core.profiles import P09


class ScriptedModel:
    """按顺序返回固定响应，类似 Mockito 的连续 ``thenReturn``。"""

    def __init__(self, replies: list[ModelReply]) -> None:
        self._replies = replies
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        if not self._replies:
            raise AssertionError("模型脚本已经没有可返回的响应")
        return self._replies.pop(0)

    def assert_exhausted(self) -> None:
        assert self._replies == []


class AllowApproval:
    """测试中允许需要审批的写操作；本用例实际上不会调用写工具。"""

    def decide(self, _request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision("allow", "测试允许", "test")


class NoopAudit:
    """满足第三章之后的审计依赖，本测试不关心审计内容。"""

    def record(self, _request: PermissionRequest, _decision: PermissionDecision) -> None:
        pass


def test_ch09_extracts_memory_then_selects_it_in_a_new_agent(tmp_path: Path) -> None:
    """第一个 Agent 写入记忆，第二个新 Agent 能按需读取同一份文件记忆。"""
    first_model = ScriptedModel(
        [
            ModelReply(assistant_message("已记住"), "stop"),
            ModelReply(
                assistant_message(
                    '[{"name":"project-fact","type":"project",'
                    '"description":"项目数据库规则",'
                    '"body":"始终使用集成测试数据库。"}]'
                ),
                "stop",
            ),
        ]
    )
    first_agent = build_agent(
        P09,
        first_model,
        str(tmp_path),
        approval_provider=AllowApproval(),
        audit_sink=NoopAudit(),
    )

    first_agent.run("记住数据库规则")

    second_model = ScriptedModel(
        [
            ModelReply(assistant_message('["project-fact"]'), "stop"),
            ModelReply(assistant_message("应该使用集成测试数据库"), "stop"),
            ModelReply(assistant_message("[]"), "stop"),
        ]
    )
    second_agent = build_agent(
        P09,
        second_model,
        str(tmp_path),
        approval_provider=AllowApproval(),
        audit_sink=NoopAudit(),
    )

    result = second_agent.run("我应该使用哪个数据库？")

    assert result.final_text == "应该使用集成测试数据库"
    # 请求 0 是 selector，1 是主 Agent，2 是 extractor。
    assert any(
        message.content is not None and "始终使用集成测试数据库" in message.content
        for message in second_model.requests[1].messages
    )
    assert first_model.requests[1].tools == ()
    assert second_model.requests[0].tools == ()
    assert second_model.requests[2].tools == ()
    assert [tool.name for tool in second_model.requests[1].tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
        "task",
        "load_skill",
    ]
    first_model.assert_exhausted()
    second_model.assert_exhausted()
