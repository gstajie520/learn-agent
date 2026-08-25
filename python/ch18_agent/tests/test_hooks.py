import asyncio
from dataclasses import replace

import pytest

from agent_ch18.core.hooks import (
    HOOK_EVENTS,
    HookContext,
    HookContractError,
    HookRegistry,
    HookResult,
)
from agent_ch18.core.messages import (
    assistant_message,
    system_message,
    tool_call,
    tool_message,
    user_message,
)
from agent_ch18.core.tools import ToolDefinition, ToolRegistry, tool_error, tool_success


def prepared_call(value: int = 1):
    """创建已通过 prepare 的测试调用；Hook 单测绝不执行 handler。"""
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "echo",
            "回显整数",
            {"type": "object"},
            "read",
            lambda _args, _ctx: tool_success("不应执行"),
            lambda args: set(args) == {"value"} and isinstance(args["value"], int),
        )
    )
    prepared = registry.prepare(tool_call("call-echo", "echo", f'{{"value":{value}}}'))
    assert prepared.error is None
    return prepared


def run(coro):
    """单测中的同步辅助函数，等价于 Java 测试里阻塞等待 CompletionStage。"""
    return asyncio.run(coro)


def test_defines_exactly_four_events_and_runs_callbacks_in_order() -> None:
    assert HOOK_EVENTS == ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
    calls: list[str] = []
    hooks = HookRegistry()
    hooks.register("UserPromptSubmit", lambda _context: calls.append("first") or HookResult())

    async def second(_context: HookContext) -> HookResult:
        calls.append("second")
        return HookResult()

    hooks.register("UserPromptSubmit", second)
    run(hooks.run_user_prompt(user_message("开始")))
    assert calls == ["first", "second"]


def test_pre_blocking_short_circuits_later_callbacks() -> None:
    calls: list[str] = []
    hooks = HookRegistry()
    hooks.register(
        "PreToolUse",
        lambda _context: (
            calls.append("block") or HookResult(blocking_error=tool_error("hook_blocked", "已阻止"))
        ),
    )
    hooks.register("PreToolUse", lambda _context: calls.append("late") or HookResult())
    result = run(hooks.run_pre_tool(prepared_call()))
    assert result.blocking_error == tool_error("hook_blocked", "已阻止")
    assert calls == ["block"]


def test_pre_rewrite_flows_to_later_callback_and_is_immutable() -> None:
    original = prepared_call(1)
    observed: list[object] = []
    hooks = HookRegistry()
    hooks.register(
        "PreToolUse",
        lambda _context: HookResult(
            updated_input=replace(
                original, call=tool_call("call-echo", "echo", '{"value":2}'), arguments={"value": 2}
            )
        ),
    )
    hooks.register(
        "PreToolUse",
        lambda context: (
            observed.append(context.prepared.arguments if context.prepared else None)
            or HookResult()
        ),
    )
    result = run(hooks.run_pre_tool(original))
    assert dict(result.updated_input.arguments or {}) == {"value": 2}
    assert dict(observed[0]) == {"value": 2}
    with pytest.raises(TypeError):
        result.updated_input.arguments["value"] = 99  # type: ignore[index,union-attr]


@pytest.mark.parametrize("change", ["id", "name", "definition", "schema"])
def test_pre_rewrite_cannot_change_trusted_identity_or_schema(change: str) -> None:
    original = prepared_call()
    if change == "id":
        updated = replace(
            original, call=tool_call("changed", "echo", '{"value":2}'), arguments={"value": 2}
        )
    elif change == "name":
        updated = replace(
            original, call=tool_call("call-echo", "other", '{"value":2}'), arguments={"value": 2}
        )
    elif change == "definition":
        updated = replace(prepared_call(2), call=original.call)
    else:
        updated = replace(original, arguments={"value": "two"})
    hooks = HookRegistry()
    hooks.register("PreToolUse", lambda _context: HookResult(updated_input=updated))
    with pytest.raises(HookContractError):
        run(hooks.run_pre_tool(original))


def test_post_rewrites_chain_and_permission_uses_strictest_value() -> None:
    observed: list[str] = []
    hooks = HookRegistry()
    hooks.register(
        "PostToolUse",
        lambda context: (
            observed.append(context.result.content)
            or HookResult(updated_output=tool_success("第一次"))
        ),
    )
    hooks.register(
        "PostToolUse",
        lambda context: (
            observed.append(context.result.content)
            or HookResult(updated_output=tool_success("第二次"))
        ),
    )
    result = run(hooks.run_post_tool(prepared_call(), tool_success("原始")))
    assert observed == ["原始", "第一次"]
    assert result.updated_output == tool_success("第二次")

    permission_hooks = HookRegistry()
    for behavior in ("allow", "ask", "deny"):
        permission_hooks.register(
            "PreToolUse", lambda _context, value=behavior: HookResult(permission_behavior=value)
        )  # type: ignore[arg-type]
    assert run(permission_hooks.run_pre_tool(prepared_call())).permission_behavior == "deny"


def test_stop_can_force_only_one_continuation_but_callback_runs_twice() -> None:
    states: list[bool] = []
    hooks = HookRegistry()
    hooks.register(
        "Stop",
        lambda context: (
            states.append(context.stop_hook_active)
            or HookResult(force_continue=user_message("再核对一次"))
        ),
    )
    history = (user_message("工作"), assistant_message("完成"))
    assert run(hooks.run_stop(history, False)).force_continue == user_message("再核对一次")
    assert run(hooks.run_stop(history, True)) == HookResult()
    assert states == [False, True]


def test_runtime_contract_rejects_cross_event_fields_and_orphan_messages() -> None:
    with pytest.raises(HookContractError):
        HookResult(blocking_error=tool_success("不是错误"))
    with pytest.raises(HookContractError):
        HookResult(additional_context=(tool_message("孤儿", "call-1"),))
    with pytest.raises(HookContractError):
        HookContext("PreToolUse", prepared=prepared_call(), message=user_message("错误字段"))
    hooks = HookRegistry()
    hooks.register("Stop", lambda _context: HookResult(prevent_continuation=True))
    with pytest.raises(HookContractError):
        run(hooks.run_stop((assistant_message("完成"),), False))


def test_user_prompt_accepts_only_system_additional_context() -> None:
    hooks = HookRegistry()
    hooks.register(
        "UserPromptSubmit",
        lambda _context: HookResult(additional_context=(system_message("项目规则"),)),
    )
    assert run(hooks.run_user_prompt(user_message("开始"))).additional_context == (
        system_message("项目规则"),
    )
