"""第十四章 Cron 表达式、时区和事件模型测试。"""

import datetime as dt
import json

import pytest

from agent_ch16.features.cron import (
    CronEvent,
    CronExpressionError,
    next_cron_occurrence,
    validate_cron_expression,
    validate_cron_timezone,
)

JOB = "00000000-0000-4000-8000-000000000401"
EVENT = "00000000-0000-4000-8000-000000000402"


def test_cron_supports_lists_ranges_steps_and_dom_dow_or() -> None:
    assert validate_cron_expression("*/15 9-10 * * 1,3,5") == "*/15 9-10 * * 1,3,5"
    base = dt.datetime(2026, 6, 1, 0, 30, tzinfo=dt.UTC)
    assert next_cron_occurrence("0 9 * * *", "Asia/Shanghai", base) == dt.datetime(
        2026, 6, 1, 1, tzinfo=dt.UTC
    )
    assert next_cron_occurrence(
        "0 9 1 * 1", "UTC", dt.datetime(2026, 6, 1, 9, 1, tzinfo=dt.UTC)
    ) == dt.datetime(2026, 6, 8, 9, tzinfo=dt.UTC)


def test_cron_rejects_bad_expression_timezone_and_naive_time() -> None:
    with pytest.raises(CronExpressionError):
        validate_cron_expression("0 9 * *")
    with pytest.raises(CronExpressionError):
        validate_cron_timezone("Mars/Phobos")
    with pytest.raises(CronExpressionError):
        next_cron_occurrence("* * * * *", "UTC", dt.datetime.now(dt.UTC).replace(tzinfo=None))


def test_dst_gap_and_fold_are_explicit() -> None:
    gap = next_cron_occurrence(
        "30 2 * * *", "America/New_York", dt.datetime(2026, 3, 8, 6, tzinfo=dt.UTC)
    )
    assert gap == dt.datetime(2026, 3, 8, 7, tzinfo=dt.UTC)
    fold = next_cron_occurrence(
        "30 1 * * *", "America/New_York", dt.datetime(2026, 11, 1, 5, 30, tzinfo=dt.UTC)
    )
    assert fold == dt.datetime(2026, 11, 1, 6, 30, tzinfo=dt.UTC)


def test_cron_event_payload_has_context_identity_and_idempotency() -> None:
    event = CronEvent(
        EVENT,
        JOB,
        "cron-owner",
        "检查 CI",
        "Asia/Shanghai",
        True,
        dt.datetime(2026, 6, 1, 1, tzinfo=dt.UTC),
        context_identity="cron-owner",
        idempotency_key=EVENT,
    )
    payload = json.loads(json.dumps(event.to_payload(), ensure_ascii=False))
    assert event.context_identity == "cron-owner"
    assert event.idempotency_key == EVENT
    assert payload["kind"] == "cron"
