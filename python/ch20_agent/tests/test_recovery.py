"""第十一章恢复层的单元测试。

Java 阅读提示：这里的 ``ActionModel`` 就是手写的 Mockito Stub。
它把每次请求记到 ``requests`` 中，使断言能验证重试策略实际发了什么请求，
而不是只检查最终文字“看起来对”。
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent_ch20.core.messages import assistant_message, system_message, user_message
from agent_ch20.core.model import (
    ModelOverloadedError,
    ModelPromptTooLongError,
    ModelRateLimitError,
    ModelReply,
    ModelRequest,
)
from agent_ch20.features.compaction import ArtifactReference, HistoryCompactionOutcome
from agent_ch20.features.recovery import (
    CONTINUATION_PROMPT,
    CancellationToken,
    InvalidRetryAfterError,
    RecoveryCancelledError,
    RecoveryConfig,
    RecoveryDeadlineExceeded,
    RecoveryManager,
)


class ActionModel:
    """按顺序执行回复或异常的模型假对象，类似 Java 测试里的队列 Stub。"""

    def __init__(self, actions: list[ModelReply | Exception]) -> None:
        self.actions = list(actions)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        if not self.actions:
            raise AssertionError("模型脚本没有剩余动作")
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


class FakeCompaction:
    """只记录压缩输入，避免恢复单测依赖磁盘和摘要模型。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], int]] = []

    def compact_on_prompt_too_long(
        self, history: tuple[object, ...], retry_count: int = 0
    ) -> HistoryCompactionOutcome:
        self.calls.append((history, retry_count))
        return HistoryCompactionOutcome(
            (system_message("压缩摘要"), user_message("保留的最新请求")),
            ArtifactReference("C:/tmp/transcript.jsonl", ".agent_tutorial/transcript.jsonl", 1),
        )


def _config(**overrides: object) -> RecoveryConfig:
    values: dict[str, object] = {
        "primary_model": "primary",
        "fallback_model": "fallback",
        "total_timeout_seconds": 30,
        "jitter_ratio": 0,
    }
    values.update(overrides)
    return RecoveryConfig(**values)  # type: ignore[arg-type]


def _request() -> ModelRequest:
    return ModelRequest((system_message("规则"), user_message("开始工作")), ())


def _manager(
    model: ActionModel,
    *,
    config: RecoveryConfig | None = None,
    compaction: FakeCompaction | None = None,
    sleeper: object | None = None,
    cancellation: CancellationToken | None = None,
    monotonic: object | None = None,
    utc_now: object | None = None,
) -> RecoveryManager:
    kwargs: dict[str, object] = {"sleeper": sleeper, "cancellation": cancellation}
    if monotonic is not None:
        kwargs["monotonic"] = monotonic
    if utc_now is not None:
        kwargs["utc_now"] = utc_now
    return RecoveryManager(model, compaction or FakeCompaction(), config or _config(), **kwargs)  # type: ignore[arg-type]


def test_recovery_config_rejects_invalid_budgets_and_error_statuses() -> None:
    with pytest.raises(ValueError, match="必须大于"):
        _config(initial_max_tokens=64_000, escalated_max_tokens=64_000)
    with pytest.raises(ValueError, match="不能超过"):
        _config(escalated_max_tokens=64_001)
    with pytest.raises(ValueError, match="不能超过"):
        _config(base_delay_seconds=2, max_delay_seconds=1)
    with pytest.raises(ValueError, match="status_code"):
        ModelRateLimitError("限流", status_code=500)
    with pytest.raises(ValueError, match="status_code"):
        ModelOverloadedError("过载", status_code=429)


def test_first_length_reply_is_discarded_and_uses_escalated_budget() -> None:
    model = ActionModel(
        [
            ModelReply(assistant_message("半截回答"), "length"),
            ModelReply(assistant_message("完整回答"), "stop"),
        ]
    )
    manager = _manager(model)
    manager.begin_turn()
    reply = manager.complete(_request())
    assert reply.message.content == "完整回答"
    assert [request.max_tokens for request in model.requests] == [8_000, 64_000]


