"""TODO 模块的单元测试：验证任务管理和状态追踪逻辑。

这是什么：测试 TODO 工具的创建、更新和容量限制
Java 类比：类似 TodoManagerTest 单元测试类
为什么需要：确保 Agent 能记录和追踪长期任务，且不会超出内存限制
"""

import json

import pytest

from agent_ch08.core.messages import tool_call
from agent_ch08.core.tools import ToolContext, ToolRegistry
from agent_ch08.features.todos import (
    MAX_TODOS,
    TODO_STALE_REMINDER,
    TODO_STATUSES,
    TodoItem,
    TodoTracker,
)

CONTEXT = ToolContext(".", "tester")


def invoke_todo(tracker: TodoTracker, arguments_json: str):
    """通过真实 ToolRegistry 调用，保证 JSON 和参数校验路径也被覆盖。"""
    tools = ToolRegistry()
    tools.register(tracker.tool_definition)
    return tools.invoke(
        tools.prepare(tool_call("todo-call", "todo_write", arguments_json)), CONTEXT
    )


def test_three_statuses_trim_content_and_return_ascii_snapshot() -> None:
    tracker = TodoTracker()
    result = invoke_todo(tracker, '{"todos":[{"content":"  编写测试  ","status":"pending"}]}')
    assert TODO_STATUSES == ("pending", "in_progress", "completed")
    assert (
        result.content
        == '{"todos":[{"content":"\\u7f16\\u5199\\u6d4b\\u8bd5","status":"pending"}]}'
    )
    assert tracker.todos == (TodoItem("编写测试", "pending"),)
    assert result.content.isascii()


def test_returns_complete_stable_snapshot_and_schema() -> None:
    tracker = TodoTracker()
    tools = ToolRegistry()
    tools.register(tracker.tool_definition)
    arguments = {
        "todos": [
            {"content": "第一步", "status": "in_progress"},
            {"content": "ship", "status": "completed"},
        ]
    }
    result = tools.invoke(
        tools.prepare(tool_call("todo", "todo_write", json.dumps(arguments, ensure_ascii=False))),
        CONTEXT,
    )
    assert json.loads(result.content) == {
        "todos": [
            {"content": "第一步", "status": "in_progress"},
            {"content": "ship", "status": "completed"},
        ]
    }
    schema = tools.openai_tools()[0].parameters
    assert schema["properties"]["todos"]["maxItems"] == MAX_TODOS
    assert schema["additionalProperties"] is False


def test_accepts_exactly_fifty_todos() -> None:
    todos = [{"content": f"task-{index}", "status": "pending"} for index in range(MAX_TODOS)]
    tracker = TodoTracker()
    result = invoke_todo(tracker, json.dumps({"todos": todos}))
    assert not result.is_error
    assert len(tracker.todos) == MAX_TODOS


@pytest.mark.parametrize(
    ("arguments_json", "error_code"),
    [
        ('{"todos":"not-array"}', "invalid_arguments"),
        ('{"todos":[{"content":" ","status":"pending"}]}', "invalid_arguments"),
        ('{"todos":[{"content":"kept","status":"unknown"}]}', "invalid_arguments"),
        ('{"todos":[{"content":"kept","status":"pending","extra":true}]}', "invalid_arguments"),
        ('{"todos":[],"extra":true}', "invalid_arguments"),
        (
            json.dumps(
                {
                    "todos": [
                        {"content": f"task-{index}", "status": "pending"}
                        for index in range(MAX_TODOS + 1)
                    ]
                }
            ),
            "invalid_arguments",
        ),
        ("{", "invalid_json"),
    ],
)
def test_invalid_update_preserves_old_snapshot(arguments_json: str, error_code: str) -> None:
    tracker = TodoTracker()
    invoke_todo(tracker, '{"todos":[{"content":"kept","status":"in_progress"}]}')
    before = tracker.todos
    result = invoke_todo(tracker, arguments_json)
    assert result.is_error and result.error_code == error_code
    assert tracker.todos is before


def test_trackers_isolate_session_state() -> None:
    first, second = TodoTracker(), TodoTracker()
    invoke_todo(first, '{"todos":[{"content":"first","status":"pending"}]}')
    assert first.todos == (TodoItem("first", "pending"),)
    assert second.todos == ()


def test_three_non_todo_rounds_emit_one_request_only_reminder() -> None:
    tracker = TodoTracker()
    tracker.record_tool_round(("read_file", "glob"))
    assert tracker.before_model() == ()
    tracker.record_tool_round(("read_file",))
    assert tracker.before_model() == ()
    tracker.record_tool_round(("shell",))
    reminder = tracker.before_model()
    assert reminder[0].content == TODO_STALE_REMINDER
    assert tracker.before_model() == ()


def test_todo_write_resets_stale_counter() -> None:
    tracker = TodoTracker()
    tracker.record_tool_round(("read_file",))
    tracker.record_tool_round(("glob",))
    invoke_todo(tracker, '{"todos":[]}')
    tracker.record_tool_round(("todo_write",))
    tracker.record_tool_round(("read_file",))
    tracker.record_tool_round(("glob",))
    assert tracker.before_model() == ()
