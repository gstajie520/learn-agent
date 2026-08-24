from pathlib import Path

from agent_ch11.core.hooks import HookRegistry, HookResult
from agent_ch11.core.loop import AgentRunner
from agent_ch11.core.messages import (
    assistant_message,
    system_message,
    tool_call,
    validate_tool_pairing,
)
from agent_ch11.core.model import ModelReply
from agent_ch11.core.permissions import PermissionPolicy, PermissionRule
from agent_ch11.core.tools import ToolContext, ToolDefinition, ToolRegistry, tool_success
from agent_ch11.features.subagents import (
    DEFAULT_SUBAGENT_MAX_TURNS,
    DEFAULT_SUBAGENT_SYSTEM_PROMPT,
    SubagentTool,
)


class FakeModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self.replies = replies
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


def registry_with(definition: ToolDefinition) -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(definition)
    return tools


def invoke_task(feature: SubagentTool, description: str):
    tools = registry_with(feature.tool_definition)
    prepared = tools.prepare(tool_call("parent-task", "task", f'{{"description":"{description}"}}'))
    return tools.invoke(prepared, ToolContext(".", "parent-user"))


def test_strict_contract_and_max_turn_cap() -> None:
    feature = SubagentTool(lambda: FakeModel([]), ToolRegistry, HookRegistry(), PermissionPolicy())
    tools = registry_with(feature.tool_definition)
    assert DEFAULT_SUBAGENT_MAX_TURNS == 30
    assert feature.tool_definition.name == "task" and feature.tool_definition.effect == "external"
    for arguments in (
        '{"description":""}',
        '{"description":"   "}',
        '{"description":"go","extra":1}',
    ):
        prepared = tools.prepare(tool_call("task-1", "task", arguments))
        assert prepared.error is not None and prepared.error.error_code == "invalid_arguments"
    try:
        SubagentTool(
            lambda: FakeModel([]), ToolRegistry, HookRegistry(), PermissionPolicy(), max_turns=31
        )
        raise AssertionError("max_turns=31 应被拒绝")
    except ValueError as error:
        assert "30" in str(error)


def test_parent_only_sees_final_result_and_child_shares_boundaries(tmp_path: Path) -> None:
    trace: list[str] = []
    observed_contexts: list[ToolContext] = []
    inspect = ToolDefinition(
        "inspect",
        "读取确定性证据",
        {"type": "object"},
        "read",
        lambda args, context: (
            observed_contexts.append(context)
            or trace.append("handler:inspect")
            or tool_success(f"证据:{args['value']}")
        ),
        lambda args: set(args) == {"value"} and isinstance(args["value"], str),
    )
    child_model = FakeModel(
        [
            ModelReply(
                assistant_message(
                    None, (tool_call("child-inspect", "inspect", '{"value":"found"}'),)
                ),
                "tool_calls",
            ),
            ModelReply(assistant_message("子 Agent 结论"), "stop"),
        ]
    )
    hooks = HookRegistry()
    hooks.register(
        "PreToolUse",
        lambda context: trace.append(f"pre:{context.prepared.call.name}") or HookResult(),
    )
    hooks.register(
        "PostToolUse",
        lambda context: trace.append(f"post:{context.prepared.call.name}") or HookResult(),
    )
    policy = PermissionPolicy(
        rules=(
            PermissionRule(
                "record",
                "allow",
                "测试允许",
                lambda request: trace.append(f"permission:{request.prepared.call.name}") or True,
            ),
        )
    )
    feature = SubagentTool(lambda: child_model, lambda: registry_with(inspect), hooks, policy)
    parent_call = tool_call("parent-task", "task", '{"description":"inspect project"}')
    parent_model = FakeModel(
        [
            ModelReply(assistant_message(None, (parent_call,)), "tool_calls"),
            ModelReply(assistant_message("父 Agent 最终回答"), "stop"),
        ]
    )
    result = AgentRunner(
        parent_model,
        registry_with(feature.tool_definition),
        "parent system",
        str(tmp_path),
        identity="parent-user",
        hooks=hooks,
        permission_policy=policy,
    ).run("父任务")
    assert result.history[2].content == "子 Agent 结论"
    assert len(result.history) == 4
    assert child_model.requests[0].messages == (
        system_message(DEFAULT_SUBAGENT_SYSTEM_PROMPT),
        type(result.history[0])("user", "inspect project"),
    )
    assert [tool.name for tool in child_model.requests[0].tools] == ["inspect"]
    assert observed_contexts == [ToolContext(str(tmp_path.resolve()), "parent-user")]
    assert trace == [
        "pre:task",
        "permission:task",
        "pre:inspect",
        "permission:inspect",
        "handler:inspect",
        "post:inspect",
        "post:task",
    ]
    validate_tool_pairing(result.history)


