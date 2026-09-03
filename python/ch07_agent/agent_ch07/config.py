"""环境配置读取与校验。

这是什么：
    配置管理模块，负责从 .env 文件或环境变量读取并校验模型配置。

Java 类比：
    类似 Spring Boot 的 @ConfigurationProperties + Bean Validation。

为什么需要：
    - 集中管理配置读取逻辑，避免在业务代码中散落配置访问
    - 启动时就校验配置完整性，避免运行时才发现配置错误
    - 支持多种配置源（.env 文件、环境变量），便于不同环境部署
    - 一次性收集所有缺失字段，提升配置错误的诊断效率
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


class ConfigurationError(Exception):
    """配置不完整或格式错误，类似 Spring 启动阶段的配置绑定异常。

    这是什么：
        配置校验失败时抛出的异常，包含所有缺失或错误的字段列表。

    Java 类比：
        class ConfigurationException extends RuntimeException
        类似 Spring Boot 的 BindException。

    为什么需要：
        - 启动时就失败，避免运行时才发现配置问题
        - 一次性报告所有错误字段，而非逐个报错
        - 保存 missing_fields 便于自动化诊断和提示
    """

    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = tuple(missing_fields)  # 转成 tuple，避免异常创建后被外部修改。
        super().__init__(f"缺少或填写错误的必要配置: {', '.join(missing_fields)}")


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    """校验通过后的模型配置。后续代码不再处理空字符串。

    这是什么：
        模型配置的不可变数据对象，所有字段已通过校验且非空。

    Java 类比：
        record OpenAISettings(String baseUrl, String apiKey, String model)
        类似 @ConfigurationProperties 绑定的不可变配置类。

    为什么需要：
        - 不可变设计（frozen=True）保证配置不会被意外修改
        - 校验通过后创建，后续代码可以信任字段非空且格式正确
        - 类型安全，避免使用 dict 传递配置导致的字段拼写错误
    """

    base_url: str  # OpenAI 兼容服务根地址，不包含 /chat/completions。
    api_key: str  # 服务商密钥，不能写入日志或提交 Git。
    model: str  # 默认模型名称，例如 deepseek-v4-flash。


def settings_from_mapping(mapping: dict[str, str | None]) -> OpenAISettings:
    """一次性检查所有必填项，并转换成强类型配置对象。"""
    # 先收集全部缺失字段，让使用者一次修改完，不必启动三次才发现三个问题。
    required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"]
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
        base_url, (mapping["OPENAI_API_KEY"] or "").strip(), (mapping["OPENAI_MODEL"] or "").strip()
    )


def settings_from_env_file(path: str | Path) -> OpenAISettings:
    """读取 .env 文件，然后复用同一套校验逻辑。"""
    values = {key: value for key, value in dotenv_values(path).items()}
    return settings_from_mapping(values)


def settings_from_environment() -> OpenAISettings:
    """直接从操作系统环境变量读取配置，便于容器或 CI 使用。"""
    return settings_from_mapping(
        {key: os.environ.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")}
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
