"""Agent 核心循环。

这是什么：Agent 运行时的核心控制逻辑，负责循环调用模型和执行工具
Java 类比：类似 @Service class AgentService，编排模型调用、工具执行和消息流转
为什么需要：实现 Agent 的核心控制流，连接模型推理和工具执行，管理对话状态

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
    """Agent 执行过程中的领域错误。

    这是什么：Agent 运行时异常的基类
    Java 类比：类似 AgentExecutionException
    为什么需要：统一 Agent 运行时错误，便于上层捕获和处理
    """


class AgentLimitError(AgentRunError):
    """达到最大模型调用轮数。

    这是什么：循环次数限制异常
    Java 类比：类似 MaxIterationsExceededException
    为什么需要：防止死循环，保护资源和成本
    """


class IncompleteModelReplyError(AgentRunError):
    """模型输出因 token 限制被截断。

    这是什么：模型输出不完整异常
    Java 类比：类似 IncompleteLLMResponseException
    为什么需要：标识模型输出被截断，提示需要增加 max_tokens 或简化任务
    """


@dataclass(frozen=True, slots=True)
class ToolAuthorizationDecision:
    """授权结果：是否允许，以及给模型看的原因。

    这是什么：工具授权决策的值对象
    Java 类比：类似 record AuthorizationDecision(boolean allowed, String reason)
    为什么需要：封装授权结果，让模型能理解为什么被拒绝
    """
    allowed: bool  # True 表示可以执行工具；False 表示只生成拒绝结果。
    reason: str  # 给人和模型看的原因，拒绝时尤其重要。


class ToolAuthorizer(Protocol):
    """工具授权接口，类似 Java 中的鉴权 Service。

    这是什么：工具授权器的接口定义
    Java 类比：interface ToolAuthorizer { AuthorizationDecision authorize(PreparedToolCall call, ToolContext ctx); }
    为什么需要：定义授权契约，支持不同授权策略（自动批准、人工审核、策略规则）
    """
    def authorize(self, prepared: PreparedToolCall, context: ToolContext) -> ToolAuthorizationDecision: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次 Agent 运行结束后返回给调用方的结果。

    这是什么：Agent 运行结果的值对象
    Java 类比：类似 record RunResult(String finalText, List<ChatMessage> history, int turns)
    为什么需要：封装运行结果，提供完整的对话历史和元数据
    """
    final_text: str  # 模型最后一次返回的普通文本。
    history: tuple[ChatMessage, ...]  # 完整对话副本，用于测试和审计。
    turns: int  # 实际调用模型的次数，从 1 开始。


