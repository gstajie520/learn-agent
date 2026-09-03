"""第四章 Hook 生命周期。

这是什么：Hook 系统让外部扩展在 Agent 循环的关键节点插入逻辑，而无需修改核心代码
Java 类比：`HookRegistry` 类似按事件分组的观察者注册表（Observer Pattern）
为什么需要：避免在核心循环里堆积 if/else，让扩展逻辑按契约声明影响而不是直接修改状态

核心设计：
- HookContext：回调看到的只读上下文（类似 Java 不可变 DTO）
- HookResult：回调声明的影响（类似 Command 对象）
- HookRegistry：按注册顺序执行回调链（类似 Spring 拦截器链）
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

# ==================== 事件类型定义 ====================
# 这是什么：定义 Hook 系统支持的四种生命周期事件
# Java 类比：类似枚举 enum HookEvent { USER_PROMPT_SUBMIT, PRE_TOOL_USE, POST_TOOL_USE, STOP }
# 为什么需要：限制事件类型，防止注册到不存在的钩子点

HookEvent = Literal["UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]  # Python 的字面量类型，限制只能是这四个值
HOOK_EVENTS: tuple[HookEvent, ...] = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")  # 所有合法事件的集合


class HookContractError(Exception):
    """Hook 输入、输出或事件字段违反契约时抛出的领域异常。

    这是什么：Hook 系统的专用异常类型
    Java 类比：类似自定义的 HookValidationException extends RuntimeException
    为什么需要：区分 Hook 契约错误和其他运行时错误，便于上层精确捕获
    """


# ==================== 辅助校验函数 ====================

def _is_event(value: object) -> bool:
    """检查值是否是合法的 Hook 事件类型。

    这是什么：类型守卫函数，在运行时验证事件合法性
    Java 类比：类似 boolean isValidEvent(Object value)
    为什么需要：Python 的类型提示是静态的，运行时需要额外检查
    """
    return value in HOOK_EVENTS  # 检查值是否在预定义的事件集合中


def _is_prepared(value: object) -> bool:
    """检查值是否是有效的 PreparedToolCall（已通过校验、无错误）。

    这是什么：复合校验函数，确保工具调用对象处于可执行状态
    Java 类比：类似 boolean isValidPreparedCall(Object value)
    为什么需要：PreparedToolCall 可能携带错误，Hook 只应处理有效的调用
    """
    return (
        isinstance(value, PreparedToolCall)  # 类型必须正确
        and value.error is None  # 准备阶段没有错误
        and value.definition is not None  # 有注册的工具定义
        and value.arguments is not None  # 参数已解析
    )


# ==================== Hook 上下文 ====================

@dataclass(frozen=True, slots=True)  # frozen=True 保证不可变，类似 Java 的 record
class HookContext:
    """某次回调能看到的最小事件上下文。

    这是什么：传递给 Hook 回调函数的只读数据容器
    Java 类比：不可变 record HookContext，字段根据事件类型有选择地填充
    为什么需要：让 Hook 只看到当前事件相关的数据，避免错误使用其他阶段的字段

    设计要点：
    - 不同事件只填充对应字段（UserPromptSubmit 只有 message，PreToolUse 只有 prepared）
    - __post_init__ 强制校验字段归属，防止 Hook 读取错误阶段的数据
    - 所有字段都是不可变的（tuple、frozen dataclass），保护核心循环状态

    参数：
        event: 当前触发的 Hook 事件类型
        message: UserPromptSubmit 事件时的用户消息
        prepared: PreToolUse/PostToolUse 事件时的已校验工具调用
        result: PostToolUse 事件时的工具执行结果
        history: Stop 事件时的完整对话历史
        stop_hook_active: Stop 事件是否在活跃的停止钩子中
    """

    event: HookEvent  # 当前事件类型（四选一）
    message: ChatMessage | None = None  # 用户消息（仅 UserPromptSubmit）
    prepared: PreparedToolCall | None = None  # 已校验的工具调用（PreToolUse/PostToolUse）
    result: ToolResult | None = None  # 工具执行结果（仅 PostToolUse）
    history: tuple[ChatMessage, ...] = ()  # 对话历史（仅 Stop）
    stop_hook_active: bool = False  # 是否在停止钩子中（仅 Stop）

    def __post_init__(self) -> None:
        """构造后校验：根据事件类型强制检查字段归属。

        这是什么：dataclass 的初始化后钩子，类似 Java Bean Validation
        Java 类比：类似在构造器最后调用 validate() 方法
        为什么需要：Python 没有 Java 那样的编译期字段检查，必须在运行时强制契约
        """
        # 第一步：基础类型检查
        if not _is_event(self.event):
            raise HookContractError("event 必须是受支持的 HookEvent")
        if not isinstance(self.history, tuple) or not all(
            isinstance(item, (SystemMessage, AssistantMessage, UserMessage, ToolMessage))
            for item in self.history
        ):
            raise HookContractError(f"{self.event} history 必须全部是合法消息")
        if not isinstance(self.stop_hook_active, bool):
            raise HookContractError("stop_hook_active 必须是 bool")

        # 第二步：按事件类型校验字段归属（类似 Java 的分组校验）
        if self.event == "UserPromptSubmit":  # 用户提交事件只需要用户消息
            if not isinstance(self.message, UserMessage):
                raise HookContractError("UserPromptSubmit 需要 user message")
            if (  # 其他字段必须为空
                self.prepared is not None
                or self.result is not None
                or self.history
                or self.stop_hook_active
            ):
                raise HookContractError("UserPromptSubmit 收到了其他事件的字段")
        elif self.event == "PreToolUse":  # 工具使用前事件只需要已校验的工具调用
            if not _is_prepared(self.prepared):
                raise HookContractError("PreToolUse 需要有效的 prepared tool call")
            if (  # 其他字段必须为空
                self.message is not None
                or self.result is not None
                or self.history
                or self.stop_hook_active
            ):
                raise HookContractError("PreToolUse 收到了其他事件的字段")
        elif self.event == "PostToolUse":  # 工具使用后事件需要工具调用和执行结果
            if not _is_prepared(self.prepared) or not isinstance(self.result, ToolResult):
                raise HookContractError("PostToolUse 需要 prepared tool call 和 tool result")
            if self.message is not None or self.history or self.stop_hook_active:
                raise HookContractError("PostToolUse 收到了其他事件的字段")
        elif self.message is not None or self.prepared is not None or self.result is not None:  # Stop 事件只需要 history
            raise HookContractError("Stop 收到了其他事件的字段")


# ==================== Hook 结果 ====================

@dataclass(frozen=True, slots=True)
class HookResult:
    """回调对循环提出的结构化影响。

    这是什么：Hook 回调函数的返回值，声明希望对 Agent 循环产生的影响
    Java 类比：不可变 record HookResult，类似 Command 模式中的命令对象
    为什么需要：让 Hook 通过声明式接口影响循环，而不是直接修改状态（保持核心循环封装性）

    设计约束：
    - additional_context 只能是 system 消息（Hook 不能伪造 assistant/tool 配对）
    - force_continue 只能是 user 消息（确保循环继续时有明确用户输入）
    - 所有对象都会被复制（防止 Hook 持有内部状态引用）

    参数：
        permission_behavior: 权限行为（passthrough/allow/ask/deny）
        updated_input: 修改后的工具输入（仅 PreToolUse 可用）
        updated_output: 修改后的工具输出（仅 PostToolUse 可用）
        additional_context: 额外的系统消息（追加到历史）
        blocking_error: 阻断性错误（跳过工具执行，直接返回错误）
        prevent_continuation: 阻止循环继续（仅 PostToolUse 可用）
        force_continue: 强制循环继续的用户消息（仅 Stop 可用）
    """

    permission_behavior: PermissionBehavior = "passthrough"  # 默认透传权限决策
    updated_input: PreparedToolCall | None = None  # 修改工具输入参数
    updated_output: ToolResult | None = None  # 修改工具执行结果
    additional_context: tuple[ChatMessage, ...] = ()  # 追加系统消息
    blocking_error: ToolResult | None = None  # 阻断性错误结果
    prevent_continuation: bool = False  # 是否阻止继续
    force_continue: UserMessage | None = None  # 强制继续的用户消息

    def __post_init__(self) -> None:
        """构造后校验和深拷贝：确保契约正确并防止引用泄漏。

        这是什么：校验返回值合法性，并复制所有可变对象
        Java 类比：类似构造器中的防御性复制（Defensive Copy）
        为什么需要：防止 Hook 通过引用修改内部状态，保证不可变性
        """
        # 第一步：字段类型和契约校验
        if self.permission_behavior not in PERMISSION_BEHAVIORS:
            raise HookContractError("permission_behavior 必须是受支持的权限行为")
        if self.updated_input is not None and not _is_prepared(self.updated_input):
            raise HookContractError("updated_input 必须是有效的 prepared tool call")
        if self.updated_output is not None and not isinstance(self.updated_output, ToolResult):
            raise HookContractError("updated_output 必须是 ToolResult")
        if self.blocking_error is not None and (
            not isinstance(self.blocking_error, ToolResult) or not self.blocking_error.is_error
        ):
            raise HookContractError("blocking_error 必须是错误 ToolResult")
        if not isinstance(self.additional_context, tuple) or not all(
            isinstance(item, SystemMessage) for item in self.additional_context
        ):
            raise HookContractError("additional_context 只能包含 system 消息")
        if not isinstance(self.prevent_continuation, bool):
            raise HookContractError("prevent_continuation 必须是 bool")
        if self.force_continue is not None and not isinstance(self.force_continue, UserMessage):
            raise HookContractError("force_continue 必须是 user 消息")

        # 第二步：防御性复制所有对象字段（类似 Java 的 clone()）
        # 使用 object.__setattr__ 绕过 frozen=True 限制，只在初始化时可修改
        object.__setattr__(
            self,
            "updated_input",
            None if self.updated_input is None else copy_prepared_tool_call(self.updated_input),
        )
        object.__setattr__(
            self,
            "updated_output",
            None if self.updated_output is None else copy_tool_result(self.updated_output),
        )
        object.__setattr__(
            self,
            "additional_context",
            tuple(system_message(item.content or "") for item in self.additional_context),  # 重新构造消息对象
        )
        object.__setattr__(
            self,
            "blocking_error",
            None if self.blocking_error is None else copy_tool_result(self.blocking_error),
        )
        object.__setattr__(
            self,
            "force_continue",
            None if self.force_continue is None else user_message(self.force_continue.content),
        )

    def validate_for(self, event: HookEvent) -> None:
        """拒绝回调在错误事件上使用字段。

        这是什么：分组校验方法，确保字段只在对应事件中使用
        Java 类比：类似 Bean Validation 的 @GroupSequence 分组校验
        为什么需要：不同事件支持不同字段，PreToolUse 不能返回 updated_output
        """
        invalid: list[str] = []
        if event != "PreToolUse":  # 只有 PreToolUse 可以修改输入和权限
            if self.permission_behavior != "passthrough":
                invalid.append("permission_behavior")
            if self.updated_input is not None:
                invalid.append("updated_input")
            if self.blocking_error is not None:
                invalid.append("blocking_error")
        if event != "PostToolUse":  # 只有 PostToolUse 可以修改输出和阻止继续
            if self.updated_output is not None:
                invalid.append("updated_output")
            if self.prevent_continuation:
                invalid.append("prevent_continuation")
        if event != "Stop" and self.force_continue is not None:  # 只有 Stop 可以强制继续
            invalid.append("force_continue")
        if invalid:
            raise HookContractError(f"{event} HookResult 不允许字段: {', '.join(invalid)}")


# ==================== Hook 回调类型 ====================
# 这是什么：Hook 回调函数的类型签名
# Java 类比：类似 Function<HookContext, HookResult> 或 Function<HookContext, CompletableFuture<HookResult>>
# 为什么需要：明确回调的输入输出契约，支持同步和异步两种形式

HookCallback = Callable[[HookContext], HookResult | Awaitable[HookResult]]  # 可返回 HookResult 或 async HookResult


# ==================== Hook 注册表 ====================

class HookRegistry:
    """按注册顺序串行执行四类生命周期回调。

    这是什么：Hook 系统的核心调度器，管理所有回调的注册和执行
    Java 类比：类似 Spring 的拦截器链管理器，按注册顺序执行回调
    为什么需要：集中管理 Hook 生命周期，确保回调按顺序执行且结果正确合并

    核心机制：
    1. 注册：按事件类型分组存储回调（字典+列表）
    2. 执行：串行调用回调链，上一个的改写传给下一个
    3. 合并：累积 additional_context，改写以最后一个为准
    """

    def __init__(self) -> None:
        """初始化空的回调注册表。

        这是什么：创建四个事件的空回调列表
        Java 类比：类似 Map<HookEvent, List<HookCallback>>
        为什么需要：每个事件独立维护回调链，互不干扰
        """
        # 为每个事件类型初始化空列表，类似 Java 的 EnumMap
        self._callbacks: dict[HookEvent, list[HookCallback]] = {event: [] for event in HOOK_EVENTS}

    def register(self, event: HookEvent, callback: HookCallback) -> None:
        """把回调追加到事件队列尾部；注册顺序就是执行顺序。

        这是什么：注册一个 Hook 回调到指定事件
        Java 类比：类似 registry.addInterceptor(event, callback)
        为什么需要：让外部扩展能插入自定义逻辑到 Agent 生命周期

        参数：
            event: Hook 事件类型（四选一）
            callback: 回调函数（接收 HookContext，返回 HookResult）
        """
        if not _is_event(event):
            raise HookContractError("event 必须是受支持的 HookEvent")
        if not callable(callback):
            raise HookContractError("hook callback 必须可调用")
        self._callbacks[event].append(callback)  # 追加到列表尾部，保持注册顺序

    async def run(self, context: HookContext) -> HookResult:
        """串行执行回调并把上一个回调的改写传给下一个回调。

        这是什么：执行指定事件的所有回调，并合并结果
        Java 类比：类似责任链模式的执行器（Chain of Responsibility）
        为什么需要：确保回调按顺序执行，且每个回调能看到前面回调的修改

        执行流程：
        1. 按注册顺序遍历回调
        2. 如果回调修改了输入/输出，更新当前上下文
        3. 把当前结果与之前结果合并（上下文累积，改写覆盖）
        4. 如果遇到 blocking_error 或 force_continue，立即中断链

        参数：
            context: 当前事件的上下文数据

        返回：
            HookResult: 所有回调的合并结果
        """
        if not isinstance(context, HookContext):
            raise HookContractError("context 必须是 HookContext")

        combined = HookResult()  # 初始化空结果，用于累积所有回调的影响
        current = context  # 当前上下文，后续回调可能看到前面回调的修改

        for callback in self._callbacks[context.event]:  # 按注册顺序执行
            # 调用回调函数，可能返回同步或异步结果
            outcome = callback(current)
            if inspect.isawaitable(outcome):  # 如果是 async 函数，等待结果
                outcome = await outcome

            # 校验返回值类型和字段归属
            if not isinstance(outcome, HookResult):
                raise HookContractError(f"{context.event} hook callback 必须返回 HookResult")
            outcome.validate_for(context.event)  # 确保返回的字段适用于当前事件

            # 规范化输入修改：确保修改后的工具调用保留原始 schema 和定义
            normalized = self._normalize_input(current, outcome)
            if normalized is not None:
                outcome = HookResult(
                    permission_behavior=outcome.permission_behavior,
                    updated_input=normalized,
                    additional_context=outcome.additional_context,
                    blocking_error=outcome.blocking_error,
                )

            # 特殊处理：Stop Hook 主动触发时不允许 force_continue
            if (
                context.event == "Stop"
                and context.stop_hook_active
                and outcome.force_continue is not None
            ):
                outcome = HookResult(additional_context=outcome.additional_context)

            # 合并当前回调结果到累积结果
            combined = _merge_results(combined, outcome)

            # 更新上下文：如果回调修改了输入/输出，下一个回调看到修改后的版本
            if outcome.updated_input is not None:
                current = HookContext("PreToolUse", prepared=outcome.updated_input)
            elif outcome.updated_output is not None and current.prepared is not None:
                current = HookContext(
                    "PostToolUse", prepared=current.prepared, result=outcome.updated_output
                )

            # 提前终止：遇到阻断错误或强制继续指令，后续回调不再执行
            if outcome.blocking_error is not None or outcome.force_continue is not None:
                break

        return combined

    async def run_user_prompt(self, message: UserMessage) -> HookResult:
        """执行 UserPromptSubmit 事件的回调链。

        这是什么：用户提交消息时的便捷入口
        Java 类比：类似 executeUserPromptHooks(UserMessage)
        为什么需要：封装上下文构造，简化调用方代码
        """
        return await self.run(HookContext("UserPromptSubmit", message=message))

    async def run_pre_tool(self, prepared: PreparedToolCall) -> HookResult:
        """执行 PreToolUse 事件的回调链。

        这是什么：工具执行前的便捷入口
        Java 类比：类似 executePreToolHooks(PreparedToolCall)
        为什么需要：封装上下文构造，让调用方不需要手动创建 HookContext
        """
        return await self.run(HookContext("PreToolUse", prepared=prepared))

    async def run_post_tool(self, prepared: PreparedToolCall, result: ToolResult) -> HookResult:
        """执行 PostToolUse 事件的回调链。

        这是什么：工具执行后的便捷入口
        Java 类比：类似 executePostToolHooks(PreparedToolCall, ToolResult)
        为什么需要：封装上下文构造，统一工具执行后的回调入口
        """
        return await self.run(HookContext("PostToolUse", prepared=prepared, result=result))

    async def run_stop(self, history: Sequence[ChatMessage], stop_hook_active: bool) -> HookResult:
        """执行 Stop 事件的回调链。

        这是什么：循环停止时的便捷入口
        Java 类比：类似 executeStopHooks(List<ChatMessage>, boolean)
        为什么需要：封装上下文构造，传递完整历史和停止钩子状态
        """
        return await self.run(
            HookContext("Stop", history=tuple(history), stop_hook_active=stop_hook_active)
        )

    @staticmethod
    def _normalize_input(context: HookContext, result: HookResult) -> PreparedToolCall | None:
        """规范化输入修改：确保修改后的工具调用保留原始定义和 schema。

        这是什么：输入修改的防御性校验
        Java 类比：类似 validateAndNormalizeInput(context, result)
        为什么需要：防止 Hook 修改 call.id、工具名或绕过 schema 校验

        校验规则：
        1. call.id 必须保持不变（用于消息配对）
        2. 工具名必须保持不变（不能偷梁换柱）
        3. 工具定义必须保持不变（来自注册表的原始定义）
        4. 修改后的参数必须通过原工具的 schema 校验
        """
        updated = result.updated_input
        if updated is None:
            return None

        original = context.prepared
        if original is None or original.definition is None:
            raise HookContractError("updated_input 需要原 prepared tool call")

        # 强制不可变约束：call.id 和工具名不能改
        if updated.call.id != original.call.id:
            raise HookContractError("updated_input 必须保留 tool call id")
        if updated.call.name != original.call.name:
            raise HookContractError("updated_input 必须保留工具名称")

        # 强制 schema 约束：修改后的参数必须符合原工具的定义
        if updated.definition is not original.definition:
            raise HookContractError("updated_input 必须保留注册表中的工具定义")
        if original.definition.validator is not None and (
            updated.arguments is None or not original.definition.validator(updated.arguments)
        ):
            raise HookContractError("updated_input 参数没有通过原工具 schema")

        return copy_prepared_tool_call(updated, definition=original.definition)


# ==================== 结果合并逻辑 ====================

def _merge_results(current: HookResult, incoming: HookResult) -> HookResult:
    """合并多个回调：上下文累积、改写以后者为准、权限取最严格。

    这是什么：多个回调结果的归约函数
    Java 类比：类似 Stream.reduce((a, b) -> mergeResults(a, b))
    为什么需要：确保回调链的结果正确组合，既保留所有上下文，又避免冲突

    合并规则：
    1. additional_context：累加（所有回调的系统消息都保留）
    2. 改写字段（updated_input/output）：后者覆盖前者（最后修改生效）
    3. permission_behavior：取更严格的（deny > ask > allow > passthrough）
    4. 终止字段（blocking_error/force_continue）：后者覆盖前者（最后决定生效）
    """
    return HookResult(
        permission_behavior=_stronger_permission(
            current.permission_behavior, incoming.permission_behavior
        ),
        updated_input=incoming.updated_input or current.updated_input,  # 后者优先
        updated_output=incoming.updated_output or current.updated_output,  # 后者优先
        additional_context=current.additional_context + incoming.additional_context,  # 累加
        blocking_error=current.blocking_error or incoming.blocking_error,  # 后者优先
        prevent_continuation=current.prevent_continuation or incoming.prevent_continuation,  # 逻辑或
        force_continue=current.force_continue or incoming.force_continue,  # 后者优先
    )


def _stronger_permission(
    current: PermissionBehavior, incoming: PermissionBehavior
) -> PermissionBehavior:
    """取两个权限行为中更严格的一个。

    这是什么：权限行为的优先级比较函数
    Java 类比：类似 Comparator.comparing(PermissionBehavior::getPriority)
    为什么需要：多个 Hook 返回不同权限时，应该取最严格的（安全优先原则）

    优先级：deny (3) > ask (2) > allow (1) > passthrough (0)
    """
    priority: Mapping[PermissionBehavior, int] = {"passthrough": 0, "allow": 1, "ask": 2, "deny": 3}
    return incoming if priority[incoming] > priority[current] else current
