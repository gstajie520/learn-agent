import pytest

from agent_ch05.config import ConfigurationError, settings_from_mapping


def test_reports_all_missing_fields():
    with pytest.raises(ConfigurationError) as error:
        settings_from_mapping({"OPENAI_API_KEY": " "})
    assert error.value.missing_fields == ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")


def test_rejects_full_chat_endpoint():
    with pytest.raises(ConfigurationError):
        settings_from_mapping({"OPENAI_BASE_URL": "https://example.test/v1/chat/completions", "OPENAI_API_KEY": "key", "OPENAI_MODEL": "model"})
