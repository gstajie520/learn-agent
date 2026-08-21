from dataclasses import replace
from pathlib import Path

from agent_ch07.bootstrap import build_agent
from agent_ch07.core.hooks import HookRegistry, HookResult
from agent_ch07.core.loop import AgentRunner
from agent_ch07.core.messages import (
    assistant_message,
    system_message,
    tool_call,
    user_message,
    validate_tool_pairing,
)
from agent_ch07.core.model import ModelReply
from agent_ch07.core.permissions import (
    PermissionDecision,
    PermissionPolicy,
    PermissionRequest,
    PermissionRule,
)
from agent_ch07.core.profiles import P03, P04
from agent_ch07.core.tools import ToolDefinition, ToolRegistry, tool_error, tool_success


class FakeModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class Approval:
    def decide(self, _request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision("allow", "测试批准", "test-approval")


class Audit:
    def record(self, _request: PermissionRequest, _decision: PermissionDecision) -> None:
        return None


def registry(handler):
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(
            "work",
            "执行确定性测试",
            {"type": "object"},
            "read",
            handler,
            lambda args: set(args) == {"value"} and isinstance(args["value"], int),
        )
    )
    return tools


def replies(calls, final: str = "完成"):
    return [
        ModelReply(assistant_message(None, tuple(calls)), "tool_calls"),
        ModelReply(assistant_message(final), "stop"),
    ]


def test_fixed_order_and_context_rewrite(tmp_path: Path) -> None:
    trace: list[str] = []
    hooks = HookRegistry()
    hooks.register(
        "UserPromptSubmit",
        lambda _context: (
            trace.append("user") or HookResult(additional_context=(system_message("Hook 上下文"),))
        ),
    )
    hooks.register(
        "PreToolUse",
        lambda _context: trace.append("pre") or HookResult(permission_behavior="allow"),
    )
    hooks.register(
        "PostToolUse",
        lambda _context: trace.append("post") or HookResult(updated_output=tool_success("已改写")),
    )
    hooks.register("Stop", lambda _context: trace.append("stop") or HookResult())
    policy = PermissionPolicy(
        rules=(
            PermissionRule(
                "record", "allow", "测试允许", lambda _request: trace.append("permission") or True
            ),
        )
    )
    model = FakeModel(replies((tool_call("call-1", "work", '{"value":42}'),)))
    runner = AgentRunner(
        model,
        registry(
            lambda args, _context: trace.append("handler") or tool_success(str(args["value"]))
        ),
        "system",
        str(tmp_path),
        permission_policy=policy,
        hooks=hooks,
    )
    result = runner.run("开始")
    assert trace == ["user", "pre", "permission", "handler", "post", "stop"]
    assert model.requests[0].messages == (
        system_message("system"),
        user_message("开始"),
        system_message("Hook 上下文"),
    )
    assert result.history[3].content == "已改写"
    validate_tool_pairing(result.history)


def test_system_deny_beats_hook_allow_and_skips_handler(tmp_path: Path) -> None:
    handled: list[int] = []
    hooks = HookRegistry()
    hooks.register("PreToolUse", lambda _context: HookResult(permission_behavior="allow"))
    policy = PermissionPolicy(
        rules=(PermissionRule("hard-deny", "deny", "系统策略拒绝", lambda _request: True),)
    )
    runner = AgentRunner(
        FakeModel(replies((tool_call("call-1", "work", '{"value":1}'),))),
        registry(lambda args, _context: handled.append(args["value"]) or tool_success("不安全")),
        "system",
        str(tmp_path),
        permission_policy=policy,
        hooks=hooks,
    )
    result = runner.run("开始")
    assert handled == []
    assert result.history[2].content == "工具执行错误 [permission_denied]: 系统策略拒绝"


