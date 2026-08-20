"""带 Hook 生命周期的 Agent 核心循环。

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
    def authorize(self, prepared: PreparedToolCall, context: ToolContext) -> ToolAuthorizationDecision: ...


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

    def __init__(self, model: ModelClient, tools: ToolRegistry, system_prompt: str, workspace: str, max_turns: int = 20, identity: str = "user", authorizer: ToolAuthorizer | None = None, permission_policy: PermissionPolicy | None = None, hooks: HookRegistry | None = None) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns 必须是正整数")
        if not identity.strip():
            raise ValueError("identity 不能为空")
        if not system_prompt.strip():
            raise ValueError("system_prompt 不能为空")
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        self._workspace = str(Path(workspace).resolve())
        self._max_turns = max_turns
        self._identity = identity
        self._authorizer = authorizer
        self._permission_policy = PermissionPolicy() if permission_policy is None and hooks is not None else permission_policy
        self._hooks = hooks or HookRegistry()
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
        context = ToolContext(self._workspace, self._identity)
        stop_hook_active = False

        for turn in range(1, self._max_turns + 1):
            validate_tool_pairing(self._history)
            snapshot = self._tools.snapshot()
            request = ModelRequest(messages=(system_message(self._system_prompt), *self._history), tools=snapshot.openai_tools())
            reply = self._model.complete(request)
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
                    result = tool_error("hook_stopped_continuation", "PostToolUse 已要求停止，当前调用未执行")
                else:
                    execution = await self._execute_tool(call, context, snapshot)
                    result = execution.result
                    deferred_context.extend(execution.additional_context)
                    if execution.prevent_continuation:
                        stopped_result_index = len(results)
                results.append(result)

            for index, call in enumerate(assistant.tool_calls):
                if index >= len(results):
                    raise AgentRunError("工具执行没有产生配对结果")
                self._history.append(tool_message(results[index].content, call.id))
            self._history.extend(deferred_context)
            if stopped_result_index is not None:
                return self._complete(results[stopped_result_index].content, turn)

        raise AgentLimitError(f"Agent 已达到最大模型调用轮数 max_turns={self._max_turns}")

    async def _execute_tool(self, call: ToolCall, context: ToolContext, tools: ToolRegistry) -> ToolExecution:
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
            return ToolExecution(tool_error("hook_contract_error", "PreToolUse Hook 返回了非法更新"))
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
            return ToolExecution(tool_error("hook_execution_error", "PostToolUse Hook 执行失败"), pre_hook.additional_context)
        return ToolExecution(post_hook.updated_output or result, pre_hook.additional_context + post_hook.additional_context, post_hook.prevent_continuation)

    def _check_permission(self, prepared: PreparedToolCall, context: ToolContext, pre_hook: HookResult) -> ToolResult | None:
        """把 Hook 建议交给第三章权限策略；Hook allow 不能绕过系统 deny。"""
        if self._permission_policy is not None:
            recommendations: tuple[PermissionDecision, ...] = ()
            if pre_hook.permission_behavior != "passthrough":
                recommendations = (PermissionDecision(pre_hook.permission_behavior, f"PreToolUse Hook 建议 {pre_hook.permission_behavior}", "pre-tool-hook"),)
            try:
                decision = self._permission_policy.decide(PermissionRequest(prepared, context, recommendations))
                return None if decision.is_allowed else decision.to_tool_result()
            except Exception:  # noqa: BLE001
                return tool_error("permission_evaluation_error", "权限评估失败")
        if self._authorizer is not None:
            try:
                authorization = self._authorizer.authorize(prepared, context)
                if not authorization.reason.strip():
                    raise ValueError("工具授权结果必须说明原因")
                return None if authorization.allowed else tool_error("permission_denied", authorization.reason)
            except Exception:  # noqa: BLE001
                return tool_error("permission_denied", "工具授权过程发生异常，已按默认拒绝处理")
        return None

    def _complete(self, final_text: str, turns: int) -> RunResult:
        """完成前再次检查消息配对，并返回与内部列表隔离的快照。"""
        validate_tool_pairing(self._history)
        return RunResult(final_text, tuple(self._history), turns)
