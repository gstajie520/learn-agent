"""带 Hook 生命周期的 Agent 核心循环。

这是什么：第 4 章扩展的 Agent 循环，集成 Hook 系统、权限策略和多个观察器
Java 类比：类似 Spring 的 Controller + Interceptor Chain，按固定顺序调用拦截器
为什么需要：在核心循环中插入扩展点，支持权限审批、日志记录、记忆存储等功能

核心扩展点：
    1. user_prompt Hook：用户输入后触发（可注入额外上下文）
    2. before_model Hook：每次调用模型前触发（可注入临时指导）
    3. pre_tool_use Hook：工具执行前触发（可阻断或修改参数）
    4. post_tool_use Hook：工具执行后触发（可修改结果或强制停止）
    5. stop Hook：模型返回文本时触发（可强制继续循环）

工具调用配对约束（第 4 章最重要的约束）：
    无论 Hook 阻断、异常还是主动停止，每个 tool_call_id 都必须得到且只得到
    一条 tool 消息。否则下次模型请求会被 OpenAI API 拒绝（400 Bad Request）。

Java 角度：这是应用服务。它按照固定顺序调用模型、Hook、权限策略和工具注册表，
但不负责创建这些依赖。第四章最重要的约束是：无论 Hook 阻断、异常还是主动停止，
每个 `tool_call_id` 都必须得到且只得到一条 tool 消息。
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .hooks import HookContractError, HookRegistry, HookResult
from .messages import (
    ChatMessage,
    ToolCall,
    system_message,
    tool_message,
    user_message,
    validate_tool_pairing,
)
from .model import ModelClient, ModelReply, ModelRequest
from .permissions import PermissionDecision, PermissionPolicy, PermissionRequest
from .tools import PreparedToolCall, ToolContext, ToolRegistry, ToolResult, tool_error


class AgentRunError(Exception):
    """Agent 执行过程中的领域错误。

    这是什么：Agent 运行时的基础异常类
    Java 类比：类似自定义的 AgentException 基类
    为什么需要：区分 Agent 业务错误和系统错误（如 IOException）
    """


class AgentLimitError(AgentRunError):
    """达到最大模型调用轮数。

    这是什么：Agent 循环超过 max_turns 限制的异常
    Java 类比：类似 TooManyRequestsException
    为什么需要：防止模型陷入工具调用死循环，保护成本和性能

    触发场景：模型连续调用工具 max_turns 次仍未返回文本
    """


class IncompleteModelReplyError(AgentRunError):
    """模型输出因 token 限制被截断。

    这是什么：模型回复不完整的异常
    Java 类比：类似 IncompleteDataException
    为什么需要：避免把半截回答当成完整结果返回给用户

    触发场景：finish_reason == "length"（达到 max_tokens）
    """


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """旧章节兼容授权结果：是否允许，以及给模型看的原因。

    这是什么：第 3 章的工具授权返回值（第 4 章后被 PermissionPolicy 替代）
    Java 类比：类似 AuthorizationResult record
    为什么需要：向后兼容旧代码，新代码应使用 PermissionPolicy

    字段说明：
        allowed: True 表示可以执行工具；False 表示只生成拒绝结果
        reason: 给人和模型看的原因，拒绝时尤其重要（模型会看到这个文本）
    """

    allowed: bool
    reason: str


class ToolAuthorizer(Protocol):
    """旧章节兼容授权接口，类似 Java 中的鉴权 Service。

    这是什么：第 3 章的工具授权接口（第 4 章后被 PermissionPolicy 替代）
    Java 类比：interface ToolAuthorizer { Decision authorize(...); }
    为什么需要：向后兼容旧代码，新代码应使用 PermissionPolicy
    """

    def authorize(
        self, prepared: PreparedToolCall, context: ToolContext
    ) -> ToolAuthorizationDecision: ...


class ToolRoundObserver(Protocol):
    """工具轮观察器接口，类似 Java 中应用服务依赖的扩展 interface。

    这是什么：观察工具调用的扩展接口（如 TodoTracker 实现此接口）
    Java 类比：interface ToolRoundObserver（观察者模式）
    为什么需要：让外部组件（如 TODO 系统）观察工具调用，而不侵入核心循环

    两个回调：
        before_model: 每次调用模型前，返回临时指导消息（不进入正式历史）
        record_tool_round: 整轮工具执行完成后，记录本轮调用过的工具名
    """

    def before_model(self) -> tuple[ChatMessage, ...]:
        """返回只用于下一次模型请求的临时指导，不进入正式历史。

        这是什么：动态注入临时上下文的回调
        Java 类比：类似 RequestInterceptor.preHandle()
        为什么需要：TodoTracker 可以在每次请求前插入当前 TODO 列表
        """

    def record_tool_round(self, tool_names: tuple[str, ...]) -> None:
        """整轮工具结果全部落盘后，记录本轮调用过的工具名。

        这是什么：工具调用记录的回调
        Java 类比：类似 AuditLogger.logToolUsage()
        为什么需要：TodoTracker 可以根据工具调用自动勾选完成的 TODO 项
        """


class RequestHistoryProcessor(Protocol):
    """请求发给模型前的临时历史处理器。

    这是什么：历史压缩/裁剪的扩展接口
    Java 类比：interface HistoryProcessor（策略模式）
    为什么需要：当历史过长时，可以压缩或裁剪历史再发给模型
    """

    def prepare(self, history: tuple[ChatMessage, ...]) -> tuple[ChatMessage, ...]: ...


class ToolResultProcessor(Protocol):
    """整批工具结果回填 canonical history 前的处理器。

    这是什么：工具结果后处理的扩展接口
    Java 类比：interface ResultProcessor（策略模式）
    为什么需要：可以在工具结果写入历史前进行裁剪或摘要
    """

    def compact_tool_results(self, results: tuple[ToolResult, ...]) -> "ProcessedToolResults": ...


class TurnLifecycle(Protocol):
    """一轮 Agent 的生命周期边界，类似 Java 的请求拦截器链。

    这是什么：Agent 轮次生命周期的扩展接口
    Java 类比：interface TurnLifecycle（拦截器模式）
    为什么需要：MemorySession 实现此接口，在轮次开始和结束时处理长期记忆
    """

    def begin_turn(self, query: str) -> None: ...

    def before_model(self) -> tuple[ChatMessage, ...]: ...

    def complete(self, history: tuple[ChatMessage, ...]) -> None: ...


class SystemPromptProvider(Protocol):
    """每轮模型请求前渲染 system prompt，类似 Java ``Supplier<String>``。

    这是什么：动态生成 system prompt 的扩展接口
    Java 类比：interface Supplier<String>（工厂模式）
    为什么需要：支持动态 system prompt（如根据时间、上下文变化）
    """

    def render(self) -> str: ...


class ModelRequestExecutor(Protocol):
    """一次逻辑模型请求执行器，内部可以重试但不能重进 Agent Loop。

    这是什么：模型请求执行的扩展接口（支持重试、缓存等）
    Java 类比：interface RequestExecutor（策略模式）
    为什么需要：封装模型请求的重试逻辑、错误处理、缓存等
    """

    def begin_turn(self) -> None: ...

    def complete(self, request: ModelRequest) -> ModelReply: ...


class ProcessedToolResults(Protocol):
    """结果处理器只需要公开不可变的 ``results`` 字段。

    这是什么：工具结果处理后的返回值接口
    Java 类比：interface ProcessedResults（值对象）
    为什么需要：封装处理后的结果，保证不可变性
    """

    @property
    def results(self) -> tuple[ToolResult, ...]: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次 Agent 运行结束后返回给调用方的不可变结果。"""

    final_text: str
    history: tuple[ChatMessage, ...]
    turns: int


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """一次工具链路的内部结果，不暴露给 AgentRunner 外部。"""

    result: ToolResult
    additional_context: tuple[ChatMessage, ...] = ()
    prevent_continuation: bool = False


