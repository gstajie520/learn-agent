import json
from pathlib import Path

import pytest

from agent_ch10.core.messages import (
    assistant_message,
    system_message,
    tool_call,
    tool_message,
    user_message,
)
from agent_ch10.core.tools import tool_error, tool_success
from agent_ch10.features.compaction import (
    COMPACTED_TOOL_RESULT,
    ArtifactConflictError,
    CompactionManager,
    CompactionSummary,
    PromptTooLongRetryError,
    history_utf8_bytes,
    micro_compact_history,
    serialize_transcript,
    snip_compact_history,
)


class RecordingSummarizer:
    """记录收到的历史，并返回固定摘要。"""

    def __init__(self) -> None:
        self.histories = []

    def summarize(self, history):
        self.histories.append(history)
        return CompactionSummary(
            "继续迁移第九章",
            ("按完整消息组压缩",),
            ("agent_ch10/features/compaction.py",),
            ("运行测试",),
            ("不能拆散工具消息",),
        )


def ids(*values: str):
    iterator = iter(values)
    return lambda: next(iterator)


def exchange(call_id: str, content: str):
    return (
        assistant_message(None, (tool_call(call_id, "read_file", '{}'),)),
        tool_message(content, call_id),
    )


def test_persists_result_above_utf8_threshold_and_preserves_error_metadata(tmp_path: Path):
    manager = CompactionManager(
        str(tmp_path), RecordingSummarizer(), id_generator=ids("large"),
        persist_threshold_bytes=8, batch_budget_bytes=100,
        preview_head_bytes=4, preview_tail_bytes=4,
    )
    outcome = manager.compact_tool_results((tool_error("read_failed", "甲甲甲"),))
    assert outcome.artifacts[0].reference.original_bytes > 8
    assert Path(outcome.artifacts[0].reference.path).read_text(encoding="utf-8").endswith("甲甲甲")
    assert outcome.results[0].is_error is True
    assert outcome.results[0].error_code == "read_failed"
    assert "persisted-tool-result" in outcome.results[0].content


def test_batch_failure_removes_created_artifacts_and_never_overwrites(tmp_path: Path):
    root = tmp_path / ".agent_tutorial" / "artifacts"
    root.mkdir(parents=True)
    conflict = root / "tool-result-conflict.txt"
    conflict.write_text("旧内容", encoding="utf-8")
    manager = CompactionManager(
        str(tmp_path), RecordingSummarizer(), id_generator=ids("created", "conflict"),
        persist_threshold_bytes=1, batch_budget_bytes=100,
    )
    with pytest.raises(ArtifactConflictError):
        manager.compact_tool_results((tool_success("first"), tool_success("other")))
    assert not (root / "tool-result-created.txt").exists()
    assert conflict.read_text(encoding="utf-8") == "旧内容"


def test_batch_budget_persists_largest_inline_result_first(tmp_path: Path):
    """即使单项未超过阈值，只要整批超预算，也要按从大到小继续落盘。"""
    manager = CompactionManager(
        str(tmp_path), RecordingSummarizer(), id_generator=ids("largest"),
        persist_threshold_bytes=100, batch_budget_bytes=9,
    )
    original = (tool_error("read_failed", "123456"), tool_success("12345"), tool_success("1234"))
    outcome = manager.compact_tool_results(original)
    assert [artifact.result_index for artifact in outcome.artifacts] == [0]
    assert outcome.results[0].is_error is True
    assert outcome.results[0].error_code == "read_failed"
    assert outcome.results[1:] == original[1:]


def test_micro_and_snip_keep_tool_pairs_atomic():
    history = (
        user_message("head"),
        *exchange("old-1", "old one"),
        *exchange("old-2", "old two"),
        *exchange("new", "new result"),
    )
    micro = micro_compact_history(history, keep_recent_tool_groups=1)
    assert micro[2] == tool_message(COMPACTED_TOOL_RESULT, "old-1")
    assert micro[4] == tool_message(COMPACTED_TOOL_RESULT, "old-2")
    assert micro[6] == tool_message("new result", "new")

    longer = (
        user_message("head"), system_message("middle"), *exchange("middle-tool", "paired"),
        user_message("middle-2"), *exchange("tail-tool", "tail"), assistant_message("done"),
    )
    snipped = snip_compact_history(longer, max_groups=4, keep_head_groups=1)
    assert snipped[1] == system_message("[Compacted: 3 message groups omitted]")
    assert snipped[-3:] == (*exchange("tail-tool", "tail"), assistant_message("done"))


def test_transcript_uses_stable_jsonl_and_real_utf8_bytes():
    history = (user_message("甲"), *exchange("call-1", "乙"))
    transcript = serialize_transcript(history)
    assert transcript.endswith("\n")
    assert history_utf8_bytes(history) == len(transcript.encode("utf-8"))
    parsed = [json.loads(line) for line in transcript.splitlines()]
    assert parsed[-1]["tool_call_id"] == "call-1"


def test_proactive_compaction_persists_transcript_then_returns_structured_summary(tmp_path: Path):
    summarizer = RecordingSummarizer()
    manager = CompactionManager(str(tmp_path), summarizer, id_generator=ids("transcript"))
    history = (user_message("start"), *exchange("call-1", "full result"))
    outcome = manager.compact_proactively(history)
    summary = json.loads(outcome.history[0].content)
    assert summary["kind"] == "compacted_history"
    assert summary["current_goal"] == "继续迁移第九章"
    assert summary["transcript_path"].endswith("transcript-transcript.jsonl")
    assert '"tool_call_id":"call-1"' in Path(outcome.transcript.path).read_text(encoding="utf-8")


def test_prepare_caches_equal_history_and_reuses_compressed_prefix(tmp_path: Path):
    summarizer = RecordingSummarizer()
    manager = CompactionManager(
        str(tmp_path), summarizer, keep_recent_tool_groups=0, proactive_threshold_bytes=100_000
    )
    first = (user_message("start"), *exchange("old", "large old result"))
    prepared = manager.prepare(first)
    cached = manager.prepare((user_message("start"), *exchange("old", "large old result")))
    appended = manager.prepare((*first, user_message("next")))
    assert cached is prepared
    assert prepared[2] == tool_message(COMPACTED_TOOL_RESULT, "old")
    assert appended == (*prepared, user_message("next"))
    assert first[2] == tool_message("large old result", "old")


def test_prompt_too_long_compaction_only_runs_once_per_retry_window(tmp_path: Path):
    manager = CompactionManager(
        str(tmp_path), RecordingSummarizer(), id_generator=ids("reactive"), reactive_tail_groups=2
    )
    history = (user_message("old"), system_message("middle"), *exchange("recent", "data"))
    outcome = manager.compact_on_prompt_too_long(history)
    assert outcome.history[1:] == (system_message("middle"), *exchange("recent", "data"))
    with pytest.raises(PromptTooLongRetryError):
        manager.compact_on_prompt_too_long(history, retry_count=1)