def test_pre_rewrite_is_shared_by_approval_and_handler(tmp_path: Path) -> None:
    approval_values: list[dict[str, object]] = []
    handled: list[int] = []
    hooks = HookRegistry()
    original_holder: dict[str, object] = {"value": 2}
    hooks.register(
        "PreToolUse",
        lambda context: HookResult(
            permission_behavior="ask",
            updated_input=replace(
                context.prepared,
                call=tool_call(context.prepared.call.id, context.prepared.call.name, '{"value":2}'),
                arguments=original_holder,
            ),
        ),
    )

    class RecordingApproval:
        def decide(self, request: PermissionRequest) -> PermissionDecision:
            approval_values.append(dict(request.prepared.arguments or {}))
            original_holder["value"] = 99
            return PermissionDecision("allow", "批准值 2", "approval")

    policy = PermissionPolicy(approval=RecordingApproval())
    runner = AgentRunner(
        FakeModel(replies((tool_call("call-1", "work", '{"value":1}'),))),
        registry(lambda args, _context: handled.append(args["value"]) or tool_success("完成")),
        "system",
        str(tmp_path),
        permission_policy=policy,
        hooks=hooks,
    )
    runner.run("开始")
    assert approval_values == [{"value": 2}]
    assert handled == [2]
    assert original_holder == {"value": 99}


def test_stop_forces_at_most_one_extra_model_turn(tmp_path: Path) -> None:
    states: list[bool] = []
    hooks = HookRegistry()
    hooks.register(
        "Stop",
        lambda context: (
            states.append(context.stop_hook_active)
            or HookResult(force_continue=user_message("核对完成情况"))
        ),
    )
    model = FakeModel(
        [
            ModelReply(assistant_message("过早完成"), "stop"),
            ModelReply(assistant_message("核对完成"), "stop"),
        ]
    )
    result = AgentRunner(model, ToolRegistry(), "system", str(tmp_path), hooks=hooks).run("开始")
    assert result.final_text == "核对完成" and result.turns == 2
    assert states == [False, True]


def test_post_stop_pairs_later_calls_without_running_them(tmp_path: Path) -> None:
    handled: list[int] = []
    hooks = HookRegistry()
    hooks.register("PostToolUse", lambda _context: HookResult(prevent_continuation=True))
    calls = (tool_call("call-1", "work", '{"value":1}'), tool_call("call-2", "work", '{"value":2}'))
    model = FakeModel([ModelReply(assistant_message(None, calls), "tool_calls")])
    result = AgentRunner(
        model,
        registry(
            lambda args, _context: (
                handled.append(args["value"]) or tool_success(f"值={args['value']}")
            )
        ),
        "system",
        str(tmp_path),
        hooks=hooks,
    ).run("开始")
    assert handled == [1]
    assert (
        result.history[3].content
        == "工具执行错误 [hook_stopped_continuation]: PostToolUse 已要求停止，当前调用未执行"
    )
    validate_tool_pairing(result.history)


def test_hook_failures_and_blocking_return_paired_errors(tmp_path: Path) -> None:
    for event, expected in (
        ("PreToolUse", "PreToolUse Hook 执行失败"),
        ("PostToolUse", "PostToolUse Hook 执行失败"),
    ):
        hooks = HookRegistry()
        hooks.register(event, lambda _context: (_ for _ in ()).throw(RuntimeError("失败")))
        result = AgentRunner(
            FakeModel(replies((tool_call("call-1", "work", '{"value":1}'),))),
            registry(lambda _args, _context: tool_success("执行过")),
            "system",
            str(tmp_path),
            hooks=hooks,
        ).run("开始")
        assert result.history[2].content == f"工具执行错误 [hook_execution_error]: {expected}"
        validate_tool_pairing(result.history)

    blocking = HookRegistry()
    blocking.register(
        "PreToolUse",
        lambda _context: HookResult(blocking_error=tool_error("hook_blocked", "已阻止")),
    )
    blocked = AgentRunner(
        FakeModel(replies((tool_call("call-1", "work", '{"value":1}'),))),
        registry(lambda _args, _context: tool_success("不应执行")),
        "system",
        str(tmp_path),
        hooks=blocking,
    ).run("开始")
    assert blocked.history[2].content == "工具执行错误 [hook_blocked]: 已阻止"


def test_profiles_reject_early_hook_injection_and_accept_p04(tmp_path: Path) -> None:
    dependencies = {
        "model": FakeModel([]),
        "workspace": str(tmp_path),
        "approval_provider": Approval(),
        "audit_sink": Audit(),
        "hooks": HookRegistry(),
    }
    try:
        build_agent(P03, **dependencies)
        raise AssertionError("P03 不应接受 Hook")
    except ValueError as error:
        assert "Hook" in str(error)
    assert isinstance(build_agent(P04, **dependencies), AgentRunner)
