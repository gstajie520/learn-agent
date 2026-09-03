"""第十一章：供应商无关的模型请求恢复层。

这是什么：
    RecoveryManager 是一个装饰器，包装 ModelClient 并透明增加容错能力。
    它处理三类真实生产故障：输出截断、输入过长、429/529 临时错误。

Java 类比：
    RecoveryManager 类似包在 HTTP Client 外面的 Resilience Service（Hystrix/Resilience4j）。
    它接收一次逻辑 ModelRequest，内部完成预算升级、续写、压缩、退避和模型切换，
    最后只向 AgentRunner 返回一个完整 ModelReply。

为什么需要：
    - 真实 API 会截断输出、拒绝过长输入、返回 429/529
    - 恢复层统一处理，避免每个调用点重复实现重试逻辑
    - 外层 AgentRunner 感知不到内部重试，保持简洁

核心设计：
    1. 输出截断：第一次升级预算（8000→64000），仍截断则续写
    2. 输入过长：保留 system message，压缩其余历史（调用第 8 章）
    3. 临时故障：429 遵守 Retry-After，529 连续 3 次切 fallback
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from ..core.messages import (
    ChatMessage,
    SystemMessage,
    assistant_message,
    user_message,
    validate_tool_pairing,
)
from ..core.model import (
    ModelClient,
    ModelOverloadedError,
    ModelPromptTooLongError,
    ModelRateLimitError,
    ModelReply,
    ModelRequest,
)
from .compaction import CompactionManager

DEFAULT_INITIAL_MAX_TOKENS = 8_000  # 首次请求的默认 token 预算（节省成本）
DEFAULT_ESCALATED_MAX_TOKENS = 64_000  # 遇到截断后升级到的预算
DEFAULT_MAX_CONTINUATIONS = 3  # 最多续写几次（避免无限续写）
DEFAULT_MAX_TRANSIENT_ATTEMPTS = 10  # 429/529 最多重试几次
DEFAULT_BASE_DELAY_SECONDS = 0.5  # 指数退避的初始延迟（秒）
DEFAULT_MAX_DELAY_SECONDS = 32.0  # 指数退避的最大延迟上限
DEFAULT_JITTER_RATIO = 0.25  # 随机抖动比例（避免惊群效应）
DEFAULT_OVERLOAD_FALLBACK_THRESHOLD = 3  # 连续几次 529 后切换 fallback 模型
DEFAULT_TOTAL_TIMEOUT_SECONDS = 300.0  # 单个用户回合的总超时时限（5 分钟）
CONTINUATION_PROMPT = (  # 续写提示词：要求模型直接接着写，不要重复或道歉
    "Continue exactly where you left off. Do not repeat any text, no apology, "
    "no recap. Pick up mid-thought."
)


class RecoveryError(Exception):
    """恢复流程公共异常。

    这是什么：恢复层的基础异常类
    Java 类比：类似自定义的 RecoveryException 基类
    为什么需要：让调用方能区分恢复层错误和其他系统错误
    """


class InvalidRetryAfterError(RecoveryError):
    """Retry-After 既不是非负秒数，也不是带时区 HTTP-date。

    这是什么：Retry-After 头解析失败的异常
    Java 类比：类似 ParseException
    为什么需要：HTTP 标准允许两种格式，解析失败需要明确报错
    """


class RecoveryCancelledError(RecoveryError):
    """调用方主动取消当前恢复回合。

    这是什么：取消令牌触发的异常
    Java 类比：类似 CancellationException
    为什么需要：让调用方能明确区分"取消"和"失败"
    """


class RecoveryDeadlineExceeded(RecoveryError):
    """当前用户回合的总 deadline 已耗尽。

    这是什么：总超时时限到达的异常
    Java 类比：类似 TimeoutException
    为什么需要：防止单个请求占用过长时间，保护资源
    """


class RecoveryRetriesExhausted(RecoveryError):
    """瞬态重试或续写次数已用完。

    这是什么：重试次数上限到达的异常
    Java 类比：类似 RetryExhaustedException
    为什么需要：避免无限重试，控制成本和延迟
    """


class CancellationToken:
    """轻量取消令牌，类似 Java 中共享的 AtomicBoolean + listeners。

    这是什么：线程安全的取消通知机制
    Java 类比：AtomicBoolean（状态）+ CopyOnWriteArrayList<Runnable>（监听器）
    为什么需要：让外部能取消长时间运行的恢复过程，且能通知所有等待点

    核心职责：
        1. 维护一个线程安全的取消状态
        2. 支持注册监听器，取消时自动调用
        3. 幂等取消，每个监听器最多调用一次

    Python 限制：
        同步 ModelClient 无法像 TypeScript AbortSignal 那样强制中止运行中的 HTTP 请求，
        只能在调用边界和可取消的等待阶段（Event.wait）检查取消状态。
    """

    def __init__(self) -> None:
        """初始化取消令牌。

        Java 对照：this.cancelled = new AtomicBoolean(false);
                  this.listeners = new CopyOnWriteArrayList<>();
        """
        self._cancelled = False  # 取消状态（布尔值）
        self._listeners: set[Callable[[], None]] = set()  # 监听器集合
        self._lock = threading.Lock()  # 保护状态和监听器的锁

    @property
    def is_cancelled(self) -> bool:
        """线程安全地读取取消状态。

        Java 对照：public boolean isCancelled() { return cancelled.get(); }
        """
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        """幂等取消，并且每个监听器最多调用一次。

        这是什么：设置取消状态并通知所有监听器
        Java 类比：类似 Future.cancel(true)
        为什么需要：多次调用不会重复通知，保证监听器只执行一次

        实现细节：
            1. 加锁检查是否已取消，是则直接返回（幂等）
            2. 设置取消标志，复制监听器列表并清空
            3. 释放锁后调用监听器（避免死锁）
        """
        with self._lock:
            if self._cancelled:  # 已取消，直接返回（幂等保证）
                return
            self._cancelled = True  # 设置取消标志
            listeners = tuple(self._listeners)  # 复制监听器列表
            self._listeners.clear()  # 清空集合，保证每个监听器只调用一次
        # 释放锁后调用监听器，避免监听器内部加锁导致死锁
        for listener in listeners:
            listener()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """注册监听器；已取消时立即调用并返回空退订函数。

        这是什么：添加取消监听器，返回退订函数
        Java 类比：类似 Observable.subscribe() 返回 Subscription
        为什么需要：让等待点能在取消时立即被唤醒

        参数：
            listener: 无参回调函数，取消时会被调用

        返回：
            退订函数，调用后移除监听器

        实现细节：
            - 如果已取消，立即调用监听器并返回空退订函数
            - 否则加入集合，返回能移除自己的退订函数
        """
        if not callable(listener):
            raise TypeError("listener 必须可调用")
        with self._lock:
            if self._cancelled:  # 已取消，立即调用监听器
                immediate = True
            else:
                self._listeners.add(listener)  # 加入监听器集合
                immediate = False
        if immediate:
            listener()  # 立即调用
            return lambda: None  # 返回空退订函数

        def unsubscribe() -> None:
            """退订函数：从监听器集合移除。"""
            with self._lock:
                self._listeners.discard(listener)  # discard 不存在时不报错

        return unsubscribe


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    """不可变恢复配置，类似 Java record RecoveryConfig。

    这是什么：恢复策略的配置参数集合
    Java 类比：record RecoveryConfig(String primaryModel, String fallbackModel, ...)
    为什么需要：集中管理恢复策略的所有可调参数，frozen=True 保证不可变

    核心参数分类：
        1. 模型配置：primary_model、fallback_model
        2. 预算配置：initial_max_tokens、escalated_max_tokens、model_max_tokens
        3. 重试配置：max_continuations、max_transient_attempts
        4. 退避配置：base_delay_seconds、max_delay_seconds、jitter_ratio
        5. 切换配置：overload_fallback_threshold
        6. 超时配置：total_timeout_seconds

    __post_init__ 职责：
        构造后立即校验所有参数合法性，避免运行时才发现配置错误
    """

    primary_model: str  # 主模型名称（如 "deepseek-chat"）
    fallback_model: str  # 备用模型名称（连续 529 时切换）
    initial_max_tokens: int = DEFAULT_INITIAL_MAX_TOKENS  # 首次请求的 token 预算
    escalated_max_tokens: int = DEFAULT_ESCALATED_MAX_TOKENS  # 截断后升级到的预算
    model_max_tokens: int = DEFAULT_ESCALATED_MAX_TOKENS  # 模型支持的最大 token 数
    max_continuations: int = DEFAULT_MAX_CONTINUATIONS  # 最多续写几次
    max_transient_attempts: int = DEFAULT_MAX_TRANSIENT_ATTEMPTS  # 429/529 最多重试几次
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS  # 指数退避初始延迟
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS  # 指数退避最大延迟
    jitter_ratio: float = DEFAULT_JITTER_RATIO  # 随机抖动比例（0.25 = 25%）
    overload_fallback_threshold: int = DEFAULT_OVERLOAD_FALLBACK_THRESHOLD  # 连续几次 529 切换
    total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS  # 单回合总超时

    def __post_init__(self) -> None:
        """构造后校验：捕获配置错误，避免运行时才发现。

        Java 对照：构造器中的参数校验逻辑
        """
        # 模型名称不能为空
        if not self.primary_model.strip() or not self.fallback_model.strip():
            raise ValueError("primary_model 和 fallback_model 不能为空")
        # 所有计数参数必须是正整数
        for name in (
            "initial_max_tokens",
            "escalated_max_tokens",
            "model_max_tokens",
            "max_transient_attempts",
            "overload_fallback_threshold",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} 必须是正整数")
        # 续写次数可以是 0（禁用续写）
        if self.max_continuations < 0:
            raise ValueError("max_continuations 不能为负数")
        # 所有时间参数必须是正有限数
        for name in ("base_delay_seconds", "max_delay_seconds", "total_timeout_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} 必须是正有限数")
        # Jitter 比例必须是非负有限数
        if not math.isfinite(self.jitter_ratio) or self.jitter_ratio < 0:
            raise ValueError("jitter_ratio 必须是非负有限数")
        # 预算参数必须递增
        if self.initial_max_tokens >= self.escalated_max_tokens:
            raise ValueError("escalated_max_tokens 必须大于 initial_max_tokens")
        if self.escalated_max_tokens > self.model_max_tokens:
            raise ValueError("escalated_max_tokens 不能超过 model_max_tokens")
        # 延迟上限必须大于等于基础延迟
        if self.base_delay_seconds > self.max_delay_seconds:
            raise ValueError("base_delay_seconds 不能超过 max_delay_seconds")


@dataclass(slots=True)
class RecoveryState:
    """当前用户回合的可变恢复状态。

    这是什么：单个用户回合内的恢复状态追踪器
    Java 类比：可变 POJO，包含当前模型、预算、重试计数等
    为什么需要：每个 turn 需要独立状态，避免上一轮状态影响下一轮

    状态字段分类：
        1. 当前策略：current_model、current_max_tokens
        2. 恢复进度：has_escalated、recovery_count
        3. 切换判断：consecutive_529
        4. 压缩标志：has_attempted_reactive_compact

    生命周期：
        begin_turn() 时创建，complete() 返回后销毁
    """

    current_model: str  # 当前使用的模型（primary 或 fallback）
    current_max_tokens: int  # 当前请求的 token 预算
    has_escalated: bool = False  # 是否已经升级过预算（8000→64000）
    recovery_count: int = 0  # 当前已续写次数（用于判断是否达到上限）
    consecutive_529: int = 0  # 连续遇到 529 的次数（达到阈值时切换 fallback）
    has_attempted_reactive_compact: bool = False  # 是否已尝试响应式压缩


class RecoveryManager:
    """一次逻辑模型请求的唯一恢复执行器。

    这是什么：装饰器模式，包装 ModelClient 并透明增加容错能力
    Java 类比：类似 Hystrix Command 或 Resilience4j Decorator
    为什么需要：统一处理三类故障，让外层 AgentRunner 无需关心重试细节

    核心职责：
        1. 输出截断恢复：升级预算 → 续写
        2. 输入过长恢复：保留 system → 压缩历史
        3. 临时故障恢复：429 退避、529 切换模型
        4. 取消与超时：检查边界条件，及时失败

    装饰器特性：
        - 外层只调用一次 complete()，内部可能多次调用 ModelClient
        - 成功时返回完整 ModelReply，外层感知不到内部重试
        - 失败时抛出恢复层异常，让外层判断是否继续

    依赖注入：
        model: 被装饰的 ModelClient（真实 OpenAI/DeepSeek 客户端）
        compaction: 压缩管理器（处理输入过长）
        config: 恢复策略配置（不可变）
        cancellation: 取消令牌（可选，用于外部取消）

    测试钩子：
        monotonic: 时间源（单测时注入假时钟）
        utc_now: UTC 时间源（解析 Retry-After HTTP-date）
        sleeper: 等待函数（单测时注入不真正睡眠的假函数）
        jitter: 随机抖动函数（单测时注入固定返回值）
    """

    def __init__(
        self,
        model: ModelClient,  # 被装饰的模型客户端
        compaction: CompactionManager,  # 压缩管理器（处理输入过长）
        config: RecoveryConfig,  # 恢复策略配置
        *,
        monotonic: Callable[[], float] = time.monotonic,  # 单调时钟（用于超时判断）
        utc_now: Callable[[], datetime] | None = None,  # UTC 时间（解析 HTTP-date）
        sleeper: Callable[[float, CancellationToken], None] | None = None,  # 等待函数
        jitter: Callable[[float], float] | None = None,  # 随机抖动函数
        cancellation: CancellationToken | None = None,  # 取消令牌
    ) -> None:
        """初始化恢复管理器。

        Java 对照：构造器注入所有依赖，类似 Spring @Autowired
        """
        self._model = model  # 真实模型客户端
        self._compaction = compaction  # 压缩管理器
        self._config = config  # 不可变配置
        self._monotonic = monotonic  # 时间源
        self._utc_now = utc_now or (lambda: datetime.now(UTC))  # UTC 时间源
        self._sleeper = sleeper or _sleep  # 等待函数（默认用 Event.wait）
        self._jitter = jitter or (lambda upper: random.uniform(0, upper))  # 随机抖动
        self._cancellation = cancellation or CancellationToken()  # 取消令牌
        self._state: RecoveryState | None = None  # 当前回合状态（未开始时为 None）
        self._deadline: float | None = None  # 当前回合的截止时间

    @property
    def state(self) -> RecoveryState:
        """返回状态副本，外部不能修改内部计数。

        Java 对照：public RecoveryState getState() { return state.copy(); }
        """
        state = self._require_state()
        # 返回副本，避免外部修改影响内部状态
        return RecoveryState(
            state.current_model,
            state.current_max_tokens,
            state.has_escalated,
            state.recovery_count,
            state.consecutive_529,
            state.has_attempted_reactive_compact,
        )

    def begin_turn(self) -> None:
        """每个用户回合重置模型、预算、计数和总 deadline。

        这是什么：初始化新回合的恢复状态
        Java 类比：类似 @BeforeEach 或每次请求前的重置逻辑
        为什么需要：每个用户回合独立，避免上一轮状态污染下一轮

        调用时机：
            AgentRunner.run() 开始时调用一次
        """
        started = self._now()  # 记录开始时间
        # 重置为初始状态：主模型、初始预算、所有计数归零
        self._state = RecoveryState(
            self._config.primary_model, self._config.initial_max_tokens
        )
        # 设置本回合的截止时间（开始时间 + 总超时）
        self._deadline = started + self._config.total_timeout_seconds

    def complete(self, request: ModelRequest) -> ModelReply:
        """完成一个逻辑请求；内部尝试不会进入外层 Agent turn。

        这是什么：主恢复循环，处理所有三类故障
        Java 类比：public ModelReply execute(ModelRequest req) throws RecoveryError
        为什么需要：封装完整的"请求→重试→恢复→返回"流程

        参数：
            request: 逻辑模型请求（消息历史 + 工具定义）

        返回：
            ModelReply: 成功的完整回复（可能是续写合并后的）

        异常：
            RecoveryCancelledError: 外部取消
            RecoveryDeadlineExceeded: 超时
            RecoveryRetriesExhausted: 重试次数耗尽
            其他 ModelClient 异常：无法恢复的错误

        核心流程：
            while True:
                1. 检查边界（取消、超时）
                2. 调用模型（使用当前 model 和 max_tokens）
                3. 检查 finish_reason：
                   - "stop" → 返回
                   - "length" → 升级预算或续写
                   - "content_filter" → 抛异常
                4. 捕获异常：
                   - ModelRateLimitError → 退避重试
                   - ModelOverloadedError → 退避重试，连续 3 次切 fallback
                   - ModelPromptTooLongError → 压缩历史重试

        外层感知：
            - 只调用一次 complete()
            - 只看到最终 ModelReply
            - 感知不到内部重试次数
        """
        state = self._require_state()  # 确保已调用 begin_turn()
        validate_tool_pairing(request.messages)  # 校验工具调用配对完整性
        # 校验 request.model 和 request.max_tokens 必须匹配配置或为 None
        if request.model is not None and request.model != self._config.primary_model:
            raise ValueError("request.model 必须匹配 RecoveryConfig.primary_model")
        if request.max_tokens is not None and request.max_tokens != self._config.initial_max_tokens:
            raise ValueError("request.max_tokens 必须匹配 initial_max_tokens")

        request_messages = tuple(request.messages)  # 不可变副本，后续可能追加续写消息
        fragments: list[str] = []  # 收集续写片段
        prompt_too_long_retries = 0  # 输入过长重试次数（一次请求只压缩一次）
        transient_failures = 0  # 临时故障重试次数（429/529）
        state.has_attempted_reactive_compact = False  # 重置压缩标志

        while True:  # 恢复循环：直到成功或抛异常退出
            self._check_boundary()  # 检查取消和超时
            # 构造有效请求：使用当前模型和预算
            effective = ModelRequest(
                request_messages,
                request.tools,
                model=state.current_model,  # 可能是 primary 或 fallback
                max_tokens=state.current_max_tokens,  # 可能是 8000 或 64000
            )
            try:
                reply = self._model.complete(effective)  # 调用真实模型
                self._check_boundary()  # 调用后再次检查边界
            except ModelRateLimitError as error:  # 429 限流
                state.consecutive_529 = 0  # 清零 529 计数（429 说明模型可用）
                transient_failures += 1  # 临时故障计数 +1
                self._retry_transient(transient_failures, error.retry_after, "限流")
                continue  # 等待后重试
            except ModelOverloadedError:  # 529 过载
                state.consecutive_529 += 1  # 连续 529 计数 +1
                if state.consecutive_529 >= self._config.overload_fallback_threshold:
                    # 达到阈值（默认 3 次），切换到 fallback 模型
                    state.current_model = self._config.fallback_model
                    state.consecutive_529 = 0  # 切换后清零计数
                transient_failures += 1
                self._retry_transient(transient_failures, None, "模型过载")
                continue
            except ModelPromptTooLongError:  # 输入过长
                state.consecutive_529 = 0  # 清零 529 计数
                # 分离首条 system message（保留）和其余消息（可压缩）
                leading, compactable = _split_leading_system(request_messages)
                # 调用第 8 章的压缩管理器
                outcome = self._compaction.compact_on_prompt_too_long(
                    compactable, retry_count=prompt_too_long_retries
                )
                self._check_boundary()  # 压缩后检查边界
                prompt_too_long_retries += 1  # 压缩次数 +1
                state.has_attempted_reactive_compact = True  # 标记已压缩
                # 拼接：(system, *压缩后的历史)
                request_messages = (*leading, *outcome.history)
                validate_tool_pairing(request_messages)  # 校验配对完整性
                continue  # 压缩后重试

            # 成功拿到回复，清零临时故障计数
            transient_failures = 0
            state.consecutive_529 = 0
            # 检查 finish_reason
            if reply.finish_reason != "length":  # 不是截断，成功返回
                state.has_attempted_reactive_compact = False  # 清除压缩标志
                return _merge_fragments(reply, fragments)  # 合并续写片段（如果有）
            # finish_reason == "length"，输出被截断
            if not state.has_escalated:  # 第一次截断：升级预算
                state.current_max_tokens = self._config.escalated_max_tokens
                state.has_escalated = True
                continue  # 升级后重试
            # 第二次截断：启动续写机制
            fragment = reply.message.content
            # 续写要求非空纯文本片段，不能有 tool_calls
            if reply.message.tool_calls or fragment is None or not fragment:
                raise RecoveryRetriesExhausted("续写恢复要求非空纯文本片段")
            # 检查续写次数上限
            if state.recovery_count >= self._config.max_continuations:
                raise RecoveryRetriesExhausted("续写恢复次数已耗尽")
            fragments.append(fragment)  # 收集片段
            # 追加助手消息和续写提示，构造新请求
            request_messages = (
                *request_messages,
                reply.message,
                user_message(CONTINUATION_PROMPT),
            )
            validate_tool_pairing(request_messages)  # 校验配对完整性
            state.recovery_count += 1  # 续写次数 +1

    def _retry_transient(
        self, failures: int, retry_after: str | None, label: str
    ) -> None:
        """处理 429/529 的退避等待逻辑。

        这是什么：临时故障的退避重试协调器
        Java 类比：类似 Resilience4j Retry 的延迟计算
        为什么需要：统一退避策略，优先遵守 Retry-After，否则指数退避

        参数：
            failures: 当前失败次数（用于判断是否耗尽）
            retry_after: HTTP Retry-After 头（429 时存在）
            label: 日志标签（"限流" 或 "模型过载"）

        流程：
            1. 检查重试次数是否耗尽
            2. 计算延迟：优先解析 Retry-After，否则指数退避
            3. 检查延迟是否会超过 deadline
            4. 等待（可被取消）
            5. 等待后再次检查边界
        """
        # 检查重试次数上限
        if failures >= self._config.max_transient_attempts:
            raise RecoveryRetriesExhausted(f"{label}恢复次数已耗尽")
        # 计算延迟：429 优先用 Retry-After，否则指数退避
        delay = (
            self._parse_retry_after(retry_after)
            if retry_after is not None
            else self._backoff_delay(failures - 1)  # failures 从 1 开始，attempt 从 0 开始
        )
        # 检查延迟是否会超过 deadline
        if delay >= self._remaining_seconds():
            raise RecoveryDeadlineExceeded("等待时间会达到或超过当前回合 deadline")
        # 等待（可被取消令牌中断）
        self._sleeper(delay, self._cancellation)
        # 等待后再次检查边界（可能在等待期间被取消）
        self._check_boundary()

    def _parse_retry_after(self, value: str) -> float:
        """解析 Retry-After 头：支持秒数和 HTTP-date 两种格式。

        这是什么：HTTP 标准 Retry-After 头的解析器
        Java 类比：类似 DateTimeFormatter.parse() + Duration.between()
        为什么需要：RFC 7231 允许两种格式，必须都支持

        支持格式：
            1. 非负整数秒数：Retry-After: 120
            2. RFC 2822 HTTP-date：Retry-After: Wed, 21 Oct 2026 07:28:00 GMT

        参数：
            value: Retry-After 头的值

        返回：
            float: 需要等待的秒数（非负）

        异常：
            InvalidRetryAfterError: 解析失败
        """
        normalized = value.strip()
        # 尝试解析为秒数
        try:
            seconds = float(normalized)
        except ValueError:
            seconds = math.nan
        # 如果是非负有限数，直接返回
        if normalized and math.isfinite(seconds) and seconds >= 0:
            return seconds
        # 否则尝试解析为 HTTP-date
        try:
            target = parsedate_to_datetime(normalized)  # RFC 2822 格式
        except (TypeError, ValueError, OverflowError) as error:
            raise InvalidRetryAfterError("Retry-After 不是秒数或 HTTP-date") from error
        # HTTP-date 必须包含时区
        if target.tzinfo is None:
            raise InvalidRetryAfterError("Retry-After HTTP-date 必须包含时区")
        now = self._utc_now()
        if now.tzinfo is None:
            raise RecoveryError("utc_now 必须返回带时区 datetime")
        # 计算目标时间与当前时间的差值（至少为 0）
        return max(0.0, (target - now).total_seconds())

    def _backoff_delay(self, attempt: int) -> float:
        """计算指数退避延迟：base * 2^attempt + jitter。

        这是什么：带随机抖动的指数退避算法
        Java 类比：类似 Resilience4j ExponentialBackoff
        为什么需要：避免惊群效应，分散重试时间

        公式：
            base = min(base_delay * 2^attempt, max_delay)
            jitter = random(0, base * jitter_ratio)
            delay = base + jitter

        参数：
            attempt: 重试次数（从 0 开始）

        返回：
            float: 延迟秒数

        示例（base=0.5, max=32, jitter_ratio=0.25）：
            attempt=0 → 0.5 + random(0, 0.125) = 0.5~0.625s
            attempt=1 → 1.0 + random(0, 0.25) = 1.0~1.25s
            attempt=2 → 2.0 + random(0, 0.5) = 2.0~2.5s
            attempt=6 → 32.0 + random(0, 8.0) = 32~40s（达到上限）
        """
        # 计算基础延迟：指数增长，但不超过最大值
        base = float(min(
            self._config.base_delay_seconds * (2**attempt),
            self._config.max_delay_seconds,
        ))
        # 计算抖动上限
        upper = base * self._config.jitter_ratio
        # 生成随机抖动
        jitter = float(self._jitter(upper))
        # 校验抖动合法性（测试钩子可能返回非法值）
        if not math.isfinite(jitter) or jitter < 0 or jitter > upper:
            raise RecoveryError("jitter 返回值必须位于合法范围")
        return base + jitter

    def _check_boundary(self) -> None:
        """检查取消和超时边界条件。

        这是什么：边界条件检查点
        Java 类比：类似 Thread.interrupted() 或 Future.isCancelled()
        为什么需要：及时响应取消和超时，避免浪费资源

        调用时机：
            - 每次模型请求前后
            - 每次退避等待前后
            - 每次压缩前后
        """
        if self._cancellation.is_cancelled:  # 检查取消令牌
            raise RecoveryCancelledError("当前恢复回合已取消")
        if self._remaining_seconds() <= 0:  # 检查是否超时
            raise RecoveryDeadlineExceeded("当前恢复回合已超过总时限")

    def _remaining_seconds(self) -> float:
        """计算当前回合剩余时间（秒）。

        Java 对照：类似 deadline - System.currentTimeMillis()
        """
        if self._deadline is None:
            raise RecoveryError("尚未开始恢复回合")
        return self._deadline - self._now()

    def _now(self) -> float:
        """获取当前单调时钟值（秒）。

        Java 对照：类似 System.nanoTime() / 1e9
        为什么用单调时钟：不受系统时间调整影响，适合计时
        """
        value = self._monotonic()
        if not math.isfinite(value):
            raise RecoveryError("monotonic 必须返回有限数")
        return value

    def _require_state(self) -> RecoveryState:
        """确保已调用 begin_turn()，返回状态对象。

        Java 对照：类似 requireNonNull() 或 checkState()
        """
        if self._state is None:
            raise RecoveryError("尚未开始恢复回合")
        return self._state


def _sleep(seconds: float, cancellation: CancellationToken) -> None:
    """用 Event.wait 代替 time.sleep，使退避等待能被取消。

    这是什么：可取消的等待函数
    Java 类比：类似 Thread.sleep() 但响应中断
    为什么需要：time.sleep() 无法被中断，Event.wait() 能响应取消令牌

    实现原理：
        1. 创建 Event 对象（初始为未设置状态）
        2. 订阅取消令牌，取消时设置 Event
        3. 调用 Event.wait(seconds)，最多等待指定秒数
        4. 如果 wait 返回 True（被设置），说明被取消了

    参数：
        seconds: 等待秒数
        cancellation: 取消令牌

    异常：
        RecoveryCancelledError: 等待期间被取消
    """
    event = threading.Event()  # 创建事件对象
    unsubscribe = cancellation.subscribe(event.set)  # 取消时设置事件
    try:
        # wait() 返回 True 表示事件被设置（取消），False 表示超时
        if event.wait(seconds):
            raise RecoveryCancelledError("当前恢复回合已取消")
    finally:
        unsubscribe()  # 无论如何都要取消订阅，避免内存泄漏


def _split_leading_system(
    messages: tuple[ChatMessage, ...],
) -> tuple[tuple[ChatMessage, ...], tuple[ChatMessage, ...]]:
    """分离首条 system message 和其余消息。

    这是什么：输入过长时的消息分割器
    Java 类比：类似 List.subList(0, 1) 和 List.subList(1, n)
    为什么需要：压缩时保留 system message（规则），只压缩对话历史

    返回：
        (leading, compactable): leading 是首条 system（或空），compactable 是其余消息

    示例：
        [system, user, assistant, user] → ([system], [user, assistant, user])
        [user, assistant] → ([], [user, assistant])
    """
    if messages and isinstance(messages[0], SystemMessage):
        return (messages[0],), messages[1:]  # 有 system，分离出来
    return (), messages  # 没有 system，全部可压缩


def _merge_fragments(reply: ModelReply, fragments: list[str]) -> ModelReply:
    """合并续写片段，返回完整的 ModelReply。

    这是什么：续写片段的合并器
    Java 类比：类似 String.join("", fragments) + finalText
    为什么需要：外层只看到一条完整消息，感知不到内部续写

    参数：
        reply: 最后一次成功的回复
        fragments: 之前续写的所有片段

    返回：
        ModelReply: 内容为所有片段拼接后的完整回复

    示例：
        fragments = ["第一段...", "第二段..."]
        reply.content = "第三段（完）"
        → 返回内容为 "第一段...第二段...第三段（完）"
    """
    if not fragments:  # 没有续写，直接返回
        return reply
    final = reply.message.content or ""  # 最后一段内容
    # 拼接所有片段和最后一段
    return ModelReply(
        assistant_message("".join((*fragments, final)), reply.message.tool_calls),
        reply.finish_reason,
        reply.usage,
    )
