"""配置加载与验证测试。

这是什么：配置模块的单元测试
Java 类比：类似 ConfigServiceTest 测试类
为什么需要：验证配置加载、缺失字段检测和 URL 格式校验
"""

import pytest

from agent_ch02.config import ConfigurationError, settings_from_mapping


def test_reports_all_missing_fields():
    """验证缺失字段全部报告。

    这是什么：配置验证测试用例
    Java 类比：类似 @Test void testMissingFieldsReported()
    为什么需要：确保配置验证一次性报告所有错误，而非逐个报告
    """
    with pytest.raises(ConfigurationError) as error:  # 捕获配置错误
        settings_from_mapping({"OPENAI_API_KEY": " "})  # 空白值视为缺失
    assert error.value.missing_fields == ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")  # 验证所有缺失字段


def test_rejects_full_chat_endpoint():
    """验证拒绝完整的聊天端点 URL。

    这是什么：URL 格式验证测试用例
    Java 类比：类似 @Test void testRejectFullEndpointUrl()
    为什么需要：确保用户配置基础 URL 而非完整端点，避免路径拼接错误
    """
    with pytest.raises(ConfigurationError):  # 应该抛出配置错误
        settings_from_mapping({"OPENAI_BASE_URL": "https://example.test/v1/chat/completions", "OPENAI_API_KEY": "key", "OPENAI_MODEL": "model"})  # 完整端点应被拒绝
