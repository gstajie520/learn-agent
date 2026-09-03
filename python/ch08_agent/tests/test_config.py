"""配置模块的单元测试：验证 Profile 选择和配置加载逻辑。

这是什么：测试配置解析和 Profile 映射功能
Java 类比：类似 ConfigurationServiceTest 单元测试类
为什么需要：确保章节号能正确映射到 Profile，且配置格式校验有效
"""

import pytest

from agent_ch08.config import ConfigurationError, settings_from_mapping
from agent_ch08.core.profiles import P07, profile_for_chapter


def test_profile_for_chapter_seven_exposes_skills():
    assert profile_for_chapter(7) is P07
    assert "skills" in P07.capabilities


def test_reports_all_missing_fields():
    with pytest.raises(ConfigurationError) as error:
        settings_from_mapping({"OPENAI_API_KEY": " "})
    assert error.value.missing_fields == ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")


def test_rejects_full_chat_endpoint():
    with pytest.raises(ConfigurationError):
        settings_from_mapping(
            {
                "OPENAI_BASE_URL": "https://example.test/v1/chat/completions",
                "OPENAI_API_KEY": "key",
                "OPENAI_MODEL": "model",
            }
        )
