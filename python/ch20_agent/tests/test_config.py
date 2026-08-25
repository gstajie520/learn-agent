import pytest

from agent_ch20.config import ConfigurationError, settings_from_mapping
from agent_ch20.core.profiles import (
    P07,
    P09,
    P10,
    P11,
    P12,
    P19,
    P20,
    profile_for_chapter,
)


def test_profile_for_chapter_seven_exposes_skills():
    assert profile_for_chapter(7) is P07
    assert "skills" in P07.capabilities


def test_profile_for_chapter_nine_exposes_memory():
    assert profile_for_chapter(9) is P09
    assert "memory" in P09.capabilities


def test_profile_for_chapter_ten_exposes_dynamic_prompt():
    assert profile_for_chapter(10) is P10
    assert "dynamic_prompt" in P10.capabilities


def test_profile_for_chapter_eleven_exposes_recovery():
    assert profile_for_chapter(11) is P11
    assert "recovery" in P11.capabilities


def test_profile_for_chapter_twelve_exposes_json_task_dag():
    assert profile_for_chapter(12) is P12
    assert "task_dag_json" in P12.capabilities


def test_reports_all_missing_fields():
    with pytest.raises(ConfigurationError) as error:
        settings_from_mapping({"OPENAI_API_KEY": " "})
    assert error.value.missing_fields == (
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_FALLBACK_MODEL",
    )


def test_rejects_full_chat_endpoint():
    with pytest.raises(ConfigurationError):
        settings_from_mapping(
            {
                "OPENAI_BASE_URL": "https://example.test/v1/chat/completions",
                "OPENAI_API_KEY": "key",
                "OPENAI_MODEL": "model",
                "OPENAI_FALLBACK_MODEL": "fallback-model",
            }
        )


def test_profile_for_chapter_twenty_marks_full_harness():
    """P20 只在 P19 之上追加 full_harness 标记，不新增独立运行时能力。"""
    assert profile_for_chapter(20) is P20
    assert "full_harness" in P20.capabilities
    # P20 必须是 P19 的严格超集，且只多出一个标记能力。
    assert P19.capabilities < P20.capabilities
    assert P20.capabilities - P19.capabilities == {"full_harness"}
    # 前十九章的关键能力必须全部保留在完整 Harness 中。
    for capability in ("mcp", "worktree", "work_stealing", "protocol", "cron", "recovery"):
        assert capability in P20.capabilities


def test_every_profile_is_a_strict_superset_of_the_previous_chapter():
    """增量推导必须保证章节能力单调递增，避免后一章丢掉已验证能力。"""
    previous = profile_for_chapter(1)
    for chapter in range(2, 21):
        current = profile_for_chapter(chapter)
        assert current.chapter == chapter
        assert previous.capabilities < current.capabilities
        previous = current


@pytest.mark.parametrize("chapter", [0, 21, True, 1.5])
def test_profile_for_chapter_rejects_invalid_chapter(chapter):
    """越界、布尔和非整数输入都必须在启动前失败。"""
    with pytest.raises(ValueError, match="chapter 必须是 1 到 20 的整数"):
        profile_for_chapter(chapter)
