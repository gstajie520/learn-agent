import pytest

from agent_ch15.config import ConfigurationError, settings_from_mapping
from agent_ch15.core.profiles import P07, P09, P10, P11, P12, profile_for_chapter


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
