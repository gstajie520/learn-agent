"""带 Hook 生命周期的 Agent 核心循环。

这是什么：第四章到第六章的核心编排逻辑，集成了 Hook、权限策略和工具轮观察器
Java 类比：@Service class AgentRunner，依赖注入 ModelClient、ToolRegistry、HookRegistry、PermissionPolicy
为什么需要：在固定位置发布生命周期事件，让扩展逻辑能以声明式方式介入工具执行流程

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
from .model import ModelClient, ModelRequest
from .permissions import PermissionDecision, PermissionPolicy, PermissionRequest
from .tools import PreparedToolCall, ToolContext, ToolRegistry, ToolResult, tool_error


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


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """旧章节兼容授权结果：是否允许，以及给模型看的原因。

    这是什么：第一章授权器的返回值对象，第三章后被 PermissionPolicy 替代
    Java 类比：record ToolAuthorizationDecision(boolean allowed, String reason)
    为什么需要：保持向后兼容，允许同时使用旧授权器和新权限策略
    """

    allowed: bool  # 是否授权执行
    reason: str  # 授权或拒绝的原因说明


class ToolAuthorizer(Protocol):
    """旧章节兼容授权接口，类似 Java 中的鉴权 Service。

    这是什么：第一章定义的授权器协议
    Java 类比：interface ToolAuthorizer { Decision authorize(...); }
    为什么需要：第三章引入 PermissionPolicy 后保留此接口以兼容旧代码
    """

    def authorize(
        self, prepared: PreparedToolCall, context: ToolContext
    ) -> ToolAuthorizationDecision: ...


class ToolRoundObserver(Protocol):
    """工具轮观察器接口，类似 Java 中应用服务依赖的扩展 interface。

    这是什么：第六章引入的观察器协议，用于跟踪工具使用情况
    Java 类比：interface ToolRoundObserver { List<ChatMessage> beforeModel(); void recordToolRound(...); }
    为什么需要：让扩展功能（如 TodoTracker）能在每轮工具执行后收到通知，实现状态监控
    """

    def before_model(self) -> tuple[ChatMessage, ...]:
        """返回只用于下一次模型请求的临时指导，不进入正式历史。

        这是什么：在调用模型前注入临时系统消息
        Java 类比：类似 Spring Interceptor 的 preHandle
        为什么需要：允许观察器根据当前状态动态调整模型行为（如提醒更新计划）
        """

    def record_tool_round(self, tool_names: tuple[str, ...]) -> None:
        """整轮工具结果全部落盘后，记录本轮调用过的工具名。

        这是什么：工具轮结束后的回调通知
        Java 类比：类似 Spring 事件监听器的 @EventListener
        为什么需要：让观察器能统计工具使用情况，如连续多少轮未调用特定工具
        """


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次 Agent 运行结束后返回给调用方的不可变结果。

    这是什么：AgentRunner.run() 的返回值
    Java 类比：record RunResult(String finalText, List<ChatMessage> history, int turns)
    为什么需要：封装三个关键信息，避免用元组或字典传递数据
    """

    final_text: str  # 模型最后一次返回的普通文本（用户最终看到的答案）
    history: tuple[ChatMessage, ...]  # 完整对话副本（不可变 tuple），用于测试和审计
    turns: int  # 实际调用模型的次数，从 1 开始（用于计费和性能分析）


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """一次工具链路的内部结果，不暴露给 AgentRunner 外部。

    这是什么：工具执行流程的中间结果对象
    Java 类比：record ToolExecution(ToolResult result, List<ChatMessage> additionalContext, boolean preventContinuation)
    为什么需要：封装工具执行后的三种影响：结果本身、Hook 追加的上下文、是否停止继续执行
    """

    result: ToolResult  # 工具执行结果（成功或失败）
    additional_context: tuple[ChatMessage, ...] = ()  # Hook 注入的额外系统消息
    prevent_continuation: bool = False  # PostToolUse Hook 是否要求停止后续工具执行


