"""Agent 核心循环。

Java 角度：这是应用服务，不负责创建 OpenAI 客户端或 PowerShell 进程；
它只编排 ModelClient、ToolRegistry 和消息历史。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .messages import ChatMessage, system_message, tool_message, user_message, validate_tool_pairing
from .model import ModelClient, ModelRequest
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
    allowed: bool
    reason: str


class ToolAuthorizer(Protocol):
    """工具授权接口，类似 Java 中的鉴权 Service。"""
    def authorize(self, prepared: PreparedToolCall, context: ToolContext) -> ToolAuthorizationDecision: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次 Agent 运行结束后返回给调用方的结果。"""
    final_text: str
    history: tuple[ChatMessage, ...]
    turns: int


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
    ) -> None:
        # 构造函数只保存依赖和长期配置。和 Java 构造器注入一样，依赖从外部传进来。
        if max_turns <= 0:
            raise ValueError("max_turns must be a positive integer")
        if not identity.strip():
            raise ValueError("identity must not be empty")
        if not system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        self._model = model
        self._tools = tools
        self._system_prompt = system_prompt
        self._workspace = str(Path(workspace).resolve())
        self._max_turns = max_turns
        self._identity = identity
        self._authorizer = authorizer
        self._history: list[ChatMessage] = []

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
                raise IncompleteModelReplyError("Model output reached the token limit")
            if reply.finish_reason == "content_filter":
                raise AgentRunError("Model response was blocked by the content filter")

            # 模型消息要先入历史，后面的 tool 消息才能通过 call.id 与它配对。
            assistant = reply.message
            self._history.append(assistant)

            # 没有工具调用，表示模型认为任务完成了，此时退出循环。
            if not assistant.tool_calls:
                if assistant.content is None:
                    raise AgentRunError("Model stopped without final text or tool calls")
                validate_tool_pairing(self._history)
                return RunResult(assistant.content, tuple(self._history), turn)

            for call in assistant.tool_calls:
                # prepare 只校验，不执行 PowerShell。
                prepared = snapshot.prepare(call)
                result: ToolResult
                if prepared.error is not None:
                    # 未知工具、错误 JSON 等失败已经变成可回填的 ToolResult。
                    result = prepared.error
                elif self._authorizer is not None:
                    try:
                        # 有授权器时，必须先获得明确允许，才能进入 invoke。
                        decision = self._authorizer.authorize(prepared, context)
                        if not decision.reason.strip():
                            raise ValueError("authorization decision reason must not be empty")
                        result = snapshot.invoke(prepared, context) if decision.allowed else tool_error("permission_denied", decision.reason)
                    except Exception:
                        # 授权系统本身报错时默认拒绝，这叫 fail-closed。
                        result = tool_error("permission_denied", "Tool approval failed closed")
                else:
                    # 单元测试通常不注入授权器，直接使用 Fake 工具执行器。
                    result = snapshot.invoke(prepared, context)

                # 无论成功、失败还是拒绝，每个 call.id 都必须写回一条 tool 消息。
                self._history.append(tool_message(result.content, call.id))

        # 循环用完仍未得到最终文本，说明模型一直在调用工具。
        raise AgentLimitError(f"Agent exceeded max_turns={self._max_turns}")
