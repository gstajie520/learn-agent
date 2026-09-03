"""第四章 Hook 生命周期。

Java 对照：`HookRegistry` 类似一个按事件分组的观察者注册表，
`HookContext` 和 `HookResult` 类似经过校验的不可变 DTO。回调只能声明影响，
不能直接修改 Agent 循环，所以扩展逻辑不会重新变成一堆 if/else。
"""

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .messages import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
    system_message,
    user_message,
)
from .permissions import PERMISSION_BEHAVIORS, PermissionBehavior
from .tools import PreparedToolCall, ToolResult, copy_prepared_tool_call, copy_tool_result

HookEvent = Literal["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]
HOOK_EVENTS: tuple[HookEvent, ...] = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")


class HookContractError(Exception):
    """Hook 输入、输出或事件字段违反契约时抛出的领域异常。

    这是什么：Hook 契约违反的专用异常
    Java 类比：类似 HookViolationException 或 ContractException
    为什么需要：Hook 回调必须遵守严格契约（事件对应字段、返回值结构），违反时需明确报错
    """


def _is_event(value: object) -> bool:
    """检查值是否是合法的 Hook 事件名称。

    这是什么：事件名称校验器
    Java 类比：类似 private boolean isValidEvent(Object value)
    为什么需要：运行时校验事件名称，防止拼写错误或传入非法事件
    """
    return value in HOOK_EVENTS


def _is_prepared(value: object) -> bool:
    """检查值是否是有效的已准备工具调用（无错误且包含定义和参数）。

    这是什么：工具调用完整性校验器
    Java 类比：类似 private boolean isValidPrepared(Object value)
    为什么需要：Hook 只能处理已通过校验的工具调用，确保定义和参数都存在
    """
    return isinstance(value, PreparedToolCall) and value.error is None and value.definition is not None and value.arguments is not None


@dataclass(frozen=True, slots=True)
class HookContext:
    """某次回调能看到的最小事件上下文。

    这是什么：Hook 回调的不可变输入上下文
    Java 类比：类似 record HookContext(HookEvent event, ...) 带字段校验
    为什么需要：为每个生命周期事件提供强类型上下文，确保回调只能访问该事件允许的字段

    字段说明：
        event: 触发的事件类型（四选一）
        message: UserPromptSubmit 事件中的用户消息
        prepared: PreToolUse/PostToolUse 事件中的已准备工具调用
        result: PostToolUse 事件中的工具执行结果
        history: Stop 事件中的完整对话历史
        stop_hook_active: Stop 事件是否在 stop hook 激活状态下触发
    """

    event: HookEvent
    message: ChatMessage | None = None
    prepared: PreparedToolCall | None = None
    result: ToolResult | None = None
    history: tuple[ChatMessage, ...] = ()
    stop_hook_active: bool = False

    def __post_init__(self) -> None:
        """构造后校验：每个事件只能携带对应的字段组合。

        这是什么：上下文字段的契约校验器
        Java 类比：类似构造器末尾调用 validate() 检查字段组合
        为什么需要：防止事件和字段不匹配（如 Stop 事件却携带 prepared），确保 Hook 拿到正确数据
        """
        if not _is_event(self.event):
            raise HookContractError("event 必须是受支持的 HookEvent")
        if not isinstance(self.history, tuple) or not all(isinstance(item, (SystemMessage, AssistantMessage, UserMessage, ToolMessage)) for item in self.history):
            raise HookContractError(f"{self.event} history 必须全部是合法消息")
        if not isinstance(self.stop_hook_active, bool):
            raise HookContractError("stop_hook_active 必须是 bool")
        if self.event == "UserPromptSubmit":
            if not isinstance(self.message, UserMessage):
                raise HookContractError("UserPromptSubmit 需要 user message")
            if self.prepared is not None or self.result is not None or self.history or self.stop_hook_active:
                raise HookContractError("UserPromptSubmit 收到了其他事件的字段")
        elif self.event == "PreToolUse":
            if not _is_prepared(self.prepared):
                raise HookContractError("PreToolUse 需要有效的 prepared tool call")
            if self.message is not None or self.result is not None or self.history or self.stop_hook_active:
                raise HookContractError("PreToolUse 收到了其他事件的字段")
        elif self.event == "PostToolUse":
            if not _is_prepared(self.prepared) or not isinstance(self.result, ToolResult):
                raise HookContractError("PostToolUse 需要 prepared tool call 和 tool result")
            if self.message is not None or self.history or self.stop_hook_active:
                raise HookContractError("PostToolUse 收到了其他事件的字段")
        elif self.message is not None or self.prepared is not None or self.result is not None:
            raise HookContractError("Stop 收到了其他事件的字段")


@dataclass(frozen=True, slots=True)
class HookResult:
    """回调对循环提出的结构化影响。

    这是什么：Hook 回调的不可变返回结果
    Java 类比：类似 record HookResult(...) 带字段校验和防御性复制
    为什么需要：让 Hook 以声明方式影响 Agent 流程，而不是直接修改状态（避免扩展逻辑变成一堆 if/else）

    字段说明：
        permission_behavior: 权限行为覆盖（仅 PreToolUse 有效）
        updated_input: 修改后的工具调用输入（仅 PreToolUse 有效）
        updated_output: 修改后的工具执行结果（仅 PostToolUse 有效）
        additional_context: 追加到对话中的系统消息
        blocking_error: 阻止工具执行的错误（仅 PreToolUse 有效）
        prevent_continuation: 阻止继续执行（仅 PostToolUse 有效）
        force_continue: 强制继续的用户消息（仅 Stop 有效）
    """

    permission_behavior: PermissionBehavior = "passthrough"
    updated_input: PreparedToolCall | None = None
    updated_output: ToolResult | None = None
    additional_context: tuple[ChatMessage, ...] = ()
    blocking_error: ToolResult | None = None
    prevent_continuation: bool = False
    force_continue: UserMessage | None = None

    def __post_init__(self) -> None:
        """校验字段有效性并防御性复制所有嵌套对象。

        这是什么：结果字段的契约校验和防御性复制
        Java 类比：类似构造器中的 validate() + 深拷贝
        为什么需要：防止回调传入非法值或通过引用修改内部状态
        """
        if self.permission_behavior not in PERMISSION_BEHAVIORS:
            raise HookContractError("permission_behavior 必须是受支持的权限行为")
        if self.updated_input is not None and not _is_prepared(self.updated_input):
            raise HookContractError("updated_input 必须是有效的 prepared tool call")
        if self.updated_output is not None and not isinstance(self.updated_output, ToolResult):
            raise HookContractError("updated_output 必须是 ToolResult")
        if self.blocking_error is not None and (not isinstance(self.blocking_error, ToolResult) or not self.blocking_error.is_error):
            raise HookContractError("blocking_error 必须是错误 ToolResult")
        if not isinstance(self.additional_context, tuple) or not all(isinstance(item, SystemMessage) for item in self.additional_context):
            raise HookContractError("additional_context 只能包含 system 消息")
        if not isinstance(self.prevent_continuation, bool):
            raise HookContractError("prevent_continuation 必须是 bool")
        if self.force_continue is not None and not isinstance(self.force_continue, UserMessage):
            raise HookContractError("force_continue 必须是 user 消息")
        object.__setattr__(self, "updated_input", None if self.updated_input is None else copy_prepared_tool_call(self.updated_input))
        object.__setattr__(self, "updated_output", None if self.updated_output is None else copy_tool_result(self.updated_output))
        object.__setattr__(self, "additional_context", tuple(system_message(item.content or "") for item in self.additional_context))
        object.__setattr__(self, "blocking_error", None if self.blocking_error is None else copy_tool_result(self.blocking_error))
        object.__setattr__(self, "force_continue", None if self.force_continue is None else user_message(self.force_continue.content))

    def validate_for(self, event: HookEvent) -> None:
        """拒绝回调在错误事件上使用字段，类似 Java Bean Validation 的分组校验。

        这是什么：基于事件的字段使用校验器
        Java 类比：类似 @GroupSequence 分组校验，确保字段只在允许的事件中使用
        为什么需要：防止回调在错误的生命周期阶段使用字段（如在 Stop 事件中使用 updated_input）
        """
        invalid: list[str] = []
        if event != "PreToolUse":
            if self.permission_behavior != "passthrough": invalid.append("permission_behavior")
            if self.updated_input is not None: invalid.append("updated_input")
            if self.blocking_error is not None: invalid.append("blocking_error")
        if event != "PostToolUse":
            if self.updated_output is not None: invalid.append("updated_output")
            if self.prevent_continuation: invalid.append("prevent_continuation")
        if event != "Stop" and self.force_continue is not None:
            invalid.append("force_continue")
        if invalid:
            raise HookContractError(f"{event} HookResult 不允许字段: {', '.join(invalid)}")


HookCallback = Callable[[HookContext], HookResult | Awaitable[HookResult]]


class HookRegistry:
    """按注册顺序串行执行四类生命周期回调。

    这是什么：Hook 回调的注册表和执行器
    Java 类比：类似 @Component class HookRegistry { Map<Event, List<Consumer<Context>>> callbacks }
    为什么需要：让扩展点以观察者模式插入生命周期，而不是在主流程中硬编码 if/else
    """

    def __init__(self) -> None:
        """初始化四个事件的空回调列表。

        这是什么：构造器，为每个事件类型创建独立队列
        Java 类比：类似构造器中初始化 Map<Event, List<Callback>>
        为什么需要：让每个事件维护独立的回调队列，按注册顺序执行
        """
        self._callbacks: dict[HookEvent, list[HookCallback]] = {event: [] for event in HOOK_EVENTS}

    def register(self, event: HookEvent, callback: HookCallback) -> None:
        """把回调追加到事件队列尾部；注册顺序就是执行顺序。

        这是什么：回调注册方法
        Java 类比：类似 public void addListener(Event event, Consumer<Context> callback)
        为什么需要：让用户以声明方式注册扩展逻辑，保证执行顺序可预测
        """
        if not _is_event(event):
            raise HookContractError("event 必须是受支持的 HookEvent")
        if not callable(callback):
            raise HookContractError("hook callback 必须可调用")
        self._callbacks[event].append(callback)

    async def run(self, context: HookContext) -> HookResult:
        """串行执行回调并把上一个回调的改写传给下一个回调。

        这是什么：回调链的执行引擎
        Java 类比：类似 CompletableFuture 链式调用，每个回调看到前一个的结果
        为什么需要：让多个 Hook 能协作处理同一事件，后续 Hook 能看到前面的修改
        """
        if not isinstance(context, HookContext):
            raise HookContractError("context 必须是 HookContext")
        combined = HookResult()
        current = context
        for callback in self._callbacks[context.event]:
            outcome = callback(current)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if not isinstance(outcome, HookResult):
                raise HookContractError(f"{context.event} hook callback 必须返回 HookResult")
            outcome.validate_for(context.event)
            normalized = self._normalize_input(current, outcome)
            if normalized is not None:
                outcome = HookResult(permission_behavior=outcome.permission_behavior, updated_input=normalized, additional_context=outcome.additional_context, blocking_error=outcome.blocking_error)
            if context.event == "Stop" and context.stop_hook_active and outcome.force_continue is not None:
                outcome = HookResult(additional_context=outcome.additional_context)
            combined = _merge_results(combined, outcome)
            if outcome.updated_input is not None:
                current = HookContext("PreToolUse", prepared=outcome.updated_input)
            elif outcome.updated_output is not None and current.prepared is not None:
                current = HookContext("PostToolUse", prepared=current.prepared, result=outcome.updated_output)
            if outcome.blocking_error is not None or outcome.force_continue is not None:
                break
        return combined

    async def run_user_prompt(self, message: UserMessage) -> HookResult:
        """执行 UserPromptSubmit 事件的所有回调。

        这是什么：用户提示提交事件的便捷执行方法
        Java 类比：类似 public HookResult onUserPrompt(UserMessage msg)
        为什么需要：为常见事件提供类型安全的快捷方法，避免手动构造 HookContext
        """
        return await self.run(HookContext("UserPromptSubmit", message=message))

    async def run_pre_tool(self, prepared: PreparedToolCall) -> HookResult:
        """执行 PreToolUse 事件的所有回调。

        这是什么：工具执行前事件的便捷执行方法
        Java 类比：类似 public HookResult onPreTool(PreparedToolCall call)
        为什么需要：为常见事件提供类型安全的快捷方法
        """
        return await self.run(HookContext("PreToolUse", prepared=prepared))

    async def run_post_tool(self, prepared: PreparedToolCall, result: ToolResult) -> HookResult:
        """执行 PostToolUse 事件的所有回调。

        这是什么：工具执行后事件的便捷执行方法
        Java 类比：类似 public HookResult onPostTool(PreparedToolCall call, ToolResult result)
        为什么需要：为常见事件提供类型安全的快捷方法
        """
        return await self.run(HookContext("PostToolUse", prepared=prepared, result=result))

    async def run_stop(self, history: Sequence[ChatMessage], stop_hook_active: bool) -> HookResult:
        """执行 Stop 事件的所有回调。

        这是什么：停止事件的便捷执行方法
        Java 类比：类似 public HookResult onStop(List<ChatMessage> history, boolean stopActive)
        为什么需要：为常见事件提供类型安全的快捷方法
        """
        return await self.run(HookContext("Stop", history=tuple(history), stop_hook_active=stop_hook_active))

    @staticmethod
    def _normalize_input(context: HookContext, result: HookResult) -> PreparedToolCall | None:
        """校验并规范化 updated_input，确保它保留原工具的核心属性。

        这是什么：工具调用修改的完整性校验器
        Java 类比：类似 private PreparedToolCall validateUpdate(HookContext ctx, HookResult res)
        为什么需要：防止 Hook 修改工具的 id、名称或定义，确保只能修改参数
        """
        updated = result.updated_input
        if updated is None:
            return None
        original = context.prepared
        if original is None or original.definition is None:
            raise HookContractError("updated_input 需要原 prepared tool call")
        if updated.call.id != original.call.id:
            raise HookContractError("updated_input 必须保留 tool call id")
        if updated.call.name != original.call.name:
            raise HookContractError("updated_input 必须保留工具名称")
        if updated.definition is not original.definition:
            raise HookContractError("updated_input 必须保留注册表中的工具定义")
        if original.definition.validator is not None and (updated.arguments is None or not original.definition.validator(updated.arguments)):
            raise HookContractError("updated_input 参数没有通过原工具 schema")
        return copy_prepared_tool_call(updated, definition=original.definition)


def _merge_results(current: HookResult, incoming: HookResult) -> HookResult:
    """合并多个回调：上下文累积、改写以后者为准、权限取最严格。

    这是什么：多个 Hook 结果的合并策略
    Java 类比：类似 HookResult merge(HookResult a, HookResult b)
    为什么需要：多个 Hook 同时影响时，需要明确合并规则（后覆盖前，权限取严）
    """
    return HookResult(
        permission_behavior=_stronger_permission(current.permission_behavior, incoming.permission_behavior),
        updated_input=incoming.updated_input or current.updated_input,
        updated_output=incoming.updated_output or current.updated_output,
        additional_context=current.additional_context + incoming.additional_context,
        blocking_error=current.blocking_error or incoming.blocking_error,
        prevent_continuation=current.prevent_continuation or incoming.prevent_continuation,
        force_continue=current.force_continue or incoming.force_continue,
    )


def _stronger_permission(current: PermissionBehavior, incoming: PermissionBehavior) -> PermissionBehavior:
    """返回两个权限行为中更严格的一个（deny > ask > allow > passthrough）。

    这是什么：权限行为的优先级比较器
    Java 类比：类似 PermissionBehavior selectStricter(PermissionBehavior a, PermissionBehavior b)
    为什么需要：多个 Hook 同时影响权限时，确保最严格的限制生效
    """
    priority: Mapping[PermissionBehavior, int] = {"passthrough": 0, "allow": 1, "ask": 2, "deny": 3}
    return incoming if priority[incoming] > priority[current] else current
