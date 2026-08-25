from pathlib import Path

from agent_ch20.adapters.task_json import JsonTaskStore
from agent_ch20.bootstrap import build_agent
from agent_ch20.core.messages import assistant_message, tool_call, validate_tool_pairing
from agent_ch20.core.model import ModelPromptTooLongError, ModelReply, ModelRequest
from agent_ch20.core.permissions import PermissionDecision, PermissionRequest
from agent_ch20.core.profiles import P10, P11, P12
from agent_ch20.features.memory import MemoryRecord, MemoryStore
from agent_ch20.features.recovery import RecoveryConfig


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


def _p11_config() -> RecoveryConfig:
    return RecoveryConfig("primary", "fallback", total_timeout_seconds=30)


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


def test_p11_requires_recovery_config_and_keeps_recovery_attempts_out_of_history(
    tmp_path: Path,
) -> None:
    model = ScriptedModel(
        [
            ModelReply(assistant_message("丢弃的截断回答"), "length"),
            ModelReply(assistant_message("最终回答"), "stop"),
        ]
    )
    dependencies = {
        "model": model,
        "workspace": str(tmp_path),
        "approval_provider": AllowApproval(),
        "audit_sink": NoopAudit(),
    }
    try:
        build_agent(P10, recovery_config=_p11_config(), **dependencies)
        raise AssertionError("P10 不应接受 recovery_config")
    except ValueError as error:
        assert "第十一章" in str(error)
    try:
        build_agent(P11, **dependencies)
        raise AssertionError("P11 缺少 recovery_config 时应失败")
    except ValueError as error:
        assert "recovery_config" in str(error)

    runner = build_agent(P11, recovery_config=_p11_config(), **dependencies)
    result = runner.run("开始工作")
    main_requests = [request for request in model.requests if request.tools]
    assert result.final_text == "最终回答"
    assert result.history[0].content == "开始工作"
    assert [message.content for message in result.history[1:]] == ["最终回答"]
    assert [request.max_tokens for request in main_requests] == [8_000, 64_000]
    assert [request.model for request in main_requests] == ["primary", "primary"]
    assert model.requests[-1].tools == ()
    assert model.requests[-1].model is None


def test_p11_prompt_too_long_uses_raw_summary_model_and_retries_once(tmp_path: Path) -> None:
    summary = '{"current_goal":"继续任务","key_findings":[],"files_read_or_changed":[],"remaining_work":[],"user_constraints":[]}'

    class PromptTooLongThenSuccess:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []
            self.calls = 0

        def complete(self, request: ModelRequest) -> ModelReply:
            self.requests.append(request)
            self.calls += 1
            if self.calls == 1:
                raise ModelPromptTooLongError("输入太长", error_code="context_length_exceeded")
            if not request.tools:
                return ModelReply(assistant_message(summary), "stop")
            return ModelReply(assistant_message("完成"), "stop")

    action_model = PromptTooLongThenSuccess()
    runner = build_agent(
        P11,
        action_model,
        str(tmp_path),
        recovery_config=_p11_config(),
        approval_provider=AllowApproval(),
        audit_sink=NoopAudit(),
    )
    result = runner.run("开始工作")
    main_requests = [request for request in action_model.requests if request.tools]
    side_requests = [request for request in action_model.requests if not request.tools]
    assert result.final_text == "完成"
    assert len(action_model.requests) == 4
    assert len(main_requests) == 2
    assert len(side_requests) == 2
    assert side_requests[0].model is None  # 压缩摘要直接使用原始模型。
    assert side_requests[0].max_tokens is None
    assert main_requests[1].model == "primary"
    assert main_requests[1].max_tokens == 8_000
    assert side_requests[1].model is None  # 记忆提取也不进入恢复层。


def test_p12_requires_task_store_and_appends_exactly_five_task_tools(tmp_path: Path) -> None:
    model = ScriptedModel([ModelReply(assistant_message("完成"), "stop")])
    common = {
        "model": model,
        "workspace": str(tmp_path),
        "recovery_config": _p11_config(),
        "approval_provider": AllowApproval(),
        "audit_sink": NoopAudit(),
    }
    store = JsonTaskStore(str(tmp_path))
    try:
        build_agent(P11, task_store=store, **common)
        raise AssertionError("P11 不应接受 task_store")
    except ValueError as error:
        assert "task_store" in str(error)
    try:
        build_agent(P12, **common)
        raise AssertionError("P12 缺少 task_store 时应失败")
    except ValueError as error:
        assert "task_store" in str(error)

    result = build_agent(P12, task_store=store, **common).run("检查工具")
    main_request = next(request for request in model.requests if request.tools)
    assert result.final_text == "完成"
    assert [tool.name for tool in main_request.tools] == [
        "shell",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "todo_write",
        "task",
        "load_skill",
        "create_task",
        "get_task",
        "list_tasks",
        "claim_task",
        "complete_task",
    ]