def test_second_length_reply_continues_only_in_request_snapshot_and_merges_text() -> None:
    request = _request()
    model = ActionModel(
        [
            ModelReply(assistant_message("忽略"), "length"),
            ModelReply(assistant_message("第一段"), "length"),
            ModelReply(assistant_message("第二段"), "stop"),
        ]
    )
    manager = _manager(model)
    manager.begin_turn()
    reply = manager.complete(request)
    assert reply.message.content == "第一段第二段"
    assert request.messages == _request().messages
    continuation_request = model.requests[2]
    assert continuation_request.messages[-1] == user_message(CONTINUATION_PROMPT)
    assert continuation_request.messages[-2] == assistant_message("第一段")


def test_rate_limit_honors_seconds_and_http_date_and_rejects_invalid_value() -> None:
    sleeps: list[float] = []
    model = ActionModel(
        [
            ModelRateLimitError("限流", retry_after="1.5"),
            ModelReply(assistant_message("好"), "stop"),
        ]
    )
    manager = _manager(model, sleeper=lambda seconds, _: sleeps.append(seconds))
    manager.begin_turn()
    assert manager.complete(_request()).message.content == "好"
    assert sleeps == [1.5]

    clock = datetime(2026, 1, 1, tzinfo=UTC)
    model = ActionModel(
        [
            ModelRateLimitError(
                "限流",
                retry_after=(clock + timedelta(seconds=2)).strftime("%a, %d %b %Y %H:%M:%S GMT"),
            ),
            ModelReply(assistant_message("好"), "stop"),
        ]
    )
    sleeps = []
    manager = _manager(
        model, sleeper=lambda seconds, _: sleeps.append(seconds), utc_now=lambda: clock
    )
    manager.begin_turn()
    manager.complete(_request())
    assert sleeps == [2.0]

    manager = _manager(ActionModel([]))
    manager.begin_turn()
    with pytest.raises(InvalidRetryAfterError):
        manager._parse_retry_after("不是合法头")


def test_overload_switches_to_fallback_after_threshold() -> None:
    model = ActionModel(
        [
            ModelOverloadedError("过载"),
            ModelOverloadedError("过载"),
            ModelOverloadedError("过载"),
            ModelReply(assistant_message("恢复成功"), "stop"),
        ]
    )
    manager = _manager(model, sleeper=lambda _seconds, _token: None)
    manager.begin_turn()
    manager.complete(_request())
    assert [request.model for request in model.requests] == [
        "primary",
        "primary",
        "primary",
        "fallback",
    ]


def test_prompt_too_long_keeps_leading_system_and_compacts_only_once() -> None:
    compaction = FakeCompaction()
    model = ActionModel(
        [
            ModelPromptTooLongError("太长"),
            ModelReply(assistant_message("成功"), "stop"),
        ]
    )
    manager = _manager(model, compaction=compaction)
    manager.begin_turn()
    assert manager.complete(_request()).message.content == "成功"
    assert compaction.calls[0][0] == (user_message("开始工作"),)
    assert model.requests[1].messages[0] == system_message("规则")
    assert model.requests[1].messages[1:] == (
        system_message("压缩摘要"),
        user_message("保留的最新请求"),
    )


def test_deadline_and_pre_cancelled_turn_stop_before_network_request() -> None:
    model = ActionModel([ModelReply(assistant_message("不应调用"), "stop")])
    cancelled = CancellationToken()
    cancelled.cancel()
    manager = _manager(model, cancellation=cancelled)
    manager.begin_turn()
    with pytest.raises(RecoveryCancelledError):
        manager.complete(_request())
    assert model.requests == []

    ticks = iter([0.0, 2.0])
    manager = _manager(
        ActionModel([ModelReply(assistant_message("不应调用"), "stop")]),
        config=_config(total_timeout_seconds=1),
        monotonic=lambda: next(ticks),
    )
    manager.begin_turn()
    with pytest.raises(RecoveryDeadlineExceeded):
        manager.complete(_request())


def test_unknown_errors_are_not_wrapped_or_retried() -> None:
    original = RuntimeError("供应商未知异常")
    model = ActionModel([original])
    manager = _manager(model)
    manager.begin_turn()
    with pytest.raises(RuntimeError) as error:
        manager.complete(_request())
    assert error.value is original
    assert len(model.requests) == 1
