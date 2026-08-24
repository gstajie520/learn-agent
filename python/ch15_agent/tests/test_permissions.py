import pytest

from agent_ch15.core.messages import tool_call
from agent_ch15.core.permissions import (
    PERMISSION_BEHAVIORS,
    PermissionContractError,
    PermissionDecision,
    PermissionPolicy,
    PermissionRequest,
    PermissionRule,
)
from agent_ch15.core.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    tool_success,
)


def prepared_call(name: str, effect: str, arguments: str):
    """构造一个已通过 prepare 的测试调用，避免权限测试依赖真实文件。"""
    registry = ToolRegistry()
    required = "command" if effect == "execute" else "path"
    registry.register(
        ToolDefinition(
            name,
            f"测试工具 {name}",
            {"type": "object", "required": [required], "additionalProperties": False},
            effect,
            lambda _arguments, _context: tool_success("不应执行"),
            lambda value: set(value) == {required} and isinstance(value[required], str),
        )
    )
    prepared = registry.prepare(tool_call(f"call-{name}", name, arguments))
    assert prepared.error is None
    return prepared


class RecordingApproval:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[PermissionRequest] = []

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result  # type: ignore[return-value]


class RecordingAudit:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.decisions: list[PermissionDecision] = []

    def record(self, _request: PermissionRequest, decision: PermissionDecision) -> None:
        if self.fail:
            raise RuntimeError("审计后端不可用")
        self.decisions.append(decision)


class WriteBoundary:
    def __init__(self, result: bool | Exception) -> None:
        self.result = result

    def is_path_within_workspace(self, _workspace: str, _relative_path: str) -> bool:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def request(prepared, *recommendations: PermissionDecision) -> PermissionRequest:
    return PermissionRequest(prepared, ToolContext(".", "tester"), tuple(recommendations))


def test_defines_four_behaviors_and_deny_beats_allow() -> None:
    assert PERMISSION_BEHAVIORS == ("allow", "deny", "ask", "passthrough")
    audit = RecordingAudit()
    approval = RecordingApproval(PermissionDecision("allow", "用户允许", "approval"))
    policy = PermissionPolicy(
        rules=(
            PermissionRule("allow-read", "allow", "允许读取", lambda _request: True),
            PermissionRule("deny-read", "deny", "组织策略拒绝", lambda _request: True),
        ),
        approval=approval,
        audit=audit,
    )
    decision = policy.decide(request(prepared_call("read_file", "read", '{"path":"a"}')))
    assert decision == PermissionDecision("deny", "组织策略拒绝", "deny-read")
    assert approval.requests == []
    assert audit.decisions == [decision]


def test_ask_fails_closed_and_explicit_approval_allows() -> None:
    prepared = prepared_call("write_file", "write", '{"path":"a"}')
    rule = PermissionRule("confirm-write", "ask", "写入需要确认", lambda _request: True)
    denied = PermissionPolicy(rules=(rule,), write_boundary=WriteBoundary(True)).decide(
        request(prepared)
    )
    approval = RecordingApproval(PermissionDecision("allow", "只批准一次", "approval"))
    allowed = PermissionPolicy(
        rules=(rule,), approval=approval, write_boundary=WriteBoundary(True)
    ).decide(request(prepared))
    assert denied.behavior == "deny"
    assert denied.to_tool_result().error_code == "permission_denied"
    assert allowed == PermissionDecision("allow", "只批准一次", "approval")
    assert approval.requests[0].proposed_decision == PermissionDecision(
        "ask", "写入需要确认", "confirm-write"
    )


def test_workspace_denial_cannot_be_overridden() -> None:
    prepared = prepared_call("write_file", "write", '{"path":"../outside"}')
    approval = RecordingApproval(PermissionDecision("allow", "用户允许", "approval"))
    decision = PermissionPolicy(
        rules=(PermissionRule("allow", "allow", "项目允许", lambda _request: True),),
        approval=approval,
        write_boundary=WriteBoundary(False),
    ).decide(request(prepared, PermissionDecision("allow", "hook 允许", "hook")))
    assert decision == PermissionDecision("deny", "禁止写入工作区之外", "workspace-boundary")
    assert approval.requests == []


def test_shell_defaults_to_ask_and_reads_default_to_allow() -> None:
    shell = request(prepared_call("shell", "execute", '{"command":"pwd"}'))
    read = request(prepared_call("read_file", "read", '{"path":"a"}'))
    assert PermissionPolicy().decide(shell).behavior == "deny"
    assert PermissionPolicy().decide(read) == PermissionDecision(
        "allow", "没有权限规则阻止请求", "default"
    )


def test_contract_rejects_invalid_requests() -> None:
    decision = PermissionDecision("allow", "允许", "test")
    with pytest.raises(PermissionContractError):
        decision.to_tool_result()
    prepared = prepared_call("read_file", "read", '{"path":"a"}')
    with pytest.raises(PermissionContractError):
        PermissionRequest(prepared, ToolContext(".", "tester"), ("allow",))  # type: ignore[arg-type]