def test_each_task_uses_fresh_model_registry_and_history() -> None:
    models: list[FakeModel] = []
    registries: list[ToolRegistry] = []

    def model_factory() -> FakeModel:
        model = FakeModel([ModelReply(assistant_message(f"结论 {len(models) + 1}"), "stop")])
        models.append(model)
        return model

    def tools_factory() -> ToolRegistry:
        tools = ToolRegistry()
        registries.append(tools)
        return tools

    feature = SubagentTool(model_factory, tools_factory, HookRegistry(), PermissionPolicy())
    assert invoke_task(feature, " first task ").content == "结论 1"
    assert invoke_task(feature, "second task").content == "结论 2"
    assert len(models) == 2 and len(registries) == 2 and registries[0] is not registries[1]
    assert models[0].requests[0].messages[1].content == "first task"


def test_child_factory_can_supply_its_own_round_observer() -> None:
    """子工具表和观察器必须一起传给子 Runner，不能丢掉第五章的 TODO 接缝。"""

    class Observer:
        def __init__(self) -> None:
            self.before_calls = 0
            self.rounds: list[tuple[str, ...]] = []

        def before_model(self):
            self.before_calls += 1
            return ()

        def record_tool_round(self, tool_names):
            self.rounds.append(tuple(tool_names))

    inspect = ToolDefinition(
        "inspect",
        "读取测试证据",
        {"type": "object"},
        "read",
        lambda _args, _context: tool_success("evidence"),
        lambda args: set(args) == set(),
    )
    observer = Observer()
    child = FakeModel(
        [
            ModelReply(
                assistant_message(None, (tool_call("inspect-1", "inspect", "{}"),)),
                "tool_calls",
            ),
            ModelReply(assistant_message("完成"), "stop"),
        ]
    )
    feature = SubagentTool(
        lambda: child,
        lambda: (registry_with(inspect), observer),
        HookRegistry(),
        PermissionPolicy(),
    )

    result = invoke_task(feature, "检查项目")

    assert result.content == "完成"
    assert observer.before_calls == 2
    assert observer.rounds == [("inspect",)]


def test_recursive_task_is_unknown_and_bad_factory_fails_before_model() -> None:
    child = FakeModel(
        [
            ModelReply(
                assistant_message(
                    None, (tool_call("recursive", "task", '{"description":"again"}'),)
                ),
                "tool_calls",
            ),
            ModelReply(assistant_message("无法继续委派"), "stop"),
        ]
    )
    feature = SubagentTool(lambda: child, ToolRegistry, HookRegistry(), PermissionPolicy())
    result = invoke_task(feature, "do work")
    assert result.content == "无法继续委派"
    assert child.requests[1].messages[-1].content == "工具执行错误 [unknown_tool]: 找不到工具: task"

    bad_tools = ToolRegistry()
    bad_tools.register(feature.tool_definition)
    never_called = FakeModel([])
    bad_feature = SubagentTool(
        lambda: never_called, lambda: bad_tools, HookRegistry(), PermissionPolicy()
    )
    error = invoke_task(bad_feature, "bad config")
    assert error.error_code == "subagent_configuration_error"
    assert never_called.requests == []


def test_turn_limit_and_unexpected_failure_are_structured() -> None:
    inspect = ToolDefinition(
        "inspect",
        "继续执行",
        {"type": "object"},
        "read",
        lambda args, _ctx: tool_success(str(args["value"])),
        lambda args: set(args) == {"value"},
    )

    class EndlessModel:
        def __init__(self) -> None:
            self.count = 0

        def complete(self, _request):
            self.count += 1
            return ModelReply(
                assistant_message(
                    None, (tool_call(f"call-{self.count}", "inspect", '{"value":"x"}'),)
                ),
                "tool_calls",
            )

    limited = SubagentTool(
        EndlessModel,
        lambda: registry_with(inspect),
        HookRegistry(),
        PermissionPolicy(),
        max_turns=2,
    )
    assert invoke_task(limited, "never finish").error_code == "subagent_turn_limit"

    broken = SubagentTool(
        lambda: (_ for _ in ()).throw(RuntimeError("secret")),
        ToolRegistry,
        HookRegistry(),
        PermissionPolicy(),
    )
    result = invoke_task(broken, "break")
    assert result.error_code == "subagent_execution_error" and "secret" not in result.content
