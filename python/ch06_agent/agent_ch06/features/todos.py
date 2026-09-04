"""第六章子 Agent 会话级 TODO 计划快照。

这是什么：实现 ToolRoundObserver 接口的 TODO 跟踪器，提供 todo_write 工具并监控计划更新频率
Java 类比：@Service class TodoTracker implements ToolRoundObserver
为什么需要：让模型能显式提交任务计划，并在长时间未更新时自动提醒

Java 对照：`TodoTracker` 同时扮演一个有状态的领域服务和工具轮观察器。
它不是数据库 Repository，状态只属于当前 AgentRunner，会话结束后自然消失。
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..core.messages import ChatMessage, system_message
from ..core.tools import ToolContext, ToolDefinition, ToolResult, tool_success

MAX_TODOS = 50  # 单次最多提交 50 个任务项，防止模型滥用
STALE_TOOL_ROUNDS = 3  # 连续 3 轮工具使用未更新计划时触发提醒
TODO_STALE_REMINDER = (
    "请保持 TODO 列表为最新状态。计划发生变化时，请调用 todo_write 提交完整任务快照。"
)
TodoStatus = Literal["pending", "in_progress", "completed"]  # 三种状态字面量
TODO_STATUSES: tuple[TodoStatus, ...] = ("pending", "in_progress", "completed")  # 合法状态枚举


@dataclass(frozen=True, slots=True)
class TodoItem:
    """一条不可变 TODO，类似 Java record。

    这是什么：单个任务项的值对象
    Java 类比：record TodoItem(String content, TodoStatus status)
    为什么需要：用不可变对象保证任务内容不会被意外修改
    """

    content: str  # 去掉首尾空白后的任务说明
    status: TodoStatus  # pending、in_progress、completed 三选一


def _validate_todo_input(value: Mapping[str, Any]) -> bool:
    """严格校验完整快照，未知字段或任意坏项都整体拒绝。

    这是什么：JSON Schema 之外的二次校验
    Java 类比：类似 @Valid + 自定义 Validator
    为什么需要：确保模型提交的 JSON 完全符合预期格式，避免部分字段错误导致系统状态不一致
    """
    if set(value) != {"todos"}:  # 只允许 todos 字段，多余或缺失都拒绝
        return False
    raw_todos = value.get("todos")
    if not isinstance(raw_todos, list) or len(raw_todos) > MAX_TODOS:  # 必须是列表且不超过 50 项
        return False
    for item in raw_todos:
        if not isinstance(item, dict) or set(item) != {"content", "status"}:  # 每项必须只有 content 和 status
            return False
        content = item.get("content")
        status = item.get("status")
        if not isinstance(content, str) or not content.strip() or status not in TODO_STATUSES:  # content 不能为空，status 必须合法
            return False
    return True


def _serialize_snapshot(todos: Sequence[TodoItem]) -> str:
    """返回紧凑、字段顺序稳定的 ASCII JSON，中文会变成 Unicode 转义。

    这是什么：将内存对象序列化为稳定格式的 JSON 字符串
    Java 类比：类似 ObjectMapper.writeValueAsString() + 配置 ASCII 输出
    为什么需要：保证相同内容生成相同字符串，便于测试和日志对比
    """
    return json.dumps(
        {"todos": [{"content": item.content, "status": item.status} for item in todos]},
        ensure_ascii=True,  # 中文转义为 \uXXXX，避免编码问题
        separators=(",", ":"),  # 紧凑格式，无多余空格
    )


class TodoTracker:
    """保存当前完整计划，并统计连续未更新计划的工具轮。

    这是什么：实现 ToolRoundObserver 协议的会话级状态管理器
    Java 类比：@Service class TodoTracker implements ToolRoundObserver { private List<TodoItem> todos; }
    为什么需要：在模型长时间使用工具但不更新计划时自动提醒，避免计划与实际进度脱节
    """

    def __init__(self) -> None:
        self._todos: tuple[TodoItem, ...] = ()  # 不可变快照，外部只能整体替换
        self._non_todo_tool_rounds = 0  # 连续未调用 todo_write 的工具轮数
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
            # 这里的 write 表示"修改会话状态"，不是写磁盘。第三章审批规则只匹配
            # write_file/edit_file，因此 todo_write 不会错误地弹出文件审批。
            "write",
            self._write_todos,  # 工具执行器函数
            _validate_todo_input,  # 自定义校验器
        )

    @property
    def todos(self) -> tuple[TodoItem, ...]:
        """返回当前不可变快照，外部只能读取。

        这是什么：只读属性，防止外部直接修改内部状态
        Java 类比：public List<TodoItem> getTodos() { return List.copyOf(todos); }
        为什么需要：保持封装性，外部必须通过 todo_write 工具才能修改计划
        """
        return self._todos

    def _write_todos(self, arguments: Mapping[str, Any], _context: ToolContext) -> ToolResult:
        """一次性替换全部计划；进入此方法前参数已经完整校验。

        这是什么：todo_write 工具的执行逻辑
        Java 类比：public ToolResult writeTodos(Map<String, Object> arguments)
        为什么需要：提供原子性替换整个计划的能力，避免增量修改导致状态不一致
        """
        raw_todos = arguments["todos"]
        if not isinstance(raw_todos, tuple):  # ToolRegistry.prepare 会把 list 冻结成 tuple
            raise TypeError("todo_write 参数在 prepare 后必须冻结为 tuple")
        # 转换为不可变的 TodoItem 对象
        self._todos = tuple(
            TodoItem(str(item["content"]).strip(), item["status"]) for item in raw_todos
        )
        self._non_todo_tool_rounds = 0  # 重置计数器，表示计划已更新
        return tool_success(_serialize_snapshot(self._todos))

    def record_tool_round(self, tool_names: Sequence[str]) -> None:
        """按整轮而不是按调用数统计；一轮出现 todo_write 就重置。

        这是什么：ToolRoundObserver 接口方法，记录工具使用情况
        Java 类比：@Override public void recordToolRound(List<String> toolNames)
        为什么需要：跟踪模型是否及时更新计划，连续 3 轮未更新时触发提醒
        """
        if not tool_names:  # 空轮不计数（模型返回纯文本）
            return
        if self.tool_definition.name in tool_names:  # 本轮调用了 todo_write
            self._non_todo_tool_rounds = 0  # 重置计数器
            return
        self._non_todo_tool_rounds += 1  # 未更新计划，累加计数

    def before_model(self) -> tuple[ChatMessage, ...]:
        """达到三轮后只为下一次请求返回一条临时系统提醒。

        这是什么：ToolRoundObserver 接口方法，在调用模型前注入临时指导
        Java 类比：@Override public List<ChatMessage> beforeModel()
        为什么需要：在计划过期时自动提醒模型更新，而不是让人工介入
        """
        if self._non_todo_tool_rounds < STALE_TOOL_ROUNDS:  # 未达到提醒阈值
            return ()
        self._non_todo_tool_rounds = 0  # 重置计数，下次重新累计（避免重复提醒）
        return (system_message(TODO_STALE_REMINDER),)  # 返回临时提醒消息，不进入历史
