"""第六章子 Agent 会话级 TODO 计划快照。

这是什么：管理 Agent 会话内 TODO 列表的模块
Java 类比：类似有状态的 TodoService，实现 ToolRoundObserver 接口
为什么需要：让 Agent 维护任务清单，并在长期未更新时提醒模型同步计划

Java 对照：`TodoTracker` 同时扮演一个有状态的领域服务和工具轮观察器。
它不是数据库 Repository，状态只属于当前 AgentRunner，会话结束后自然消失。
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..core.messages import ChatMessage, system_message
from ..core.tools import ToolContext, ToolDefinition, ToolResult, tool_success

MAX_TODOS = 50
STALE_TOOL_ROUNDS = 3
TODO_STALE_REMINDER = (
    "请保持 TODO 列表为最新状态。计划发生变化时，请调用 todo_write 提交完整任务快照。"
)
TodoStatus = Literal["pending", "in_progress", "completed"]
TODO_STATUSES: tuple[TodoStatus, ...] = ("pending", "in_progress", "completed")


@dataclass(frozen=True, slots=True)
class TodoItem:
    """一条不可变 TODO，类似 Java record。

    这是什么：表示单个 TODO 条目的数据类
    Java 类比：类似 record TodoItem(String content, TodoStatus status)
    为什么需要：以不可变方式存储任务内容和状态，防止意外修改
    """

    content: str  # 去掉首尾空白后的任务说明。
    status: TodoStatus  # pending、in_progress、completed 三选一。


def _validate_todo_input(value: Mapping[str, Any]) -> bool:
    """严格校验完整快照，未知字段或任意坏项都整体拒绝。

    这是什么：校验 todo_write 工具参数格式的函数
    Java 类比：类似 boolean validateTodoInput(Map<String, Object> args)
    为什么需要：确保 TODO 快照格式正确，防止无效数据进入系统
    """
    if set(value) != {"todos"}:
        return False
    raw_todos = value.get("todos")
    if not isinstance(raw_todos, list) or len(raw_todos) > MAX_TODOS:
        return False
    for item in raw_todos:
        if not isinstance(item, dict) or set(item) != {"content", "status"}:
            return False
        content = item.get("content")
        status = item.get("status")
        if not isinstance(content, str) or not content.strip() or status not in TODO_STATUSES:
            return False
    return True


def _serialize_snapshot(todos: Sequence[TodoItem]) -> str:
    """返回紧凑、字段顺序稳定的 ASCII JSON，中文会变成 Unicode 转义。

    这是什么：将 TODO 列表序列化为 JSON 字符串的函数
    Java 类比：类似 String serializeToJson(List<TodoItem> todos)
    为什么需要：生成稳定格式的 JSON 响应，便于模型解析和测试断言
    """
    return json.dumps(
        {"todos": [{"content": item.content, "status": item.status} for item in todos]},
        ensure_ascii=True,
        separators=(",", ":"),
    )


class TodoTracker:
    """保存当前完整计划，并统计连续未更新计划的工具轮。

    这是什么：管理 TODO 列表状态并监控更新频率的类
    Java 类比：类似 @Service class TodoTracker implements ToolRoundObserver
    为什么需要：提供 TODO 工具实现，同时监控未更新轮数并在必要时提醒模型
    """

    def __init__(self) -> None:
        self._todos: tuple[TodoItem, ...] = ()
        self._non_todo_tool_rounds = 0
        self.tool_definition = ToolDefinition(
            "todo_write",
            "用完整任务快照替换当前 TODO 列表；计划变化时需要重新提交全部条目。",
            {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "maxItems": MAX_TODOS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "minLength": 1},
                                "status": {"type": "string", "enum": list(TODO_STATUSES)},
                            },
                            "required": ["content", "status"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["todos"],
                "additionalProperties": False,
            },
            # 这里的 write 表示“修改会话状态”，不是写磁盘。第三章审批规则只匹配
            # write_file/edit_file，因此 todo_write 不会错误地弹出文件审批。
            "write",
            self._write_todos,
            _validate_todo_input,
        )

    @property
    def todos(self) -> tuple[TodoItem, ...]:
        """返回当前不可变快照，外部只能读取。"""
        return self._todos

    def _write_todos(self, arguments: Mapping[str, Any], _context: ToolContext) -> ToolResult:
        """一次性替换全部计划；进入此方法前参数已经完整校验。"""
        raw_todos = arguments["todos"]
        if not isinstance(raw_todos, tuple):
            raise TypeError("todo_write 参数在 prepare 后必须冻结为 tuple")
        self._todos = tuple(
            TodoItem(str(item["content"]).strip(), item["status"]) for item in raw_todos
        )
        self._non_todo_tool_rounds = 0
        return tool_success(_serialize_snapshot(self._todos))

    def record_tool_round(self, tool_names: Sequence[str]) -> None:
        """按整轮而不是按调用数统计；一轮出现 todo_write 就重置。"""
        if not tool_names:
            return
        if self.tool_definition.name in tool_names:
            self._non_todo_tool_rounds = 0
            return
        self._non_todo_tool_rounds += 1

    def before_model(self) -> tuple[ChatMessage, ...]:
        """达到三轮后只为下一次请求返回一条临时系统提醒。"""
        if self._non_todo_tool_rounds < STALE_TOOL_ROUNDS:
            return ()
        self._non_todo_tool_rounds = 0
        return (system_message(TODO_STALE_REMINDER),)