class AgentRunner:
    """在确定位置发布 Hook 事件的单会话状态机。

    这是什么：Agent 的核心编排器，集成 Hook、权限、工具轮观察器
    Java 类比：@Service class AgentRunner，通过构造器注入所有依赖
    为什么需要：在固定的生命周期点发布事件，让扩展逻辑以声明式方式介入

    核心流程：
        1. 接收用户问题 → UserPromptSubmit Hook
        2. 循环调用模型（最多 max_turns 次）
        3. 模型返回文本 → Stop Hook（可选强制继续）
        4. 模型要求工具 → PreToolUse Hook → 权限检查 → 执行 → PostToolUse Hook
        5. 工具轮结束 → 通知 ToolRoundObserver
    """

    def __init__(
        self,
        model: ModelClient,  # 模型客户端接口（可以是 DeepSeek、OpenAI 或测试 Fake）
        tools: ToolRegistry,  # 工具注册表（保存所有可用工具的映射表）
        system_prompt: str,  # 系统提示词（定义 Agent 的身份和规则）
        workspace: str,  # 工具允许操作的工作目录
        max_turns: int = 20,  # 最大循环次数（防死循环）
        identity: str = "user",  # 调用者身份（用于权限控制）
        authorizer: ToolAuthorizer | None = None,  # 可选旧版授权器（兼容第一章）
        permission_policy: PermissionPolicy | None = None,  # 可选权限策略（第三章引入）
        hooks: HookRegistry | None = None,  # 可选 Hook 注册表（第四章引入）
        tool_round_observer: ToolRoundObserver | None = None,  # 可选工具轮观察器（第六章引入）
    ) -> None:
        """初始化 Agent 运行器。

        这是什么：依赖注入构造器，所有依赖从外部传入
        Java 类比：类似 Spring 的 @Autowired 构造器注入
        为什么需要：保持依赖倒置原则，核心循环不依赖具体实现
        """
        # 参数校验：在构造时就失败，而不是运行时才发现配置错误
        if max_turns <= 0:
            raise ValueError("max_turns 必须是正整数")
        if not identity.strip():
            raise ValueError("identity 不能为空")
        if not system_prompt.strip():
            raise ValueError("system_prompt 不能为空")
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        self._workspace = str(Path(workspace).resolve())  # 转为绝对路径
        self._max_turns = max_turns
        self._identity = identity
        self._authorizer = authorizer
        # 当有 Hook 但未提供权限策略时，自动创建默认策略
        self._permission_policy = (
            PermissionPolicy()
            if permission_policy is None and hooks is not None
            else permission_policy
        )
        self._hooks = hooks or HookRegistry()  # 未提供时使用空注册表
        self._tool_round_observer = tool_round_observer
        self._history: list[ChatMessage] = []  # 不包含 system prompt 的可变会话历史

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        """返回不可变历史副本，外部不能修改下一轮模型请求。

        这是什么：只读属性，外部可以读取但不能修改
        Java 类比：public List<ChatMessage> getHistory() { return List.copyOf(history); }
        为什么需要：防止外部代码直接修改 Agent 内部状态
        """
        return tuple(self._history)

    def run(self, prompt: str) -> RunResult:
        """同步入口；内部用 asyncio 顺序等待同步或异步 Hook。

        这是什么：Agent 的主入口方法，提供同步调用接口
        Java 类比：public RunResult execute(String userPrompt)
        为什么需要：Hook 可能是异步的，但保持同步接口对调用方更友好
        """
        try:
            asyncio.get_running_loop()  # 检查是否已有事件循环
        except RuntimeError:
            return asyncio.run(self._run(prompt))  # 没有事件循环，创建新的
        raise AgentRunError("当前线程已有 asyncio 事件循环，请在同步入口外调用 AgentRunner.run")

    async def _run(self, prompt: str) -> RunResult:
        """执行完整的 Agent 任务，处理 Hook 和工具轮观察器。

        这是什么：Agent 的异步核心循环
        Java 类比：private CompletableFuture<RunResult> runAsync(String prompt)
        为什么需要：支持异步 Hook 回调，同时保持流程的顺序性
        """
        # 第一步：触发 UserPromptSubmit Hook
        submitted = user_message(prompt)
        prompt_hook = await self._hooks.run_user_prompt(submitted)
        # 把用户消息和 Hook 追加的上下文都放入历史
        self._history.extend((submitted, *prompt_hook.additional_context))
        context = ToolContext(self._workspace, self._identity)
        stop_hook_active = False  # 跟踪 Stop Hook 是否已经强制继续过

        for turn in range(1, self._max_turns + 1):
            # 在花钱请求模型前，先确认上一轮工具调用都有结果
            validate_tool_pairing(self._history)
            snapshot = self._tools.snapshot()  # 快照保证本轮工具定义不变
            # observer_guidance 只拼到本次请求，不 append 到 history
            observer_guidance = (
                ()
                if self._tool_round_observer is None
                else self._tool_round_observer.before_model()  # 获取临时提醒消息
            )
            request = ModelRequest(
                messages=(system_message(self._system_prompt), *self._history, *observer_guidance),
                tools=snapshot.openai_tools(),
            )
            reply = self._model.complete(request)
            if reply.finish_reason == "length":
                raise IncompleteModelReplyError("模型输出达到 token 上限，回答不完整")
            if reply.finish_reason == "content_filter":
                raise AgentRunError("模型回答被内容过滤器拦截")

            assistant = reply.message
            self._history.append(assistant)  # 模型消息先入历史，工具调用才能配对
            if not assistant.tool_calls:  # 没有工具调用，模型认为任务完成
                if assistant.content is None:
                    raise AgentRunError("模型已停止，但没有返回最终文本或工具调用")
                # 触发 Stop Hook，可能强制继续
                stop_hook = await self._hooks.run_stop(self._history, stop_hook_active)
                if stop_hook.force_continue is not None:  # Hook 要求继续
                    self._history.extend((*stop_hook.additional_context, stop_hook.force_continue))
                    stop_hook_active = True  # 标记已强制继续过
                    continue  # 跳回循环开始，再次调用模型
                return self._complete(assistant.content, turn)  # 正常结束

            # 有工具调用时，逐个执行
            results: list[ToolResult] = []
            deferred_context: list[ChatMessage] = []  # 收集所有 Hook 追加的上下文
            stopped_result_index: int | None = None  # 记录哪个工具触发了 prevent_continuation
            for call in assistant.tool_calls:
                if stopped_result_index is not None:  # 已停止，后续工具不执行
                    result = tool_error(
                        "hook_stopped_continuation", "PostToolUse 已要求停止，当前调用未执行"
                    )
                else:
                    execution = await self._execute_tool(call, context, snapshot)
                    result = execution.result
                    deferred_context.extend(execution.additional_context)
                    if execution.prevent_continuation:  # Hook 要求停止后续工具
                        stopped_result_index = len(results)
                results.append(result)

            # 所有工具执行完毕，写回配对的 tool 消息
            for index, call in enumerate(assistant.tool_calls):
                if index >= len(results):
                    raise AgentRunError("工具执行没有产生配对结果")
                self._history.append(tool_message(results[index].content, call.id))
            if self._tool_round_observer is not None:
                # 等所有 tool result 都配对写入后再计数，观察器不会看到半轮状态
                self._tool_round_observer.record_tool_round(
                    tuple(call.name for call in assistant.tool_calls)
                )
            self._history.extend(deferred_context)  # Hook 上下文在配对消息之后追加
            if stopped_result_index is not None:  # Hook 主动停止，返回停止点的结果
                return self._complete(results[stopped_result_index].content, turn)

        # 循环用完仍未得到最终文本
        raise AgentLimitError(f"Agent 已达到最大模型调用轮数 max_turns={self._max_turns}")

    async def _execute_tool(
        self, call: ToolCall, context: ToolContext, tools: ToolRegistry
    ) -> ToolExecution:
        """执行固定链路：prepare -> Pre -> permission -> handler -> Post。

        这是什么：单个工具调用的完整执行流程
        Java 类比：private ToolExecution executeToolChain(ToolCall call)
        为什么需要：确保每个工具都经过完整的生命周期（准备、前置Hook、权限、执行、后置Hook）
        """
        # 第一步：prepare 校验参数
        try:
            prepared = tools.prepare(call)
        except Exception:  # noqa: BLE001
            return ToolExecution(tool_error("tool_preparation_error", "工具准备失败"))
        if prepared.error is not None:  # 准备阶段已失败（未知工具、JSON错误等）
            return ToolExecution(prepared.error)

        # 第二步：触发 PreToolUse Hook
        try:
            pre_hook = await self._hooks.run_pre_tool(prepared)
        except HookContractError:  # Hook 返回了非法更新
            return ToolExecution(
                tool_error("hook_contract_error", "PreToolUse Hook 返回了非法更新")
            )
        except Exception:  # noqa: BLE001
            return ToolExecution(tool_error("hook_execution_error", "PreToolUse Hook 执行失败"))

        # Hook 可能修改了参数，使用修改后的版本
        effective = pre_hook.updated_input or prepared
        if pre_hook.blocking_error is not None:  # Hook 主动阻断
            return ToolExecution(pre_hook.blocking_error, pre_hook.additional_context)

        # 第三步：权限检查（结合 Hook 建议和系统策略）
        permission_error = self._check_permission(effective, context, pre_hook)
        if permission_error is not None:  # 权限拒绝
            return ToolExecution(permission_error, pre_hook.additional_context)

        # 第四步：执行工具
        result = tools.invoke(effective, context)

        # 第五步：触发 PostToolUse Hook
        try:
            post_hook = await self._hooks.run_post_tool(effective, result)
        except Exception:  # noqa: BLE001
            return ToolExecution(
                tool_error("hook_execution_error", "PostToolUse Hook 执行失败"),
                pre_hook.additional_context,
            )
        # 返回最终结果：可能被 PostHook 修改的结果、合并的上下文、是否停止继续
        return ToolExecution(
            post_hook.updated_output or result,
            pre_hook.additional_context + post_hook.additional_context,
            post_hook.prevent_continuation,
        )

    def _check_permission(
        self, prepared: PreparedToolCall, context: ToolContext, pre_hook: HookResult
    ) -> ToolResult | None:
        """把 Hook 建议交给第三章权限策略；Hook allow 不能绕过系统 deny。

        这是什么：整合 Hook 建议和权限策略的决策逻辑
        Java 类比：private ToolResult checkPermissionWithHookAdvice(PreparedToolCall, HookResult)
        为什么需要：让 Hook 能影响权限决策，但不能完全绕过系统策略（安全优先）
        """
        if self._permission_policy is not None:  # 有权限策略时走新流程
            recommendations: tuple[PermissionDecision, ...] = ()
            if pre_hook.permission_behavior != "passthrough":  # Hook 提出了建议
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
            except Exception:  # noqa: BLE001  | 策略评估失败，默认拒绝
                return tool_error("permission_evaluation_error", "权限评估失败")
        if self._authorizer is not None:  # 兼容第一章的授权器
            try:
                authorization = self._authorizer.authorize(prepared, context)
                if not authorization.reason.strip():
                    raise ValueError("工具授权结果必须说明原因")
                return (
                    None
                    if authorization.allowed
                    else tool_error("permission_denied", authorization.reason)
                )
            except Exception:  # noqa: BLE001  | fail-closed 原则
                return tool_error("permission_denied", "工具授权过程发生异常，已按默认拒绝处理")
        return None  # 既无策略也无授权器，直接放行

    def _complete(self, final_text: str, turns: int) -> RunResult:
        """完成前再次检查消息配对，并返回与内部列表隔离的快照。

        这是什么：构造不可变结果对象的辅助方法
        Java 类比：private RunResult buildResult(String finalText, int turns)
        为什么需要：确保返回的历史是不可变副本，防止外部修改影响下次运行
        """
        validate_tool_pairing(self._history)  # 最终校验：确保所有工具调用都已配对
        return RunResult(final_text, tuple(self._history), turns)
