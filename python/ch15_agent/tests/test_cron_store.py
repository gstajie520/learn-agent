"""Cron JSON Repository 的 durable/session/outbox 测试。"""

import datetime as dt

from agent_ch15.adapters.cron_json import JsonCronStore

JOB = "00000000-0000-4000-8000-000000000411"
EVENT = "00000000-0000-4000-8000-000000000412"
BASE = dt.datetime(2026, 6, 1, 12, 0, 30, tzinfo=dt.UTC)


def make_input(*, durable: bool, recurring: bool) -> dict[str, object]:
    return {
        "cron": "* * * * *",
        "prompt": "检查 CI",
        "timezone": "UTC",
        "recurring": recurring,
        "durable": durable,
        "identity": "owner",
        "now_utc": BASE,
    }


def test_durable_job_and_outbox_recover(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = JsonCronStore(str(tmp_path), id_generator=lambda: JOB, event_id_generator=lambda: EVENT)
    job = store.schedule_cron(make_input(durable=True, recurring=False))
    events = store.tick(job.next_run_at_utc)
    assert [event.event_id for event in events] == [EVENT]
    restarted = JsonCronStore(str(tmp_path))
    assert restarted.list_jobs() == ()
    assert [event.event_id for event in restarted.pending_events()] == [EVENT]


def test_one_shot_removes_job_but_ack_keeps_event_until_consumed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = JsonCronStore(str(tmp_path), id_generator=lambda: JOB, event_id_generator=lambda: EVENT)
    job = store.schedule_cron(make_input(durable=True, recurring=False))
    store.tick(job.next_run_at_utc)
    assert store.list_jobs() == ()
    assert store.ack_event(EVENT)
    assert not store.ack_event(EVENT)
    assert store.pending_events() == ()


def test_recurring_tick_advances_beyond_misfire_time(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = JsonCronStore(str(tmp_path), id_generator=lambda: JOB, event_id_generator=lambda: EVENT)
    job = store.schedule_cron(make_input(durable=True, recurring=True))
    store.tick(job.next_run_at_utc + dt.timedelta(hours=3))
    updated = store.get_job(JOB)
    assert updated.last_slot_at_utc == job.next_run_at_utc
    assert updated.next_run_at_utc > job.next_run_at_utc + dt.timedelta(hours=3)