class AgentRunner:
    """一轮轮调用模型，直到模型返回最终文本。

    这是什么：Agent 循环控制器，编排模型调用、工具执行和消息管理
    Java 类比：类似 @Service class AgentOrchestrator
    为什么需要：实现 Agent 的 ReAct 循环（Reasoning + Acting），管理状态和流程

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
        """初始化 Agent 运行器。

        这是什么：构造器，通过依赖注入接收所有外部依赖
        Java 类比：类似 @Autowired 构造器注入依赖
        为什么需要：解耦 Agent 逻辑和外部实现，便于测试和配置切换
        """
        # 构造函数只保存依赖和长期配置。和 Java 构造器注入一样，依赖从外部传进来。
        if max_turns <= 0:  # 验证最大轮数必须为正数
            raise ValueError("max_turns 必须是正整数")
        if not identity.strip():  # 验证身份标识不能为空
            raise ValueError("identity 不能为空")
        if not system_prompt.strip():  # 验证系统提示不能为空
            raise ValueError("system_prompt 不能为空")
        self._model = model  # 模型接口：可以是真实 DeepSeek，也可以是测试 Fake。
        self._tools = tools  # 工具注册表：保存模型可以调用的"手"。
        self._system_prompt = system_prompt  # 每轮都要放在消息最前面的系统约束。
        self._workspace = str(Path(workspace).resolve())  # 工具允许使用的工作目录。
        self._max_turns = max_turns  # 单次任务最多调用模型多少次，防止死循环。
        self._identity = identity  # 当前调用者身份，后续权限系统会使用。
        self._authorizer = authorizer  # 可选授权器；没有时通常用于离线测试。
        self._history: list[ChatMessage] = []  # 不包含 system prompt 的可变会话历史。

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        """返回对话历史的不可变副本。

        这是什么：历史记录的只读访问器
        Java 类比：类似 public List<ChatMessage> getHistory() { return List.copyOf(history); }
        为什么需要：保护内部状态，防止外部代码修改历史记录
        """
        # tuple 是不可变序列。返回副本，避免外部代码直接修改 Agent 内部历史。
        return tuple(self._history)

    def run(self, prompt: str) -> RunResult:
        """执行 Agent 主循环，直到模型返回最终答案或达到轮数限制。

        这是什么：Agent 的核心运行方法，实现 ReAct 循环
        Java 类比：类似 public RunResult run(String prompt) throws AgentRunError
        为什么需要：启动 Agent 循环，处理用户请求，返回最终结果
        """
        # 第一步：把用户问题放入历史。system prompt 不放这里，它每轮请求时临时加在最前面。
        self._history.append(user_message(prompt))  # 添加用户消息到历史

        # 所有工具共享同一份工作目录和调用者身份，工具自己不能随意决定这些边界。
        context = ToolContext(self._workspace, self._identity)  # 构造工具执行上下文

        # 一次循环就是一次模型请求。设置上限是为了防止模型无限要求调用工具。
        for turn in range(1, self._max_turns + 1):  # 循环调用模型，从 1 开始计数
            # 在花钱请求模型前，先确认上一轮工具调用都有结果。
            validate_tool_pairing(self._history)  # 校验工具调用和结果是否配对

            # 快照保证"模型看到的工具"和"这一轮真正能执行的工具"完全一致。
            snapshot = self._tools.snapshot()  # 获取工具注册表快照

            # Python 的 *self._history 类似 Java 中把一个 List 展开放进新 List。
            request = ModelRequest(
                messages=(system_message(self._system_prompt), *self._history),  # 组装消息列表，system prompt 放最前面
                tools=snapshot.openai_tools(),  # 添加工具定义
            )

            # 核心循环只调用接口，不知道内部是 DeepSeek、OpenAI 还是假模型。
            reply = self._model.complete(request)  # 调用模型获取响应

            # length 表示回答被 token 上限截断，不能把半截内容当成最终答案。
            if reply.finish_reason == "length":  # 输出因长度限制被截断
                raise IncompleteModelReplyError("模型输出达到 token 上限，回答不完整")
            if reply.finish_reason == "content_filter":  # 输出被内容过滤器拦截
                raise AgentRunError("模型回答被内容过滤器拦截")

            # 模型消息要先入历史，后面的 tool 消息才能通过 call.id 与它配对。
            assistant = reply.message  # 提取 assistant 消息
            self._history.append(assistant)  # 添加到历史记录

            # 没有工具调用，表示模型认为任务完成了，此时退出循环。
            if not assistant.tool_calls:  # 模型未请求工具调用
                if assistant.content is None:  # 但也没有返回文本内容
                    raise AgentRunError("模型已停止，但没有返回最终文本或工具调用")
                validate_tool_pairing(self._history)  # 最后验证历史完整性
                return RunResult(assistant.content, tuple(self._history), turn)  # 返回最终结果

            for call in assistant.tool_calls:  # 遍历所有工具调用请求
                # prepare 只校验，不执行 PowerShell。
                prepared = snapshot.prepare(call)  # 准备工具调用（仅校验，不执行）
                result: ToolResult  # 声明结果变量类型
                if prepared.error is not None:  # 准备阶段发现错误（如工具不存在、参数非法）
                    # 未知工具、错误 JSON 等失败已经变成可回填的 ToolResult。
                    result = prepared.error  # 使用准备阶段的错误结果
                elif self._authorizer is not None:  # 有授权器时需要人工批准
                    try:
                        # 有授权器时，必须先获得明确允许，才能进入 invoke。
                        decision = self._authorizer.authorize(prepared, context)  # 请求授权
                        if not decision.reason.strip():  # 授权结果必须包含原因
                            raise ValueError("工具授权结果必须说明原因")
                        result = snapshot.invoke(prepared, context) if decision.allowed else tool_error("permission_denied", decision.reason)  # 根据授权结果执行或拒绝
                    # 授权器属于外部边界，无论抛出哪种异常都必须默认拒绝。
                    except Exception:  # noqa: BLE001 | 捕获所有授权器异常
                        # 授权系统本身报错时默认拒绝，这叫 fail-closed。
                        result = tool_error("permission_denied", "工具授权过程发生异常，已按默认拒绝处理")  # 默认拒绝策略
                else:  # 无授权器时直接执行（通常用于测试）
                    # 单元测试通常不注入授权器，直接使用 Fake 工具执行器。
                    result = snapshot.invoke(prepared, context)  # 直接执行工具

                # 无论成功、失败还是拒绝，每个 call.id 都必须写回一条 tool 消息。
                self._history.append(tool_message(result.content, call.id))  # 添加工具结果到历史

        # 循环用完仍未得到最终文本，说明模型一直在调用工具。
        raise AgentLimitError(f"Agent 已达到最大模型调用轮数 max_turns={self._max_turns}")  # 达到最大轮数限制
