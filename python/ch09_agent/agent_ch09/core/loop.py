"""带 Hook 生命周期和第九章长期记忆的 Agent 核心循环。

Java 角度：这是应用服务。它按照固定顺序调用模型、Hook、权限策略和工具注册表，
但不负责创建这些依赖。第四章最重要的约束是：无论 Hook 阻断、异常还是主动停止，
每个 `tool_call_id` 都必须得到且只得到一条 tool 消息。

这是什么：Agent 的核心编排逻辑，管理模型-工具循环的完整生命周期
Java 类比：类似 @Service class AgentService，依赖注入多个协作组件
为什么需要：实现"用户输入→模型思考→工具执行→最终答案"的完整流程
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
from .model import ModelClient, ModelRequest
from .permissions import PermissionDecision, PermissionPolicy, PermissionRequest
from .tools import PreparedToolCall, ToolContext, ToolRegistry, ToolResult, tool_error


# ==================== 异常定义 ====================
# Java 对照：这些类似自定义业务异常，让上层能精确识别失败原因

class AgentRunError(Exception):
    """Agent 执行过程中的领域错误。

    这是什么：Agent 运行时的基础异常类
    Java 类比：类似自定义的 BusinessException 基类
    为什么需要：区分业务错误和系统错误（如 IOException），让调用方能针对性处理
    """


class AgentLimitError(AgentRunError):
    """达到最大模型调用轮数。

    这是什么：Agent 循环超过限制次数的专用异常
    Java 类比：类似 TooManyRequestsException
    为什么需要：防止模型陷入工具调用死循环，保护成本和性能
    """


class IncompleteModelReplyError(AgentRunError):
    """模型输出因 token 限制被截断。

    这是什么：模型回复不完整的异常
    Java 类比：类似 IncompleteDataException
    为什么需要：避免把半截回答当成完整结果返回给用户
    """


# ==================== 旧章节兼容授权 ====================

@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """旧章节兼容授权结果：是否允许，以及给模型看的原因。

    这是什么：第一、二章使用的简单授权结果
    Java 类比：类似 record AuthorizationDecision(boolean allowed, String reason)
    为什么需要：向后兼容第一、二章的授权接口

    参数：
        allowed: True 表示可以执行工具；False 表示只生成拒绝结果
        reason: 给人和模型看的原因，拒绝时尤其重要
    """
    allowed: bool  # 是否授权执行
    reason: str    # 授权或拒绝的原因说明


class ToolAuthorizer(Protocol):
    """旧章节兼容授权接口，类似 Java 中的鉴权 Service。

    这是什么：定义授权器的契约
    Java 类比：interface ToolAuthorizer { Decision authorize(...); }
    为什么需要：让核心循环不依赖具体授权实现，测试时可以用 Fake 替换
    """
    def authorize(
        self, prepared: PreparedToolCall, context: ToolContext
    ) -> ToolAuthorizationDecision:
        """判断某个工具调用是否被允许执行。

        参数：
            prepared: 已校验的工具调用（包含工具名、参数）
            context: 运行环境（工作目录、用户身份）

        返回：
            ToolAuthorizationDecision: 包含是否允许和原因
        """
        ...


# ==================== 生命周期扩展点 ====================

class ToolRoundObserver(Protocol):
    """工具轮观察器接口，类似 Java 中应用服务依赖的扩展 interface。

    这是什么：观察工具执行轮次的接口
    Java 类比：interface ToolRoundObserver { ... }
    为什么需要：让 TODO 跟踪器等组件能在每轮前注入临时指导
    """

    def before_model(self) -> tuple[ChatMessage, ...]:
        """返回只用于下一次模型请求的临时指导，不进入正式历史。

        这是什么：提供临时上下文的钩子方法
        Java 类比：类似 List<Message> provideTemporaryContext()
        为什么需要：在不污染历史的情况下传递临时信息
        """

    def record_tool_round(self, tool_names: tuple[str, ...]) -> None:
        """整轮工具结果全部落盘后，记录本轮调用过的工具名。

        这是什么：记录工具调用的回调方法
        Java 类比：类似 void onToolRoundComplete(List<String> toolNames)
        为什么需要：让观察器跟踪工具使用情况
        """


class RequestHistoryProcessor(Protocol):
    """请求发给模型前的临时历史处理器。

    这是什么：历史消息的预处理接口
    Java 类比：interface HistoryProcessor { List<Message> process(...); }
    为什么需要：支持上下文压缩等功能，减少 token 消耗
    """

    def prepare(self, history: tuple[ChatMessage, ...]) -> tuple[ChatMessage, ...]:
        """处理历史消息，返回处理后的版本。

        参数：
            history: 原始历史消息

        返回：
            tuple[ChatMessage, ...]: 处理后的历史消息
        """
        ...


class ToolResultProcessor(Protocol):
    """整批工具结果回填 canonical history 前的处理器。

    这是什么：工具结果的批量处理接口
    Java 类比：interface ToolResultProcessor { ProcessedResults process(...); }
    为什么需要：支持工具结果压缩，避免历史过长
    """

    def compact_tool_results(self, results: tuple[ToolResult, ...]) -> "ProcessedToolResults":
        """压缩工具结果。

        参数：
            results: 原始工具结果

        返回：
            ProcessedToolResults: 处理后的结果对象
        """
        ...


class TurnLifecycle(Protocol):
    """一轮 Agent 的生命周期边界，类似 Java 的请求拦截器链。

    这是什么：管理 Agent 一轮执行的生命周期接口
    Java 类比：interface TurnLifecycle extends RequestInterceptor { ... }
    为什么需要：支持长期记忆等功能，管理轮次级别的状态
    """

    def begin_turn(self, query: str) -> None:
        """轮次开始时调用。

        参数：
            query: 用户输入的问题
        """
        ...

    def before_model(self) -> tuple[ChatMessage, ...]:
        """模型调用前返回临时上下文。

        返回：
            tuple[ChatMessage, ...]: 临时消息列表
        """
        ...

    def complete(self, history: tuple[ChatMessage, ...]) -> None:
        """轮次完成时调用，传入完整历史。

        参数：
            history: 完整的消息历史
        """
        ...


class ProcessedToolResults(Protocol):
    """结果处理器只需要公开不可变的 ``results`` 字段。

    这是什么：工具结果处理的输出接口
    Java 类比：interface ProcessedToolResults { List<ToolResult> getResults(); }
    为什么需要：定义结果处理器的返回契约
    """

    @property
    def results(self) -> tuple[ToolResult, ...]:
        """返回处理后的工具结果列表。"""
        ...


# ==================== 运行结果 ====================

@dataclass(frozen=True, slots=True)
class RunResult:
    """一次 Agent 运行结束后返回给调用方的不可变结果。

    这是什么：AgentRunner.run() 的返回值
    Java 类比：record RunResult(String finalText, List<ChatMessage> history, int turns)
    为什么需要：封装三个关键信息，避免用元组或字典传递数据

    参数：
        final_text: 模型最后一次返回的普通文本（用户最终看到的答案）
        history: 完整对话副本（不可变 tuple），用于测试和审计
        turns: 实际调用模型的次数，从 1 开始（用于计费和性能分析）
    """
    final_text: str                      # 最终答案文本
    history: tuple[ChatMessage, ...]     # tuple = 不可变列表
    turns: int                           # 循环轮数计数


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """一次工具链路的内部结果，不暴露给 AgentRunner 外部。

    这是什么：工具执行的内部数据传输对象
    Java 类比：类似 record ToolExecution(ToolResult result, List<Message> additionalContext, boolean preventContinuation)
    为什么需要：封装工具执行的完整结果，包括副作用和控制流信息

    参数：
        result: 工具执行结果
        additional_context: Hook 可能添加的额外上下文消息
        prevent_continuation: 是否阻止继续执行后续工具调用
    """

    result: ToolResult
    additional_context: tuple[ChatMessage, ...] = ()
    prevent_continuation: bool = False


# ==================== 核心 Agent 循环 ====================

class AgentRunner:
    """在确定位置发布 Hook 事件的单会话状态机。

    这是全章最重要的类。可以把它看成一个 Service：它只负责编排，
    不负责 HTTP 请求细节，也不负责 PowerShell 进程细节。

    这是什么：Agent 的核心编排器，管理完整的模型-工具循环
    Java 类比：类似 @Service class AgentService，依赖注入 ModelClient 和 ToolRegistry
    为什么需要：实现"模型-工具循环"的通用逻辑，让不同模型供应商和工具能插拔替换

    核心流程：
        1. 接收用户问题
        2. 循环调用模型（最多 max_turns 次）
        3. 模型返回文本 → 结束
        4. 模型要求工具 → 执行工具 → 继续循环
    """

    def __init__(
        self,
        model: ModelClient,
        tools: ToolRegistry,
        system_prompt: str,
        workspace: str,
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
        """初始化 Agent 运行器，注入所有依赖。

        Java 对照：这是构造器注入，所有依赖从外部传入，类似 Spring 的 @Autowired

        参数：
            model: 模型客户端接口（可以是 DeepSeek、OpenAI 或测试 Fake）
            tools: 工具注册表（保存所有可用工具的映射表）
            system_prompt: 系统提示词（定义 Agent 的身份和规则）
            workspace: 工具允许操作的工作目录
            max_turns: 最大循环次数（防死循环）
            identity: 调用者身份（用于权限控制）
            authorizer: 旧章节兼容授权器（可选）
            permission_policy: 权限策略（第三章起使用）
            hooks: Hook 注册表（第四章起支持）
            tool_round_observer: 工具轮观察器（如 TODO 跟踪器）
            history_processor: 历史处理器（如上下文压缩）
            tool_result_processor: 工具结果处理器（如结果压缩）
            turn_lifecycle: 轮次生命周期管理器（如长期记忆）

        异常：
            ValueError: 参数校验失败
        """
        # 参数校验：在构造时就失败，而不是运行时才发现配置错误
        if max_turns <= 0:
            raise ValueError("max_turns 必须是正整数")
        if not identity.strip():
            raise ValueError("identity 不能为空")
        if not system_prompt.strip():
            raise ValueError("system_prompt 不能为空")

        # 保存依赖：下划线前缀 _ 表示私有字段，类似 Java 的 private final
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        self._workspace = str(Path(workspace).resolve())
        self._max_turns = max_turns
        self._identity = identity
        self._authorizer = authorizer
        # 如果有 hooks 但没有 policy，创建默认空策略（第四章引入）
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
        self._history: list[ChatMessage] = []  # 可变会话历史

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        """返回对话历史的不可变副本。

        这是什么：只读属性，外部可以读取但不能修改
        Java 类比：public List<ChatMessage> getHistory() { return List.copyOf(history); }
        为什么需要：防止外部代码直接修改 Agent 内部状态

        返回：
            tuple[ChatMessage, ...]: 不可变消息序列
        """
        return tuple(self._history)

    def run(self, prompt: str) -> RunResult:
        """执行一次完整的 Agent 任务，直到模型返回最终答案或达到轮数上限。

        这是什么：Agent 的主入口方法（同步接口）
        Java 类比：public RunResult execute(String userPrompt) throws AgentRunError
        为什么需要：封装完整的"问题→循环→答案"流程，内部使用 asyncio 支持异步 Hook

        参数：
            prompt: 用户输入的自然语言问题

        返回：
            RunResult: 包含最终答案、完整历史和轮数统计

        异常：
            AgentRunError: 当前线程已有事件循环或其他运行错误
        """
        try:
            asyncio.get_running_loop()  # 检查是否已有运行中的事件循环
        except RuntimeError:
            # 没有事件循环，创建新的并运行
            return asyncio.run(self._run(prompt))
        # 已有事件循环，避免嵌套冲突
        raise AgentRunError("当前线程已有 asyncio 事件循环，请在同步入口外调用 AgentRunner.run")

    async def _run(self, prompt: str) -> RunResult:
        """异步运行逻辑，支持异步 Hook 和同步 Hook 的统一等待。

        这是什么：Agent 的核心循环实现
        Java 类比：类似 private RunResult executeInternal(String prompt)
        为什么需要：实现完整的模型-工具循环，处理 Hook 和生命周期事件

        工作流程：
            1. 触发 UserPromptSubmit Hook
            2. 开始轮次生命周期
            3. 循环：调用模型 → 执行工具 → 记录观察
            4. 模型返回文本时结束，触发 Stop Hook
            5. 调用生命周期完成钩子
        """
        # 第一步：创建用户消息并触发 Hook
        submitted = user_message(prompt)
        prompt_hook = await self._hooks.run_user_prompt(submitted)
        self._history.extend((submitted, *prompt_hook.additional_context))

        # 第二步：通知生命周期管理器（如长期记忆）轮次开始
        if self._turn_lifecycle is not None:
            # 长期记忆属于辅助能力。MemorySession 会自行记录中文错误，不应让
            # 记忆文件损坏或 side-query 失败挡住用户的主请求
            self._turn_lifecycle.begin_turn(prompt)

        context = ToolContext(self._workspace, self._identity)
        stop_hook_active = False  # 跟踪 Stop Hook 是否已被激活

        # 第三步：模型-工具循环，最多执行 max_turns 轮
        for turn in range(1, self._max_turns + 1):
            # 确保消息历史中工具调用和结果正确配对
            validate_tool_pairing(self._history)
            snapshot = self._tools.snapshot()  # 工具快照，避免并发修改

            # 收集临时指导消息（不写入正式历史）
            observer_guidance = (
                ()
                if self._tool_round_observer is None
                else self._tool_round_observer.before_model()
            )

            # 历史处理（如上下文压缩）
            request_history = (
                tuple(self._history)
                if self._history_processor is None
                else self._history_processor.prepare(tuple(self._history))
            )
            validate_tool_pairing(list(request_history))

            # 轮次级别的临时指导（如长期记忆提示）
            turn_guidance = (
                () if self._turn_lifecycle is None else self._turn_lifecycle.before_model()
            )
            validate_tool_pairing(list(turn_guidance))

            # 构建模型请求：系统提示词 + 历史 + 临时指导
            request = ModelRequest(
                messages=(
                    system_message(self._system_prompt),
                    *request_history,
                    *turn_guidance,
                    *observer_guidance,
                ),
                tools=snapshot.openai_tools(),
            )

            # 调用模型
            reply = self._model.complete(request)

            # 检查模型回复的完成状态
            if reply.finish_reason == "length":
                raise IncompleteModelReplyError("模型输出达到 token 上限，回答不完整")
            if reply.finish_reason == "content_filter":
                raise AgentRunError("模型回答被内容过滤器拦截")

            # 将模型消息加入历史
            assistant = reply.message
            self._history.append(assistant)

            # 情况 1：模型返回文本（无工具调用），任务完成
            if not assistant.tool_calls:
                if assistant.content is None:
                    raise AgentRunError("模型已停止，但没有返回最终文本或工具调用")

                # 触发 Stop Hook，可能强制继续循环
                stop_hook = await self._hooks.run_stop(self._history, stop_hook_active)
                if stop_hook.force_continue is not None:
                    self._history.extend((*stop_hook.additional_context, stop_hook.force_continue))
                    stop_hook_active = True
                    continue

                # 正常结束，返回结果
                return self._complete(assistant.content, turn)

            # 情况 2：模型请求工具调用，逐个执行
            results: list[ToolResult] = []
            deferred_context: list[ChatMessage] = []
            stopped_result_index: int | None = None

            for call in assistant.tool_calls:
                if stopped_result_index is not None:
                    # 前面的工具 Hook 要求停止，后续工具不执行
                    result = tool_error(
                        "hook_stopped_continuation", "PostToolUse 已要求停止，当前调用未执行"
                    )
                else:
                    # 执行工具链路：prepare -> PreHook -> permission -> handler -> PostHook
                    execution = await self._execute_tool(call, context, snapshot)
                    result = execution.result
                    deferred_context.extend(execution.additional_context)
                    if execution.prevent_continuation:
                        stopped_result_index = len(results)
                results.append(result)

            # 工具结果压缩（如果配置了处理器）
            if self._tool_result_processor is not None:
                try:
                    outcome = self._tool_result_processor.compact_tool_results(tuple(results))
                    processed = outcome.results
                    if not isinstance(processed, tuple) or len(processed) != len(results):
                        raise ValueError("工具结果处理器返回了错误数量")
                    results = list(processed)
                except Exception:  # noqa: BLE001
                    # 处理失败时，将所有结果替换为错误
                    results = [
                        tool_error("tool_result_processing_error", "工具结果处理失败")
                        for _ in results
                    ]

            # 将工具结果写回历史，确保每个 call.id 都有配对的 tool 消息
            for index, call in enumerate(assistant.tool_calls):
                if index >= len(results):
                    raise AgentRunError("工具执行没有产生配对结果")
                self._history.append(tool_message(results[index].content, call.id))

            # 通知观察器本轮工具调用完成
            if self._tool_round_observer is not None:
                # 等所有 tool result 都配对写入后再计数，观察器不会看到半轮状态
                self._tool_round_observer.record_tool_round(
                    tuple(call.name for call in assistant.tool_calls)
                )

            # 添加 Hook 延迟的上下文消息
            self._history.extend(deferred_context)

            # 如果 Hook 要求停止，立即返回
            if stopped_result_index is not None:
                return self._complete(results[stopped_result_index].content, turn)

        # 循环用完仍未得到最终文本，说明模型一直在调用工具
        raise AgentLimitError(f"Agent 已达到最大模型调用轮数 max_turns={self._max_turns}")

    async def _execute_tool(
        self, call: ToolCall, context: ToolContext, tools: ToolRegistry
    ) -> ToolExecution:
        """执行固定链路：prepare -> PreHook -> permission -> handler -> PostHook。

        这是什么：单个工具调用的完整执行链路
        Java 类比：类似 private ToolExecution executeToolChain(ToolCall call)
        为什么需要：确保每个工具调用都经过完整的准备、鉴权、执行、后处理流程

        执行顺序（严格固定）：
            1. prepare: 查找工具定义、解析 JSON、校验参数
            2. PreToolUse Hook: 可以修改输入或阻止执行
            3. permission check: 权限策略决定是否允许
            4. handler: 执行工具的实际逻辑
            5. PostToolUse Hook: 可以修改输出或阻止继续

        参数：
            call: 模型的工具调用请求
            context: 工具执行上下文
            tools: 工具注册表快照

        返回：
            ToolExecution: 包含结果、额外上下文和停止标志
        """
        # 第一步：准备工具调用（查找、解析、校验）
        try:
            prepared = tools.prepare(call)
        except Exception:  # noqa: BLE001
            return ToolExecution(tool_error("tool_preparation_error", "工具准备失败"))

        if prepared.error is not None:  # 准备阶段已失败（未知工具、JSON 错误等）
            return ToolExecution(prepared.error)

        # 第二步：触发 PreToolUse Hook
        try:
            pre_hook = await self._hooks.run_pre_tool(prepared)
        except HookContractError:
            return ToolExecution(
                tool_error("hook_contract_error", "PreToolUse Hook 返回了非法更新")
            )
        except Exception:  # noqa: BLE001
            return ToolExecution(tool_error("hook_execution_error", "PreToolUse Hook 执行失败"))

        # Hook 可能更新了输入参数
        effective = pre_hook.updated_input or prepared

        # Hook 可能直接阻止执行
        if pre_hook.blocking_error is not None:
            return ToolExecution(pre_hook.blocking_error, pre_hook.additional_context)

        # 第三步：权限检查
        permission_error = self._check_permission(effective, context, pre_hook)
        if permission_error is not None:
            return ToolExecution(permission_error, pre_hook.additional_context)

        # 第四步：执行工具处理器
        result = tools.invoke(effective, context)

        # 第五步：触发 PostToolUse Hook
        try:
            post_hook = await self._hooks.run_post_tool(effective, result)
        except Exception:  # noqa: BLE001
            return ToolExecution(
                tool_error("hook_execution_error", "PostToolUse Hook 执行失败"),
                pre_hook.additional_context,
            )

        # 返回最终结果（Hook 可能修改了输出或要求停止继续）
        return ToolExecution(
            post_hook.updated_output or result,
            pre_hook.additional_context + post_hook.additional_context,
            post_hook.prevent_continuation,
        )

    def _check_permission(
        self, prepared: PreparedToolCall, context: ToolContext, pre_hook: HookResult
    ) -> ToolResult | None:
        """检查工具调用权限，优先使用第三章权限策略，回退到旧授权器。

        这是什么：权限检查的统一入口
        Java 类比：类似 private ToolResult checkPermission(PreparedToolCall call)
        为什么需要：集中权限逻辑，支持新旧两种授权方式

        规则：Hook allow 建议不能绕过系统 deny 规则

        参数：
            prepared: 准备好的工具调用
            context: 执行上下文
            pre_hook: PreToolUse Hook 的结果（可能包含权限建议）

        返回：
            ToolResult | None: 权限错误结果，或 None 表示允许执行
        """
        # 优先使用第三章权限策略（支持规则链和审计）
        if self._permission_policy is not None:
            recommendations: tuple[PermissionDecision, ...] = ()

            # 如果 Hook 给出了权限建议，传递给策略
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
                # 权限评估失败，默认拒绝（fail-closed 原则）
                return tool_error("permission_evaluation_error", "权限评估失败")

        # 回退到旧章节的简单授权器
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
                # 授权异常，默认拒绝（安全优先）
                return tool_error("permission_denied", "工具授权过程发生异常，已按默认拒绝处理")

        # 没有配置任何权限检查，直接允许
        return None

    def _complete(self, final_text: str, turns: int) -> RunResult:
        """完成任务，触发生命周期钩子并返回不可变结果。

        这是什么：任务完成的收尾方法
        Java 类比：类似 private RunResult finalize(String text, int turns)
        为什么需要：统一处理任务完成逻辑，确保生命周期正确结束

        参数：
            final_text: 模型的最终答案
            turns: 实际调用模型的轮数

        返回：
            RunResult: 不可变的运行结果
        """
        # 最后再次检查消息配对完整性
        validate_tool_pairing(self._history)

        # 通知生命周期管理器任务完成（如保存长期记忆）
        if self._turn_lifecycle is not None:
            self._turn_lifecycle.complete(tuple(self._history))

        # 返回与内部列表隔离的不可变快照
        return RunResult(final_text, tuple(self._history), turns)
