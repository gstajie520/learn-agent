"""环境配置读取与校验。

这是什么：应用配置加载和验证模块
Java 类比：类似 Spring 的 @ConfigurationProperties 和配置绑定
为什么需要：统一配置来源（环境变量或 .env 文件），启动时一次性校验所有必填项
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


class ConfigurationError(Exception):
    """配置不完整或格式错误，类似 Spring 启动阶段的配置绑定异常。

    这是什么：配置错误的领域异常
    Java 类比：类似 @ConfigurationProperties 绑定失败的异常
    为什么需要：启动时快速失败，告知用户缺少哪些必填配置，避免运行时才报错
    """

    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = tuple(missing_fields)  # 转成 tuple，避免异常创建后被外部修改。
        super().__init__(f"缺少或填写错误的必要配置: {', '.join(missing_fields)}")


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    """校验通过后的模型配置。后续代码不再处理空字符串。

    这是什么：OpenAI 兼容服务的不可变配置对象
    Java 类比：record OpenAISettings(String baseUrl, String apiKey, String model, String fallback)
    为什么需要：通过构造器校验一次，后续代码可以信任字段都是非空的合法值

    参数：
        base_url: OpenAI 兼容服务根地址，不包含 /chat/completions
        api_key: 服务商密钥，不能写入日志或提交 Git
        model: 默认模型名称，例如 deepseek-v4-flash
        fallback_model: 主模型连续过载时切换的备用模型
    """

    base_url: str  # OpenAI 兼容服务根地址，不包含 /chat/completions。
    api_key: str  # 服务商密钥，不能写入日志或提交 Git。
    model: str  # 默认模型名称，例如 deepseek-v4-flash。
    fallback_model: str  # 主模型连续过载时切换的备用模型。


def settings_from_mapping(mapping: dict[str, str | None]) -> OpenAISettings:
    """一次性检查所有必填项，并转换成强类型配置对象。

    这是什么：从字典映射构建配置对象的工厂函数
    Java 类比：类似 @ConfigurationProperties 的绑定逻辑
    为什么需要：统一校验逻辑，避免环境变量和 .env 文件分别实现一遍

    参数：
        mapping: 配置键值映射，值可能为 None 或空字符串

    返回：
        OpenAISettings: 校验通过的配置对象

    异常：
        ConfigurationError: 缺少必填项或格式错误
    """
    # 先收集全部缺失字段，让使用者一次修改完，不必启动三次才发现三个问题。
    required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_FALLBACK_MODEL"]
    missing = [name for name in required if not (mapping.get(name) or "").strip()]
    if missing:
        raise ConfigurationError(missing)
    base_url = (mapping["OPENAI_BASE_URL"] or "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.path.rstrip("/").endswith(
        "/chat/completions"
    ):
        raise ConfigurationError(["OPENAI_BASE_URL"])
    return OpenAISettings(
        base_url,
        (mapping["OPENAI_API_KEY"] or "").strip(),
        (mapping["OPENAI_MODEL"] or "").strip(),
        (mapping["OPENAI_FALLBACK_MODEL"] or "").strip(),
    )


def settings_from_env_file(path: str | Path) -> OpenAISettings:
    """读取 .env 文件，然后复用同一套校验逻辑。

    这是什么：从 .env 文件加载配置的便捷函数
    Java 类比：类似读取 application.properties 的配置加载器
    为什么需要：开发环境通常使用 .env 文件管理密钥，避免硬编码到代码中

    参数：
        path: .env 文件的路径

    返回：
        OpenAISettings: 校验通过的配置对象
    """
    values = {key: value for key, value in dotenv_values(path).items()}
    return settings_from_mapping(values)


def settings_from_environment() -> OpenAISettings:
    """直接从操作系统环境变量读取配置，便于容器或 CI 使用。

    这是什么：从系统环境变量加载配置的便捷函数
    Java 类比：类似读取 System.getenv() 的配置加载器
    为什么需要：生产环境和 CI/CD 通常通过环境变量注入配置，不使用文件

    返回：
        OpenAISettings: 校验通过的配置对象
    """
    return settings_from_mapping(
        {
            key: os.environ.get(key)
            for key in (
                "OPENAI_BASE_URL",
                "OPENAI_API_KEY",
                "OPENAI_MODEL",
                "OPENAI_FALLBACK_MODEL",
            )
        }
    )


def find_env_file(start: str | Path) -> Path | None:
    """从当前目录向上查找共享 .env，类似 Java 应用查找外部配置目录。"""
    # 从章节目录开始逐级向上找，因此所有章节可以共享 python/.env。
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    # `*current.parents` 是序列展开，类似先 new List，再 addAll(current.getParents())。
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None
