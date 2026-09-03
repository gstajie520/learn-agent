"""带 Hook 生命周期和运行时事件的 Agent 核心循环。

这是什么：第 19 章核心类，在第 4 章 Hook 基础上增加运行时事件支持
Java 角度：这是应用服务。它按照固定顺序调用模型、Hook、权限策略和工具注册表，
        但不负责创建这些依赖。第 19 章的核心约束是：运行时事件在安全点注入，
        每个事件必须 ack 确认，失败时保留租约防止丢失
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .events import RuntimeEvent, runtime_event_message
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


class _ExecutionScope:
    """一次 Agent.run 的内部身份对象，只用于 Worktree scope 映射。"""


def _path_inside(parent: Path, child: Path) -> bool:
    """使用 commonpath 判断 child 是否位于 parent 内。"""
    try:
        return parent == child or parent in child.parents
    except (OSError, ValueError):
        return False


class AgentRunError(Exception):
    """Agent 执行过程中的领域错误。"""


class AgentLimitError(AgentRunError):
    """达到最大模型调用轮数。"""


class IncompleteModelReplyError(AgentRunError):
    """模型输出因 token 限制被截断。"""


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """旧章节兼容授权结果：是否允许，以及给模型看的原因。"""

    allowed: bool
    reason: str


class ToolAuthorizer(Protocol):
    """旧章节兼容授权接口，类似 Java 中的鉴权 Service。"""

    def authorize(
        self, prepared: PreparedToolCall, context: ToolContext
    ) -> ToolAuthorizationDecision: ...


class ToolRoundObserver(Protocol):
    """工具轮观察器接口，类似 Java 中应用服务依赖的扩展 interface。"""

    def before_model(self) -> tuple[ChatMessage, ...]:
        """返回只用于下一次模型请求的临时指导，不进入正式历史。"""

    def record_tool_round(self, tool_names: tuple[str, ...]) -> None:
        """整轮工具结果全部落盘后，记录本轮调用过的工具名。"""


class RequestHistoryProcessor(Protocol):
    """请求发给模型前的临时历史处理器。"""

    def prepare(self, history: tuple[ChatMessage, ...]) -> tuple[ChatMessage, ...]: ...


class ToolResultProcessor(Protocol):
    """整批工具结果回填 canonical history 前的处理器。"""

    def compact_tool_results(self, results: tuple[ToolResult, ...]) -> "ProcessedToolResults": ...


class TurnLifecycle(Protocol):
    """一轮 Agent 的生命周期边界，类似 Java 的请求拦截器链。"""

    def begin_turn(self, query: str) -> None: ...

    def before_model(self) -> tuple[ChatMessage, ...]: ...

    def complete(self, history: tuple[ChatMessage, ...]) -> None: ...


class SystemPromptProvider(Protocol):
    """每轮模型请求前渲染 system prompt，类似 Java ``Supplier<String>``。"""

    def render(self) -> str: ...


class ModelRequestExecutor(Protocol):
    """一次逻辑模型请求执行器，内部可以重试但不能重进 Agent Loop。"""

    def begin_turn(self) -> None: ...

    def complete(self, request: ModelRequest) -> ModelReply: ...


class ProcessedToolResults(Protocol):
    """结果处理器只需要公开不可变的 ``results`` 字段。"""

    @property
    def results(self) -> tuple[ToolResult, ...]: ...


class ToolDispatcher(Protocol):
    """权限通过后决定工具是否提交后台。"""

    def dispatch(
        self, prepared: PreparedToolCall, context: ToolContext, tools: ToolRegistry
    ) -> ToolResult | None: ...


class ToolContextProvider(Protocol):
    """每次工具调用前解析可信上下文，类似 Java 请求拦截器。"""

    @property
    def workspace_root(self) -> str:
        """返回 Provider 允许的 workspace 信任根。"""

    def resolve(self, context: ToolContext) -> ToolContext:
        """返回当前工具真正使用的上下文。"""


class RuntimeEventPump(Protocol):
    """后台事件泵接口。

    这是什么：事件队列的抽象接口，AgentRunner 通过它获取事件
    Java 类比：interface EventPump { boolean hasWork(); List<Event> drain(); void ack(Event); }
    为什么需要：让 AgentRunner 不依赖具体实现（EventInbox、TaskStore），方便测试和替换
    """

    @property
    def has_pending_work(self) -> bool:
        """是否有待处理的事件（包括未 ack 的）。

        Java 类比：类似 !queue.isEmpty()
        为什么需要：让主循环知道是否需要等待事件，避免过早返回
        """
        ...

    def drain_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """非阻塞取事件，立即返回当前队列中的事件。

        Java 类比：List<Event> drain(int limit)
        为什么需要：循环开始前轮询事件，不阻塞主流程
        """
        ...

    def wait_for_events(self, limit: int | None = None) -> tuple[RuntimeEvent, ...]:
        """阻塞等待事件，直到至少有一条事件或超时。

        Java 类比：List<Event> take(int limit, long timeout)
        为什么需要：确认有待处理工作时，阻塞等待事件到达
        """
        ...

    def acknowledge_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """确认事件已处理完成，从持久化存储中删除。

        Java 类比：void ack(List<Event> events)
        为什么需要：防止重启后重复处理事件，保证至少一次语义
        """
        ...

    def release_events(self, events: tuple[RuntimeEvent, ...]) -> None:
        """释放事件租约，让事件重新进入 ready 状态。

        Java 类比：void release(List<Event> events)
        为什么需要：处理失败时释放租约，让其他 worker 能重新处理
        """
        ...


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
        tool_dispatcher: ToolDispatcher | None = None,
        event_pump: RuntimeEventPump | None = None,
        resources: tuple[object, ...] = (),
        tool_context_provider: ToolContextProvider | None = None,
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
        self._tool_dispatcher = tool_dispatcher
        self._event_pump = event_pump
        self._resources = resources
        self._tool_context_provider = tool_context_provider
        self._seen_event_ids: set[str] = set()  # 已处理事件的 ID 集合，用于去重
        self._deferred_runtime_events: list[RuntimeEvent] = []  # 延迟处理的用户上下文事件
        # 已写入 history 但 ack 失败的事件。下次 run_events 只重试 ack，不重复调用模型
        self._pending_event_acks: dict[str, tuple[RuntimeEvent, RunResult]] = {}
        self._history: list[ChatMessage] = []  # 对话历史（不包含 system prompt）

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        """返回不可变历史副本，外部不能修改下一轮模型请求。"""
        return tuple(self._history)

    def run(
        self,
        prompt: str,
        *,
        idempotency_key: str | None = None,
        claim_token: str | None = None,
        runtime_event: RuntimeEvent | None = None,
    ) -> RunResult:
        """同步入口；内部用 asyncio 顺序等待同步或异步 Hook。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            if idempotency_key is not None and not idempotency_key.strip():
                raise ValueError("idempotency_key 不能为空")
            return asyncio.run(self._run(prompt, runtime_event, idempotency_key, claim_token))
        raise AgentRunError("当前线程已有 asyncio 事件循环，请在同步入口外调用 AgentRunner.run")

    def run_events(self) -> RunResult | None:
        """消费一条运行时事件；事件回合完成后才 ack，ack 失败只重试确认。

        这是什么：事件驱动入口，主循环调用此方法处理一条后台事件
        Java 类比：public RunResult processNextEvent()，从队列取一条事件处理
        为什么需要：后台任务完成后通知主循环，而不是直接修改历史

        返回：
            RunResult: 事件处理完成后的结果
            None: 当前没有待处理事件

        注意：
            - 优先重试 ack 失败的事件（不重复调用模型）
            - ack 失败时保留租约，防止事件丢失
            - 处理失败时释放租约，让其他 worker 能重新处理
        """
        # 第一步：检查是否有 ack 失败的事件，优先重试确认
        if self._pending_event_acks:
            event, result = next(iter(self._pending_event_acks.values()))
            if self._event_pump is not None:
                self._event_pump.acknowledge_events((event,))  # 重试 ack
            self._pending_event_acks.pop(event.event_id, None)  # 确认成功后移除
            return result
        # 第二步：从延迟队列或 event_pump 获取下一条事件
        next_event: RuntimeEvent | None = (
            self._deferred_runtime_events.pop(0) if self._deferred_runtime_events else None
        )
        if next_event is None and self._event_pump is not None:
            drained = self._event_pump.drain_events(1)  # 非阻塞取一条事件
            next_event = drained[0] if drained else None
        if next_event is None:  # 没有事件时直接返回 None
            return None
        event = next_event
        # 第三步：处理事件，确保 ack 机制正确执行
        try:
            asyncio.get_running_loop()  # 检查是否在异步上下文中
        except RuntimeError:  # 不在异步上下文中，创建新的事件循环
            try:
                # 调用 _run 处理事件，包装成 user 消息注入循环
                result = asyncio.run(
                    self._run(
                        getattr(event, "prompt", "处理运行时事件"), event, event.idempotency_key
                    )
                )
                # 第四步：处理成功后 ack 确认
                if self._event_pump is not None:
                    try:
                        self._event_pump.acknowledge_events((event,))
                    except Exception:
                        # history 和模型调用已经完成，保留事件身份，下一轮只补 ack
                        self._pending_event_acks[event.event_id] = (event, result)
                        raise  # 重新抛出异常，让调用方知道 ack 失败
                return result
            except Exception:
                # ack 失败时事件仍处于 processing，必须保留租约；否则 release 会让下一轮
                # 看到 ready 状态，而补 ack 又找不到原来的 processing 文件。
                if self._event_pump is not None and event.event_id not in self._pending_event_acks:
                    self._event_pump.release_events((event,))  # 处理失败时释放租约
                raise
        raise AgentRunError("当前线程已有 asyncio 事件循环，不能调用 AgentRunner.run_events")

    def close(self) -> None:
        """按逆序关闭外部资源。"""
        for resource in reversed(self._resources):
            close = getattr(resource, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001, S112
                    continue

    async def _run(
        self,
        prompt: str,
        runtime_event: RuntimeEvent | None = None,
        idempotency_key: str | None = None,
        claim_token: str | None = None,
    ) -> RunResult:
        # 事件回合已经由 runtime_event_message 作为 canonical user 消息进入历史，跳过普通用户 Hook。
        if runtime_event is None:
            submitted = user_message(prompt)
            prompt_hook = await self._hooks.run_user_prompt(submitted)
            self._history.extend((submitted, *prompt_hook.additional_context))
        if runtime_event is not None:
            self._history.append(runtime_event_message(runtime_event))
        if self._turn_lifecycle is not None:
            # 长期记忆属于辅助能力。MemorySession 会自行记录中文错误，不应让
            # 记忆文件损坏或 side-query 失败挡住用户的主请求。
            self._turn_lifecycle.begin_turn(prompt)
        if self._model_request_executor is not None:
            self._model_request_executor.begin_turn()
        execution_scope = _ExecutionScope() if self._tool_context_provider is not None else None
        context = ToolContext(
            self._workspace,
            self._identity
            if runtime_event is None or runtime_event.context_identity is None
            else runtime_event.context_identity,
            runtime_event.idempotency_key if runtime_event is not None else idempotency_key,
            claim_token=claim_token,
            execution_scope=execution_scope,
        )
        stop_hook_active = False

        for turn in range(1, self._max_turns + 1):
            self._inject_runtime_events(False, allow_context_events=runtime_event is not None)
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
                if self._event_pump is not None and self._event_pump.has_pending_work:
                    self._inject_runtime_events(
                        True, allow_context_events=runtime_event is not None
                    )
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
            effective_context = self._resolve_tool_context(context)
        except Exception:  # noqa: BLE001
            return ToolExecution(tool_error("tool_context_error", "工具工作区上下文解析失败"))
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
        permission_error = self._check_permission(effective, effective_context, pre_hook)
        if permission_error is not None:
            return ToolExecution(permission_error, pre_hook.additional_context)

        result = None
        if self._tool_dispatcher is not None:
            try:
                result = self._tool_dispatcher.dispatch(effective, effective_context, tools)
            except Exception:  # noqa: BLE001
                result = tool_error("background_submission_error", "后台任务提交失败")
        if result is None:
            result = tools.invoke(effective, effective_context)
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

    def _resolve_tool_context(self, context: ToolContext) -> ToolContext:
        """解析工具工作区，并验证 Provider 没有篡改可信身份字段。"""
        provider = self._tool_context_provider
        if provider is None:
            return context
        resolved = provider.resolve(context)
        root = Path(provider.workspace_root).resolve(strict=True)
        workspace = Path(resolved.workspace).resolve(strict=True)
        if not _path_inside(root, workspace):
            raise ValueError("解析后的 workspace 越出 Provider 信任根")
        if resolved.identity != context.identity:
            raise ValueError("Provider 不得修改 identity")
        if resolved.idempotency_key != context.idempotency_key:
            raise ValueError("Provider 不得修改 idempotency_key")
        if resolved.execution_scope is not context.execution_scope:
            raise ValueError("Provider 不得替换 execution_scope")
        return resolved

    def _inject_runtime_events(self, wait_for_pending: bool, *, allow_context_events: bool) -> None:
        """批量取事件、去重，并作为普通 user 消息追加到历史。

        这是什么：事件注入方法，在安全点将事件包装成 user 消息加入历史
        Java 类比：void injectEvents(boolean waitForPending, boolean allowContext)
        为什么需要：后台事件不能直接修改历史，需要在消息配对完整后统一注入

        参数：
            wait_for_pending: 是否阻塞等待待处理事件（模型返回文本后设为 True）
            allow_context_events: 是否允许注入用户上下文事件（只在处理运行时事件回合时为 True）

        核心逻辑：
            1. 非阻塞取事件（drain），或阻塞等待（wait）
            2. 过滤用户上下文事件（context_identity != None）
            3. 通过 event_id 去重（防止重复处理）
            4. 包装成 user 消息追加到历史
        """
        if self._event_pump is None:  # 没有事件泵时直接返回
            return
        # 第一步：从 event_pump 取事件
        events = self._event_pump.drain_events()  # 非阻塞取所有就绪事件
        if not events and wait_for_pending and self._event_pump.has_pending_work:
            events = self._event_pump.wait_for_events()  # 阻塞等待至少一条事件
        # 第二步：过滤用户上下文事件
        injectable: list[RuntimeEvent] = []
        for event in events:
            # 用户上下文事件（context_identity != None）只能在该用户回合注入
            if event.context_identity is not None and not allow_context_events:
                self._deferred_runtime_events.append(event)  # 延迟到下次处理
            else:
                injectable.append(event)  # 系统事件或允许的用户上下文事件
        # 第三步：通过 event_id 去重
        fresh = [event for event in injectable if event.event_id not in self._seen_event_ids]
        self._seen_event_ids.update(event.event_id for event in fresh)  # 标记为已处理
        total = len(fresh)
        # 第四步：包装成 user 消息追加到历史
        self._history.extend(
            runtime_event_message(event, index, total) for index, event in enumerate(fresh)
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
