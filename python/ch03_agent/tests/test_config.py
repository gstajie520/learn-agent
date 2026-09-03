"""配置加载与校验测试。

这是什么：测试环境变量和 .env 文件的配置读取、校验逻辑。
Java 类比：类似 ConfigurationTest，验证 Spring @ConfigurationProperties 绑定和校验。
为什么需要：配置错误应该在启动时就发现，而不是运行时才报错。
"""

import pytest

from agent_ch03.config import ConfigurationError, settings_from_mapping


def test_reports_all_missing_fields():
    with pytest.raises(ConfigurationError) as error:
        settings_from_mapping({"OPENAI_API_KEY": " "})
    assert error.value.missing_fields == ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")


def test_rejects_full_chat_endpoint():
    with pytest.raises(ConfigurationError):
        settings_from_mapping({"OPENAI_BASE_URL": "https://example.test/v1/chat/completions", "OPENAI_API_KEY": "key", "OPENAI_MODEL": "model"})
