"""第六章一次性子 Agent 工具。

这是什么：实现 task 工具，将自包含任务委派给独立的子 AgentRunner
Java 类比：@Service class SubagentTool，内部创建新的 AgentService 实例执行子任务
为什么需要：让父 Agent 能把独立子任务委派出去，子任务有自己的历史和工具状态

Java 对照：`SubagentTool` 是一个外部调用适配器，类似应用服务里委派另一个
`AgentService` 的 facade。它不复制循环，而是创建新的 `AgentRunner`；父子共享
Hook、权限、workspace 和 identity，但消息历史、模型请求队列和工具注册表隔离。
"""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from ..core.hooks import HookRegistry
from ..core.loop import AgentLimitError, AgentRunner, ToolRoundObserver
from ..core.model import ModelClient
from ..core.permissions import PermissionPolicy
from ..core.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)

TASK_TOOL_NAME = "task"  # 工具名称，父 Agent 调用此工具来委派子任务
# 子 Agent 最多允许请求模型 30 次。测试可以调低，但正式配置不能调高。
DEFAULT_SUBAGENT_MAX_TURNS = 30
# 这是子 Agent 自己的 system prompt，不会继承父 Agent 的 system prompt。
DEFAULT_SUBAGENT_SYSTEM_PROMPT = (
    "你是一个专注的编码子 Agent，正在当前工作区执行委派任务。"
    "只完成委派的单一任务，最后返回简洁且有证据的结论。不要继续委派子任务。"
)


class ModelClientFactory(Protocol):
    """每次 task 调用创建一个独立模型边界。

    这是什么：模型客户端工厂接口
    Java 类比：Supplier<ModelClient>
    为什么需要：每个子 Agent 需要独立的模型状态，避免会话混淆

    Java 对照：类似 `Supplier<ModelClient>`。使用工厂而不是固定对象，测试时可以
    为每个子任务准备独立回复队列，真实运行时也不会复用上一次子任务的会话状态。
    """

    def __call__(self) -> ModelClient: ...


class ToolRegistryFactory(Protocol):
    """每次 task 调用创建独立工具表，也可以附带会话观察器。

    这是什么：工具注册表工厂接口
    Java 类比：Supplier<Tuple<ToolRegistry, Optional<ToolRoundObserver>>>
    为什么需要：每个子 Agent 需要独立的工具状态和 TODO 跟踪器

    返回 tuple 时，第一个元素是工具注册表，第二个元素是和该注册表配套的
    `TodoTracker` 等观察器。它们必须一起新建，不能让父子 Agent 共用 TODO 状态。
    """

    def __call__(self) -> ToolRegistry | tuple[ToolRegistry, ToolRoundObserver | None]: ...


def _validate_task_input(value: Mapping[str, object]) -> bool:
    """task 只接受一个非空 description 字段，拒绝未知字段。

    这是什么：task 工具的参数校验器
    Java 类比：类似 @Valid + 自定义 Validator
    为什么需要：确保父 Agent 传递的子任务描述符合预期格式
    """
    description = value.get("description")
    return (
        set(value) == {"description"} and isinstance(description, str) and bool(description.strip())
    )