class AgentRunner:
    """在确定位置发布 Hook 事件的单会话状态机。"""

    def __init__(
        self,
        model: ModelClient,
        tools: ToolRegistry,
        system_prompt: str,
        workspace: str,
        system_prompt_provider: SystemPromptProvider | None = None,
        model_request_executor: ModelRequestExecutor | None = None,
        max_turns: int = 20,
        identity: str = "user",
        authorizer: ToolAuthorizer | None = None,
        permission_policy: PermissionPolicy | None = None,
        hooks: HookRegistry | None = None,
        tool_round_observer: ToolRoundObserver | None = None,
        history_processor: RequestHistoryProcessor | None = None,
        tool_result_processor: ToolResultProcessor | None = None,
        turn_lifecycle: TurnLifecycle | None = None,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns 必须是正整数")
        if not identity.strip():
            raise ValueError("identity 不能为空")
        if not system_prompt.strip():
            raise ValueError("system_prompt 不能为空")
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        if system_prompt_provider is not None and not callable(
            getattr(system_prompt_provider, "render", None)
        ):
            raise TypeError("system_prompt_provider 必须实现 render()")
        self._system_prompt_provider = system_prompt_provider
        self._model_request_executor = model_request_executor
        self._workspace = str(Path(workspace).resolve())
        self._max_turns = max_turns
        self._identity = identity
        self._authorizer = authorizer
        self._permission_policy = (
            PermissionPolicy()
            if permission_policy is None and hooks is not None
            else permission_policy
        )
        self._hooks = hooks or HookRegistry()
        self._tool_round_observer = tool_round_observer
        self._history_processor = history_processor
        self._tool_result_processor = tool_result_processor
        self._turn_lifecycle = turn_lifecycle
        self._history: list[ChatMessage] = []

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        """返回不可变历史副本，外部不能修改下一轮模型请求。"""
        return tuple(self._history)

    def run(self, prompt: str) -> RunResult:
        """同步入口；内部用 asyncio 顺序等待同步或异步 Hook。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._run(prompt))
        raise AgentRunError("当前线程已有 asyncio 事件循环，请在同步入口外调用 AgentRunner.run")

    async def _run(self, prompt: str) -> RunResult:
        submitted = user_message(prompt)
        prompt_hook = await self._hooks.run_user_prompt(submitted)
        self._history.extend((submitted, *prompt_hook.additional_context))
        if self._turn_lifecycle is not None:
            # 长期记忆属于辅助能力。MemorySession 会自行记录中文错误，不应让
            # 记忆文件损坏或 side-query 失败挡住用户的主请求。
            self._turn_lifecycle.begin_turn(prompt)
        if self._model_request_executor is not None:
            self._model_request_executor.begin_turn()
        context = ToolContext(self._workspace, self._identity)
        stop_hook_active = False

        for turn in range(1, self._max_turns + 1):
            validate_tool_pairing(self._history)
            snapshot = self._tools.snapshot()
            # observer_guidance 只拼到本次请求，不 append 到 history。
            observer_guidance = (
                ()
                if self._tool_round_observer is None
                else self._tool_round_observer.before_model()
            )
            request_history = (
                tuple(self._history)
                if self._history_processor is None
                else self._history_processor.prepare(tuple(self._history))
            )
            validate_tool_pairing(list(request_history))
            turn_guidance = (
                () if self._turn_lifecycle is None else self._turn_lifecycle.before_model()
            )
            validate_tool_pairing(list(turn_guidance))
            request = ModelRequest(
                messages=(
                    system_message(self._render_system_prompt()),
                    *request_history,
                    *turn_guidance,
                    *observer_guidance,
                ),
                tools=snapshot.openai_tools(),
            )
            reply = (
                self._model.complete(request)
                if self._model_request_executor is None
                else self._model_request_executor.complete(request)
            )
            if reply.finish_reason == "length":
                raise IncompleteModelReplyError("模型输出达到 token 上限，回答不完整")
            if reply.finish_reason == "content_filter":
                raise AgentRunError("模型回答被内容过滤器拦截")

            assistant = reply.message
            self._history.append(assistant)
            if not assistant.tool_calls:
                if assistant.content is None:
                    raise AgentRunError("模型已停止，但没有返回最终文本或工具调用")
                stop_hook = await self._hooks.run_stop(self._history, stop_hook_active)
                if stop_hook.force_continue is not None:
                    self._history.extend((*stop_hook.additional_context, stop_hook.force_continue))
                    stop_hook_active = True
                    continue
                return self._complete(assistant.content, turn)

            results: list[ToolResult] = []
            deferred_context: list[ChatMessage] = []
            stopped_result_index: int | None = None
            for call in assistant.tool_calls:
                if stopped_result_index is not None:
                    result = tool_error(
                        "hook_stopped_continuation", "PostToolUse 已要求停止，当前调用未执行"
                    )
                else:
                    execution = await self._execute_tool(call, context, snapshot)
                    result = execution.result
                    deferred_context.extend(execution.additional_context)
                    if execution.prevent_continuation:
                        stopped_result_index = len(results)
                results.append(result)

            if self._tool_result_processor is not None:
                try:
                    outcome = self._tool_result_processor.compact_tool_results(tuple(results))
                    processed = outcome.results
                    if not isinstance(processed, tuple) or len(processed) != len(results):
                        raise ValueError("工具结果处理器返回了错误数量")
                    results = list(processed)
                except Exception:  # noqa: BLE001
                    results = [
                        tool_error("tool_result_processing_error", "工具结果处理失败")
                        for _ in results
                    ]

            for index, call in enumerate(assistant.tool_calls):
                if index >= len(results):
                    raise AgentRunError("工具执行没有产生配对结果")
                self._history.append(tool_message(results[index].content, call.id))
            if self._tool_round_observer is not None:
                # 等所有 tool result 都配对写入后再计数，观察器不会看到半轮状态。
                self._tool_round_observer.record_tool_round(
                    tuple(call.name for call in assistant.tool_calls)
                )
            self._history.extend(deferred_context)
            if stopped_result_index is not None:
                return self._complete(results[stopped_result_index].content, turn)

        raise AgentLimitError(f"Agent 已达到最大模型调用轮数 max_turns={self._max_turns}")

    def _render_system_prompt(self) -> str:
        """读取动态 Provider，并拒绝空值，避免悄悄回退到过期 Prompt。"""
        if self._system_prompt_provider is None:
            return self._system_prompt
        rendered = self._system_prompt_provider.render()
        if not isinstance(rendered, str) or not rendered.strip():
            raise AgentRunError("动态 system prompt 必须是非空字符串")
        return rendered

    async def _execute_tool(
        self, call: ToolCall, context: ToolContext, tools: ToolRegistry
    ) -> ToolExecution:
        """执行固定链路：prepare -> Pre -> permission -> handler -> Post。"""
        try:
            prepared = tools.prepare(call)
        except Exception:  # noqa: BLE001
            return ToolExecution(tool_error("tool_preparation_error", "工具准备失败"))
        if prepared.error is not None:
            return ToolExecution(prepared.error)
        try:
            pre_hook = await self._hooks.run_pre_tool(prepared)
        except HookContractError:
            return ToolExecution(
                tool_error("hook_contract_error", "PreToolUse Hook 返回了非法更新")
            )
        except Exception:  # noqa: BLE001
            return ToolExecution(tool_error("hook_execution_error", "PreToolUse Hook 执行失败"))

        effective = pre_hook.updated_input or prepared
        if pre_hook.blocking_error is not None:
            return ToolExecution(pre_hook.blocking_error, pre_hook.additional_context)
        permission_error = self._check_permission(effective, context, pre_hook)
        if permission_error is not None:
            return ToolExecution(permission_error, pre_hook.additional_context)

        result = tools.invoke(effective, context)
        try:
            post_hook = await self._hooks.run_post_tool(effective, result)
        except Exception:  # noqa: BLE001
            return ToolExecution(
                tool_error("hook_execution_error", "PostToolUse Hook 执行失败"),
                pre_hook.additional_context,
            )
        return ToolExecution(
            post_hook.updated_output or result,
            pre_hook.additional_context + post_hook.additional_context,
            post_hook.prevent_continuation,
        )

    def _check_permission(
        self, prepared: PreparedToolCall, context: ToolContext, pre_hook: HookResult
    ) -> ToolResult | None:
        """把 Hook 建议交给第三章权限策略；Hook allow 不能绕过系统 deny。"""
        if self._permission_policy is not None:
            recommendations: tuple[PermissionDecision, ...] = ()
            if pre_hook.permission_behavior != "passthrough":
                recommendations = (
                    PermissionDecision(
                        pre_hook.permission_behavior,
                        f"PreToolUse Hook 建议 {pre_hook.permission_behavior}",
                        "pre-tool-hook",
                    ),
                )
            try:
                decision = self._permission_policy.decide(
                    PermissionRequest(prepared, context, recommendations)
                )
                return None if decision.is_allowed else decision.to_tool_result()
            except Exception:  # noqa: BLE001
                return tool_error("permission_evaluation_error", "权限评估失败")
        if self._authorizer is not None:
            try:
                authorization = self._authorizer.authorize(prepared, context)
                if not authorization.reason.strip():
                    raise ValueError("工具授权结果必须说明原因")
                return (
                    None
                    if authorization.allowed
                    else tool_error("permission_denied", authorization.reason)
                )
            except Exception:  # noqa: BLE001
                return tool_error("permission_denied", "工具授权过程发生异常，已按默认拒绝处理")
        return None

    def _complete(self, final_text: str, turns: int) -> RunResult:
        """完成前再次检查消息配对，并返回与内部列表隔离的快照。"""
        validate_tool_pairing(self._history)
        if self._turn_lifecycle is not None:
            self._turn_lifecycle.complete(tuple(self._history))
        return RunResult(final_text, tuple(self._history), turns)
