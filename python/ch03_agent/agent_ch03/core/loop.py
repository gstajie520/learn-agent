"""Agent 核心循环。

这是什么：编排模型调用、工具执行、权限检查的主循环。
Java 类比：类似 ApplicationService，协调多个领域服务完成业务流程。
为什么需要：Agent 是循环调用工具的编排系统，需要管理消息历史、轮数限制、权限检查。

Java 角度：这是应用服务，不负责创建 OpenAI 客户端或 PowerShell 进程；
它只编排 ModelClient、ToolRegistry 和消息历史。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .messages import (
    ChatMessage,
    system_message,
    tool_message,
    user_message,
    validate_tool_pairing,
)
from .model import ModelClient, ModelRequest
from .permissions import PermissionPolicy, PermissionRequest
from .tools import PreparedToolCall, ToolContext, ToolRegistry, ToolResult, tool_error


class AgentRunError(Exception):
    """Agent 执行过程中的领域错误。"""


class AgentLimitError(AgentRunError):
    """达到最大模型调用轮数。"""


class IncompleteModelReplyError(AgentRunError):
    """模型输出因 token 限制被截断。"""


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """授权结果：是否允许，以及给模型看的原因。"""
    allowed: bool  # True 表示可以执行工具；False 表示只生成拒绝结果。
    reason: str  # 给人和模型看的原因，拒绝时尤其重要。


class ToolAuthorizer(Protocol):
    """工具授权接口，类似 Java 中的鉴权 Service。"""
    def authorize(self, prepared: PreparedToolCall, context: ToolContext) -> ToolAuthorizationDecision: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次 Agent 运行结束后返回给调用方的结果。"""
    final_text: str  # 模型最后一次返回的普通文本。
    history: tuple[ChatMessage, ...]  # 完整对话副本，用于测试和审计。
    turns: int  # 实际调用模型的次数，从 1 开始。


class AgentRunner:
    """一轮轮调用模型，直到模型返回最终文本。

    这是全章最重要的类。可以把它看成一个 Service：它只负责编排，
    不负责 HTTP 请求细节，也不负责 PowerShell 进程细节。
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
    ) -> None:
        # 构造函数只保存依赖和长期配置。和 Java 构造器注入一样，依赖从外部传进来。
        if max_turns <= 0:
            raise ValueError("max_turns 必须是正整数")
        if not identity.strip():
            raise ValueError("identity 不能为空")
        if not system_prompt.strip():
            raise ValueError("system_prompt 不能为空")
        self._model = model  # 模型接口：可以是真实 DeepSeek，也可以是测试 Fake。
        self._tools = tools  # 工具注册表：保存模型可以调用的“手”。
        self._system_prompt = system_prompt  # 每轮都要放在消息最前面的系统约束。
        self._workspace = str(Path(workspace).resolve())  # 工具允许使用的工作目录。
        self._max_turns = max_turns  # 单次任务最多调用模型多少次，防止死循环。
        self._identity = identity  # 当前调用者身份，后续权限系统会使用。
        self._authorizer = authorizer  # 可选授权器；没有时通常用于离线测试。
        self._permission_policy = permission_policy  # 第三章执行前权限、审批和审计边界。
        self._history: list[ChatMessage] = []  # 不包含 system prompt 的可变会话历史。

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        # tuple 是不可变序列。返回副本，避免外部代码直接修改 Agent 内部历史。
        return tuple(self._history)

    def run(self, prompt: str) -> RunResult:
        # 第一步：把用户问题放入历史。system prompt 不放这里，它每轮请求时临时加在最前面。
        self._history.append(user_message(prompt))

        # 所有工具共享同一份工作目录和调用者身份，工具自己不能随意决定这些边界。
        context = ToolContext(self._workspace, self._identity)

        # 一次循环就是一次模型请求。设置上限是为了防止模型无限要求调用工具。
        for turn in range(1, self._max_turns + 1):
            # 在花钱请求模型前，先确认上一轮工具调用都有结果。
            validate_tool_pairing(self._history)

            # 快照保证“模型看到的工具”和“这一轮真正能执行的工具”完全一致。
            snapshot = self._tools.snapshot()

            # Python 的 *self._history 类似 Java 中把一个 List 展开放进新 List。
            request = ModelRequest(
                messages=(system_message(self._system_prompt), *self._history),
                tools=snapshot.openai_tools(),
            )

            # 核心循环只调用接口，不知道内部是 DeepSeek、OpenAI 还是假模型。
            reply = self._model.complete(request)

            # length 表示回答被 token 上限截断，不能把半截内容当成最终答案。
            if reply.finish_reason == "length":
                raise IncompleteModelReplyError("模型输出达到 token 上限，回答不完整")
            if reply.finish_reason == "content_filter":
                raise AgentRunError("模型回答被内容过滤器拦截")

            # 模型消息要先入历史，后面的 tool 消息才能通过 call.id 与它配对。
            assistant = reply.message
            self._history.append(assistant)

            # 没有工具调用，表示模型认为任务完成了，此时退出循环。
            if not assistant.tool_calls:
                if assistant.content is None:
                    raise AgentRunError("模型已停止，但没有返回最终文本或工具调用")
                validate_tool_pairing(self._history)
                return RunResult(assistant.content, tuple(self._history), turn)

            for call in assistant.tool_calls:
                # prepare 只校验，不执行 PowerShell。
                prepared = snapshot.prepare(call)
                result: ToolResult
                if prepared.error is not None:
                    # 未知工具、错误 JSON 等失败已经变成可回填的 ToolResult。
                    result = prepared.error
                elif self._permission_policy is not None:
                    try:
                        permission_decision = self._permission_policy.decide(PermissionRequest(prepared, context))
                        result = snapshot.invoke(prepared, context) if permission_decision.is_allowed else permission_decision.to_tool_result()
                    except Exception:  # noqa: BLE001
                        # 权限评估或审计失败时也必须生成配对 tool 消息，且不能执行 handler。
                        result = tool_error("permission_evaluation_error", "权限评估失败")
                elif self._authorizer is not None:
                    try:
                        # 有授权器时，必须先获得明确允许，才能进入 invoke。
                        authorization_decision = self._authorizer.authorize(prepared, context)
                        if not authorization_decision.reason.strip():
                            raise ValueError("工具授权结果必须说明原因")
                        result = snapshot.invoke(prepared, context) if authorization_decision.allowed else tool_error("permission_denied", authorization_decision.reason)
                    # 授权器属于外部边界，无论抛出哪种异常都必须默认拒绝。
                    except Exception:  # noqa: BLE001
                        # 授权系统本身报错时默认拒绝，这叫 fail-closed。
                        result = tool_error("permission_denied", "工具授权过程发生异常，已按默认拒绝处理")
                else:
                    # 单元测试通常不注入授权器，直接使用 Fake 工具执行器。
                    result = snapshot.invoke(prepared, context)

                # 无论成功、失败还是拒绝，每个 call.id 都必须写回一条 tool 消息。
                self._history.append(tool_message(result.content, call.id))

        # 循环用完仍未得到最终文本，说明模型一直在调用工具。
        raise AgentLimitError(f"Agent 已达到最大模型调用轮数 max_turns={self._max_turns}")