class SubagentTool:
    """把一个自包含描述委派给隔离的 AgentRunner，并只返回最终文本。

    这是什么：实现 task 工具的核心类，负责创建和运行子 Agent
    Java 类比：@Service class SubagentService，内部创建新的 AgentRunner
    为什么需要：让父 Agent 能委派独立子任务，保持父子历史和状态隔离

    字段说明：
    - `_model_factory`：每次委派创建子模型客户端；
    - `_tools_factory`：每次委派创建子工具注册表和可选观察器；
    - `_hooks`：父子共用的 HookRegistry；
    - `_permission_policy`：父子共用的权限策略；
    - `_system_prompt`：只属于子 Agent 的固定职责提示；
    - `_max_turns`：子 Agent 最多调用模型的轮数；
    - `tool_definition`：注册到父 Agent 的 `task` 工具定义。
    """

    def __init__(
        self,
        model_factory: ModelClientFactory,
        tools_factory: ToolRegistryFactory,
        hooks: HookRegistry,
        permission_policy: PermissionPolicy,
        system_prompt: str = DEFAULT_SUBAGENT_SYSTEM_PROMPT,
        max_turns: int = DEFAULT_SUBAGENT_MAX_TURNS,
    ) -> None:
        if not callable(model_factory) or not callable(tools_factory):
            raise TypeError("model_factory 和 tools_factory 必须可调用")
        if not isinstance(hooks, HookRegistry):
            raise TypeError("hooks 必须是 HookRegistry")
        if not isinstance(permission_policy, PermissionPolicy):
            raise TypeError("permission_policy 必须是 PermissionPolicy")
        if not system_prompt.strip():
            raise ValueError("system_prompt 不能为空")
        if max_turns <= 0:
            raise ValueError("max_turns 必须是正整数")
        if max_turns > DEFAULT_SUBAGENT_MAX_TURNS:
            raise ValueError("max_turns 不能超过 30")
        self._model_factory = model_factory  # Java: Supplier<ModelClient>。
        self._tools_factory = tools_factory  # Java: Supplier<ChildRuntime>。
        self._hooks = hooks  # 共享生命周期扩展，子工具仍会触发父会话配置的 Hook。
        self._permission_policy = permission_policy  # 共享硬边界，委派不能绕过审批。
        self._system_prompt = system_prompt  # 子历史中的第一条 system message。
        self._max_turns = max_turns  # 达到后返回 subagent_turn_limit。
        self.tool_definition = ToolDefinition(
            TASK_TOOL_NAME,
            "启动隔离的子 Agent，只返回它的最终结论。",
            {
                "type": "object",
                "properties": {"description": {"type": "string", "minLength": 1}},
                "required": ["description"],
                "additionalProperties": False,
            },
            "external",
            self._run_task,
            _validate_task_input,
        )

    def _run_task(self, arguments: Mapping[str, object], context: ToolContext) -> ToolResult:
        """执行一次同步委派；独立线程用于避免嵌套 asyncio.run。"""
        raw_description = arguments.get("description")
        if not isinstance(raw_description, str):
            return tool_error("subagent_configuration_error", "委派描述不是字符串")
        description = raw_description.strip()

        def execute() -> ToolResult:
            """在线程中完成一次子 Agent 生命周期，并把异常转换成稳定工具结果。"""
            try:
                created = self._tools_factory()
                observer: ToolRoundObserver | None = None
                if isinstance(created, tuple):
                    if len(created) != 2:
                        return tool_error("subagent_configuration_error", "工具工厂返回值格式错误")
                    tools, observer = created
                else:
                    tools = created
                if not isinstance(tools, ToolRegistry):
                    return tool_error(
                        "subagent_configuration_error", "工具工厂必须返回 ToolRegistry"
                    )
                if TASK_TOOL_NAME in tools.names:
                    return tool_error(
                        "subagent_configuration_error", "子 Agent 工具集不能包含 task"
                    )
                model = self._model_factory()
                if not hasattr(model, "complete") or not callable(model.complete):
                    return tool_error(
                        "subagent_configuration_error", "模型工厂必须返回 ModelClient"
                    )
                runner = AgentRunner(
                    model,
                    tools,
                    self._system_prompt,
                    context.workspace,
                    max_turns=self._max_turns,
                    identity=context.identity,
                    hooks=self._hooks,
                    permission_policy=self._permission_policy,
                    tool_round_observer=observer,
                )
                result = runner.run(description)
                return tool_success(result.final_text)
            except AgentLimitError:
                return tool_error(
                    "subagent_turn_limit",
                    f"子 Agent 达到 max_turns={self._max_turns}，仍未返回最终答案",
                )
            except Exception:  # noqa: BLE001
                return tool_error("subagent_execution_error", "子 Agent 执行失败")

        # 父 Agent 的工具 handler 运行在 asyncio 事件循环中，而 AgentRunner.run() 是
        # 同步入口，内部会调用 asyncio.run()。放到独立线程后，就不会在同一线程里
        # 嵌套事件循环。这里仍然会同步等待结果，不是并行任务或后台任务。
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-subagent") as executor:
            return executor.submit(execute).result()
