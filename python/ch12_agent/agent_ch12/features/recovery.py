"""第十一章：供应商无关的模型请求恢复层。

Java 对照：``RecoveryManager`` 类似包在 HTTP Client 外面的 Resilience Service。
它接收一次逻辑 ``ModelRequest``，内部完成预算升级、续写、压缩、退避和模型切换，
最后只向 AgentRunner 返回一个完整 ``ModelReply``。
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

DEFAULT_INITIAL_MAX_TOKENS = 8_000
DEFAULT_ESCALATED_MAX_TOKENS = 64_000
DEFAULT_MAX_CONTINUATIONS = 3
DEFAULT_MAX_TRANSIENT_ATTEMPTS = 10
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 32.0
DEFAULT_JITTER_RATIO = 0.25
DEFAULT_OVERLOAD_FALLBACK_THRESHOLD = 3
DEFAULT_TOTAL_TIMEOUT_SECONDS = 300.0
CONTINUATION_PROMPT = (
    "Continue exactly where you left off. Do not repeat any text, no apology, "
    "no recap. Pick up mid-thought."
)


class RecoveryError(Exception):
    """恢复流程公共异常。"""


class InvalidRetryAfterError(RecoveryError):
    """Retry-After 既不是非负秒数，也不是带时区 HTTP-date。"""


class RecoveryCancelledError(RecoveryError):
    """调用方主动取消当前恢复回合。"""


class RecoveryDeadlineExceeded(RecoveryError):
    """当前用户回合的总 deadline 已耗尽。"""


class RecoveryRetriesExhausted(RecoveryError):
    """瞬态重试或续写次数已用完。"""


class CancellationToken:
    """轻量取消令牌，类似 Java 中共享的 ``AtomicBoolean + listeners``。"""

    def __init__(self) -> None:
        self._cancelled = False
        self._listeners: set[Callable[[], None]] = set()
        self._lock = threading.Lock()

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        """幂等取消，并且每个监听器最多调用一次。"""
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            listeners = tuple(self._listeners)
            self._listeners.clear()
        for listener in listeners:
            listener()

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """注册监听器；已取消时立即调用并返回空退订函数。"""
        if not callable(listener):
            raise TypeError("listener 必须可调用")
        with self._lock:
            if self._cancelled:
                immediate = True
            else:
                self._listeners.add(listener)
                immediate = False
        if immediate:
            listener()
            return lambda: None

        def unsubscribe() -> None:
            with self._lock:
                self._listeners.discard(listener)

        return unsubscribe


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    """不可变恢复配置，类似 Java ``record RecoveryConfig``。"""

    primary_model: str
    fallback_model: str
    initial_max_tokens: int = DEFAULT_INITIAL_MAX_TOKENS
    escalated_max_tokens: int = DEFAULT_ESCALATED_MAX_TOKENS
    model_max_tokens: int = DEFAULT_ESCALATED_MAX_TOKENS
    max_continuations: int = DEFAULT_MAX_CONTINUATIONS
    max_transient_attempts: int = DEFAULT_MAX_TRANSIENT_ATTEMPTS
    base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS
    max_delay_seconds: float = DEFAULT_MAX_DELAY_SECONDS
    jitter_ratio: float = DEFAULT_JITTER_RATIO
    overload_fallback_threshold: int = DEFAULT_OVERLOAD_FALLBACK_THRESHOLD
    total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.primary_model.strip() or not self.fallback_model.strip():
            raise ValueError("primary_model 和 fallback_model 不能为空")
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
        if self.max_continuations < 0:
            raise ValueError("max_continuations 不能为负数")
        for name in ("base_delay_seconds", "max_delay_seconds", "total_timeout_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} 必须是正有限数")
        if not math.isfinite(self.jitter_ratio) or self.jitter_ratio < 0:
            raise ValueError("jitter_ratio 必须是非负有限数")
        if self.initial_max_tokens >= self.escalated_max_tokens:
            raise ValueError("escalated_max_tokens 必须大于 initial_max_tokens")
        if self.escalated_max_tokens > self.model_max_tokens:
            raise ValueError("escalated_max_tokens 不能超过 model_max_tokens")
        if self.base_delay_seconds > self.max_delay_seconds:
            raise ValueError("base_delay_seconds 不能超过 max_delay_seconds")


@dataclass(slots=True)
class RecoveryState:
    """当前用户回合的可变恢复状态。"""

    current_model: str
    current_max_tokens: int
    has_escalated: bool = False
    recovery_count: int = 0
    consecutive_529: int = 0
    has_attempted_reactive_compact: bool = False


class RecoveryManager:
    """一次逻辑模型请求的唯一恢复执行器。"""

    def __init__(
        self,
        model: ModelClient,
        compaction: CompactionManager,
        config: RecoveryConfig,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
        sleeper: Callable[[float, CancellationToken], None] | None = None,
        jitter: Callable[[float], float] | None = None,
        cancellation: CancellationToken | None = None,
    ) -> None:
        self._model = model
        self._compaction = compaction
        self._config = config
        self._monotonic = monotonic
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._sleeper = sleeper or _sleep
        self._jitter = jitter or (lambda upper: random.uniform(0, upper))
        self._cancellation = cancellation or CancellationToken()
        self._state: RecoveryState | None = None
        self._deadline: float | None = None

    @property
    def state(self) -> RecoveryState:
        """返回状态副本，外部不能修改内部计数。"""
        state = self._require_state()
        return RecoveryState(
            state.current_model,
            state.current_max_tokens,
            state.has_escalated,
            state.recovery_count,
            state.consecutive_529,
            state.has_attempted_reactive_compact,
        )

    def begin_turn(self) -> None:
        """每个用户回合重置模型、预算、计数和总 deadline。"""
        started = self._now()
        self._state = RecoveryState(
            self._config.primary_model, self._config.initial_max_tokens
        )
        self._deadline = started + self._config.total_timeout_seconds

    def complete(self, request: ModelRequest) -> ModelReply:
        """完成一个逻辑请求；内部尝试不会进入外层 Agent turn。"""
        state = self._require_state()
        validate_tool_pairing(request.messages)
        if request.model is not None and request.model != self._config.primary_model:
            raise ValueError("request.model 必须匹配 RecoveryConfig.primary_model")
        if request.max_tokens is not None and request.max_tokens != self._config.initial_max_tokens:
            raise ValueError("request.max_tokens 必须匹配 initial_max_tokens")

        request_messages = tuple(request.messages)
        fragments: list[str] = []
        prompt_too_long_retries = 0
        transient_failures = 0
        state.has_attempted_reactive_compact = False

        while True:
            self._check_boundary()
            effective = ModelRequest(
                request_messages,
                request.tools,
                model=state.current_model,
                max_tokens=state.current_max_tokens,
            )
            try:
                reply = self._model.complete(effective)
                self._check_boundary()
            except ModelRateLimitError as error:
                state.consecutive_529 = 0
                transient_failures += 1
                self._retry_transient(transient_failures, error.retry_after, "限流")
                continue
            except ModelOverloadedError:
                state.consecutive_529 += 1
                if state.consecutive_529 >= self._config.overload_fallback_threshold:
                    state.current_model = self._config.fallback_model
                    state.consecutive_529 = 0
                transient_failures += 1
                self._retry_transient(transient_failures, None, "模型过载")
                continue
            except ModelPromptTooLongError:
                state.consecutive_529 = 0
                leading, compactable = _split_leading_system(request_messages)
                outcome = self._compaction.compact_on_prompt_too_long(
                    compactable, retry_count=prompt_too_long_retries
                )
                self._check_boundary()
                prompt_too_long_retries += 1
                state.has_attempted_reactive_compact = True
                request_messages = (*leading, *outcome.history)
                validate_tool_pairing(request_messages)
                continue

            transient_failures = 0
            state.consecutive_529 = 0
            if reply.finish_reason != "length":
                state.has_attempted_reactive_compact = False
                return _merge_fragments(reply, fragments)
            if not state.has_escalated:
                state.current_max_tokens = self._config.escalated_max_tokens
                state.has_escalated = True
                continue
            fragment = reply.message.content
            if reply.message.tool_calls or fragment is None or not fragment:
                raise RecoveryRetriesExhausted("续写恢复要求非空纯文本片段")
            if state.recovery_count >= self._config.max_continuations:
                raise RecoveryRetriesExhausted("续写恢复次数已耗尽")
            fragments.append(fragment)
            request_messages = (
                *request_messages,
                reply.message,
                user_message(CONTINUATION_PROMPT),
            )
            validate_tool_pairing(request_messages)
            state.recovery_count += 1

    def _retry_transient(
        self, failures: int, retry_after: str | None, label: str
    ) -> None:
        if failures >= self._config.max_transient_attempts:
            raise RecoveryRetriesExhausted(f"{label}恢复次数已耗尽")
        delay = (
            self._parse_retry_after(retry_after)
            if retry_after is not None
            else self._backoff_delay(failures - 1)
        )
        if delay >= self._remaining_seconds():
            raise RecoveryDeadlineExceeded("等待时间会达到或超过当前回合 deadline")
        self._sleeper(delay, self._cancellation)
        self._check_boundary()

    def _parse_retry_after(self, value: str) -> float:
        normalized = value.strip()
        try:
            seconds = float(normalized)
        except ValueError:
            seconds = math.nan
        if normalized and math.isfinite(seconds) and seconds >= 0:
            return seconds
        try:
            target = parsedate_to_datetime(normalized)
        except (TypeError, ValueError, OverflowError) as error:
            raise InvalidRetryAfterError("Retry-After 不是秒数或 HTTP-date") from error
        if target.tzinfo is None:
            raise InvalidRetryAfterError("Retry-After HTTP-date 必须包含时区")
        now = self._utc_now()
        if now.tzinfo is None:
            raise RecoveryError("utc_now 必须返回带时区 datetime")
        return max(0.0, (target - now).total_seconds())

    def _backoff_delay(self, attempt: int) -> float:
        base = float(min(
            self._config.base_delay_seconds * (2**attempt),
            self._config.max_delay_seconds,
        ))
        upper = base * self._config.jitter_ratio
        jitter = float(self._jitter(upper))
        if not math.isfinite(jitter) or jitter < 0 or jitter > upper:
            raise RecoveryError("jitter 返回值必须位于合法范围")
        return base + jitter

    def _check_boundary(self) -> None:
        if self._cancellation.is_cancelled:
            raise RecoveryCancelledError("当前恢复回合已取消")
        if self._remaining_seconds() <= 0:
            raise RecoveryDeadlineExceeded("当前恢复回合已超过总时限")

    def _remaining_seconds(self) -> float:
        if self._deadline is None:
            raise RecoveryError("尚未开始恢复回合")
        return self._deadline - self._now()

    def _now(self) -> float:
        value = self._monotonic()
        if not math.isfinite(value):
            raise RecoveryError("monotonic 必须返回有限数")
        return value

    def _require_state(self) -> RecoveryState:
        if self._state is None:
            raise RecoveryError("尚未开始恢复回合")
        return self._state


def _sleep(seconds: float, cancellation: CancellationToken) -> None:
    """用 Event.wait 代替 time.sleep，使退避等待能被取消。"""
    event = threading.Event()
    unsubscribe = cancellation.subscribe(event.set)
    try:
        if event.wait(seconds):
            raise RecoveryCancelledError("当前恢复回合已取消")
    finally:
        unsubscribe()


def _split_leading_system(
    messages: tuple[ChatMessage, ...],
) -> tuple[tuple[ChatMessage, ...], tuple[ChatMessage, ...]]:
    if messages and isinstance(messages[0], SystemMessage):
        return (messages[0],), messages[1:]
    return (), messages


def _merge_fragments(reply: ModelReply, fragments: list[str]) -> ModelReply:
    if not fragments:
        return reply
    final = reply.message.content or ""
    return ModelReply(
        assistant_message("".join((*fragments, final)), reply.message.tool_calls),
        reply.finish_reason,
        reply.usage,
    )
