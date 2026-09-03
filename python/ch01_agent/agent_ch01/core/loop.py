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
    Java 类比：类似 IncompletDataException
    为什么需要：避免把半截回答当成完整结果返回给用户
    """


# ==================== 授权决策 ====================

@dataclass(frozen=True, slots=True)  # frozen=True 表示不可变，类似 Java record
class ToolAuthorizationDecision:
    """授权结果：是否允许，以及给模型看的原因。

    这是什么：工具授权的返回值对象
    Java 类比：类似 AuthorizationResult record，包含 boolean 和 String
    为什么需要：统一授权结果格式，确保拒绝时必须说明原因

    参数：
        allowed: True 表示可以执行工具；False 表示只生成拒绝结果
        reason: 给人和模型看的原因，拒绝时尤其重要（模型会看到这个文本）
    """
    allowed: bool  # 是否授权执行
    reason: str    # 授权或拒绝的原因说明


class ToolAuthorizer(Protocol):  # Protocol = Java 的 interface
    """工具授权接口，类似 Java 中的鉴权 Service。

    这是什么：定义授权器的契约
    Java 类比：interface ToolAuthorizer { Decision authorize(...); }
    为什么需要：让核心循环不依赖具体授权实现，测试时可以用 Fake 替换
    """
    def authorize(self, prepared: PreparedToolCall, context: ToolContext) -> ToolAuthorizationDecision:
        """判断某个工具调用是否被允许执行。

        参数：
            prepared: 已校验的工具调用（包含工具名、参数）
            context: 运行环境（工作目录、用户身份）

        返回：
            ToolAuthorizationDecision: 包含是否允许和原因
        """
        ...  # Python 的 ... 表示接口方法签名，类似 Java 接口中的抽象方法


# ==================== 运行结果 ====================

@dataclass(frozen=True, slots=True)  # 不可变值对象
class RunResult:
    """一次 Agent 运行结束后返回给调用方的结果。

    这是什么：AgentRunner.run() 的返回值
    Java 类比：record RunResult(String finalText, List<ChatMessage> history, int turns)
    为什么需要：封装三个关键信息，避免用元组或字典传递数据

    参数：
        final_text: 模型最后一次返回的普通文本（用户最终看到的答案）
        history: 完整对话副本（不可变 tuple），用于测试和审计
        turns: 实际调用模型的次数，从 1 开始（用于计费和性能分析）
    """
    final_text: str                      # 最终答案文本
    history: tuple[ChatMessage, ...]     # tuple = 不可变列表，类似 Java 的 List.copyOf()
    turns: int                           # 循环轮数计数


# ==================== 核心 Agent 循环 ====================

class AgentRunner:
    """一轮轮调用模型，直到模型返回最终文本。

    这是全章最重要的类。可以把它看成一个 Service：它只负责编排，
    不负责 HTTP 请求细节，也不负责 PowerShell 进程细节。

    这是什么：Agent 的核心编排器
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
        model: ModelClient,                    # 模型客户端接口（可以是 DeepSeek、OpenAI 或测试 Fake）
        tools: ToolRegistry,                   # 工具注册表（保存所有可用工具的映射表）
        system_prompt: str,                    # 系统提示词（定义 Agent 的身份和规则）
        workspace: str,                        # 工具允许操作的工作目录
        max_turns: int = 20,                   # 最大循环次数（防死循环）
        identity: str = "user",                # 调用者身份（用于权限控制）
        authorizer: ToolAuthorizer | None = None,  # 可选授权器（None 表示无权限检查）
    ) -> None:
        """初始化 Agent 运行器。

        Java 对照：这是构造器注入，所有依赖从外部传入，类似 Spring 的 @Autowired

        参数校验：
            - max_turns 必须 > 0（至少要调用一次模型）
            - identity 不能为空（必须知道是谁在调用）
            - system_prompt 不能为空（模型必须知道自己的角色）
        """
        # 参数校验：在构造时就失败，而不是运行时才发现配置错误
        if max_turns <= 0:
            raise ValueError("max_turns 必须是正整数")
        if not identity.strip():
            raise ValueError("identity 不能为空")
        if not system_prompt.strip():
            raise ValueError("system_prompt 不能为空")

        # 保存依赖：下划线前缀 _ 表示私有字段，类似 Java 的 private final
        self._model = model  # 模型接口：可以是真实 DeepSeek，也可以是测试 Fake
        self._tools = tools  # 工具注册表：保存模型可以调用的"手"
        self._system_prompt = system_prompt  # 每轮都要放在消息最前面的系统约束
        self._workspace = str(Path(workspace).resolve())  # 工具允许使用的工作目录（转为绝对路径）
        self._max_turns = max_turns  # 单次任务最多调用模型多少次，防止死循环
        self._identity = identity  # 当前调用者身份，后续权限系统会使用
        self._authorizer = authorizer  # 可选授权器；没有时通常用于离线测试
        self._history: list[ChatMessage] = []  # 不包含 system prompt 的可变会话历史

    @property  # Python 的 @property 类似 Java 的 getter 方法
    def history(self) -> tuple[ChatMessage, ...]:
        """返回对话历史的不可变副本。

        这是什么：只读属性，外部可以读取但不能修改
        Java 类比：public List<ChatMessage> getHistory() { return List.copyOf(history); }
        为什么需要：防止外部代码直接修改 Agent 内部状态

        返回：
            tuple[ChatMessage, ...]: 不可变消息序列（tuple 类似 Java 的 Collections.unmodifiableList）
        """
        # tuple 是不可变序列。返回副本，避免外部代码直接修改 Agent 内部历史
        return tuple(self._history)

    def run(self, prompt: str) -> RunResult:
        """执行一次完整的 Agent 任务，直到模型返回最终答案或达到轮数上限。

        这是什么：Agent 的主入口方法
        Java 类比：public RunResult execute(String userPrompt) throws AgentRunError
        为什么需要：封装完整的"问题→循环→答案"流程

        参数：
            prompt: 用户输入的自然语言问题

        返回：
            RunResult: 包含最终答案、完整历史和轮数统计

        异常：
            AgentLimitError: 达到最大轮数仍未得到答案
            IncompleteModelReplyError: 模型回复被 token 限制截断
            AgentRunError: 其他运行时错误
        """
        # 第一步：把用户问题放入历史。system prompt 不放这里，它每轮请求时临时加在最前面
        self._history.append(user_message(prompt))

        # 所有工具共享同一份工作目录和调用者身份，工具自己不能随意决定这些边界
        context = ToolContext(self._workspace, self._identity)

        # 一次循环就是一次模型请求。设置上限是为了防止模型无限要求调用工具
        # range(1, max_turns + 1) 生成 [1, 2, ..., max_turns]，类似 Java 的 for(int i=1; i<=max; i++)
        for turn in range(1, self._max_turns + 1):
            # 在花钱请求模型前，先确认上一轮工具调用都有结果
            # 这一步类似 Java 的数据完整性检查，避免发送格式错误的消息给模型 API
            validate_tool_pairing(self._history)

            # 快照保证"模型看到的工具"和"这一轮真正能执行的工具"完全一致
            # 如果中途有工具被动态添加/移除，本轮不受影响
            snapshot = self._tools.snapshot()

            # Python 的 *self._history 类似 Java 中把一个 List 展开放进新 List
            # 相当于 new ArrayList<>(List.of(systemMsg), historyMessages)
            request = ModelRequest(
                messages=(system_message(self._system_prompt), *self._history),  # system 放最前面
                tools=snapshot.openai_tools(),  # 转换成 OpenAI 格式的工具定义
            )

            # 核心循环只调用接口，不知道内部是 DeepSeek、OpenAI 还是假模型
            # 这是依赖倒置原则：高层不依赖低层实现
            reply = self._model.complete(request)

            # length 表示回答被 token 上限截断，不能把半截内容当成最终答案
            if reply.finish_reason == "length":
                raise IncompleteModelReplyError("模型输出达到 token 上限，回答不完整")
            if reply.finish_reason == "content_filter":  # 内容被安全过滤器拦截
                raise AgentRunError("模型回答被内容过滤器拦截")

            # 模型消息要先入历史，后面的 tool 消息才能通过 call.id 与它配对
            assistant = reply.message
            self._history.append(assistant)

            # 没有工具调用，表示模型认为任务完成了，此时退出循环
            # Java 对照：if (assistant.toolCalls().isEmpty()) { return result; }
            if not assistant.tool_calls:  # not [] 等价于 Java 的 isEmpty()
                if assistant.content is None:  # 既没文本也没工具调用，这是异常情况
                    raise AgentRunError("模型已停止，但没有返回最终文本或工具调用")
                validate_tool_pairing(self._history)  # 最后再检查一次消息配对完整性
                return RunResult(assistant.content, tuple(self._history), turn)

            # 有工具调用时，逐个执行并把结果写回历史
            for call in assistant.tool_calls:  # 类似 Java 的 for (ToolCall call : assistant.toolCalls())
                # prepare 只校验，不执行 PowerShell
                # 这一步会检查工具是否存在、JSON 是否合法、参数是否符合 schema
                prepared = snapshot.prepare(call)
                result: ToolResult  # 显式类型标注，类似 Java 的 ToolResult result;

                if prepared.error is not None:  # 准备阶段已经失败（未知工具、JSON 错误等）
                    # 未知工具、错误 JSON 等失败已经变成可回填的 ToolResult
                    # 不需要用异常处理，直接把错误结果返回给模型，让它换个做法
                    result = prepared.error
                elif self._authorizer is not None:  # 有授权器时走权限检查流程
                    try:
                        # 有授权器时，必须先获得明确允许，才能进入 invoke
                        decision = self._authorizer.authorize(prepared, context)
                        if not decision.reason.strip():  # 授权结果必须说明原因
                            raise ValueError("工具授权结果必须说明原因")
                        # 三元表达式：类似 Java 的 decision.allowed ? invoke(...) : error(...)
                        result = snapshot.invoke(prepared, context) if decision.allowed else tool_error("permission_denied", decision.reason)
                    # 授权器属于外部边界，无论抛出哪种异常都必须默认拒绝
                    except Exception:  # noqa: BLE001 | 类似 Java 的 catch (Exception e)
                        # 授权系统本身报错时默认拒绝，这叫 fail-closed（安全优先原则）
                        # 类比：信用卡系统如果挂了，应该拒绝交易而不是放行
                        result = tool_error("permission_denied", "工具授权过程发生异常，已按默认拒绝处理")
                else:  # 没有授权器时直接执行
                    # 单元测试通常不注入授权器，直接使用 Fake 工具执行器
                    result = snapshot.invoke(prepared, context)

                # 无论成功、失败还是拒绝，每个 call.id 都必须写回一条 tool 消息
                # 这是 OpenAI 工具协议的强制要求：assistant 的每个 call 必须有对应的 tool 结果
                self._history.append(tool_message(result.content, call.id))

        # 循环用完仍未得到最终文本，说明模型一直在调用工具
        # 类比：就像递归深度超限，必须中断避免无限循环
        raise AgentLimitError(f"Agent 已达到最大模型调用轮数 max_turns={self._max_turns}")
