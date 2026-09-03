"""环境配置读取与校验。

Java 角度：这是配置绑定模块，类似 Spring Boot 的 @ConfigurationProperties。
负责从 .env 或环境变量读取配置，并在启动阶段就失败（fail-fast）。
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


class ConfigurationError(Exception):
    """配置不完整或格式错误时抛出的启动异常。

    这是什么：配置校验失败的专用异常
    Java 类比：类似 Spring Boot 的 BindException 或 ConfigurationPropertiesBindException
    为什么需要：在启动阶段就暴露配置问题，避免运行到一半才发现 API Key 缺失
    """

    def __init__(self, missing_fields: list[str]) -> None:
        # 转成 tuple，避免异常创建后被外部修改（不可变原则）
        self.missing_fields = tuple(missing_fields)
        super().__init__(f"缺少或填写错误的必要配置: {', '.join(missing_fields)}")


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    """校验通过后的模型配置，保证字段非空且格式正确。

    这是什么：强类型配置对象，保存 OpenAI 兼容服务的连接参数
    Java 类比：类似带 @Validated 的 record 或 @ConfigurationProperties class
    为什么需要：后续代码不再检查空字符串，配置问题在启动时就已经被拦截

    参数：
        base_url: OpenAI 兼容服务根地址，不包含 /chat/completions 路径
        api_key: 服务商密钥，不能写入日志或提交 Git
        model: 默认模型名称，例如 deepseek-v4-flash
    """

    base_url: str  # OpenAI 兼容服务根地址
    api_key: str  # 服务商密钥
    model: str  # 默认模型名称


def settings_from_mapping(mapping: dict[str, str | None]) -> OpenAISettings:
    """一次性检查所有必填项，并转换成强类型配置对象。

    这是什么：配置绑定的核心逻辑，从字典构建配置对象
    Java 类比：类似 Spring 的 Binder.bind(properties, OpenAISettings.class)
    为什么需要：一次性报告所有缺失字段，避免"修一个、启动、再修一个"的循环

    参数：
        mapping: 键值对字典，通常来自 .env 文件或环境变量

    返回：
        OpenAISettings: 校验通过的配置对象

    异常：
        ConfigurationError: 缺失必填字段或 URL 格式不正确
    """
    # 先收集全部缺失字段，让使用者一次修改完，不必启动三次才发现三个问题
    required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"]
    missing = [name for name in required if not (mapping.get(name) or "").strip()]
    if missing:
        raise ConfigurationError(missing)

    # 校验 base_url 格式：必须是 http/https，且不能包含 /chat/completions 后缀
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
    """读取 .env 文件，然后复用同一套校验逻辑。

    这是什么：从 .env 文件加载配置的便捷方法
    Java 类比：类似 Spring Boot 的 @PropertySource("classpath:.env")
    为什么需要：开发环境常用 .env 文件管理密钥，避免硬编码

    参数：
        path: .env 文件路径

    返回：
        OpenAISettings: 校验通过的配置对象
    """
    values = {key: value for key, value in dotenv_values(path).items()}
    return settings_from_mapping(values)


def settings_from_environment() -> OpenAISettings:
    """直接从操作系统环境变量读取配置，便于容器或 CI 使用。

    这是什么：从系统环境变量加载配置
    Java 类比：类似 Spring 的 Environment.getProperty("OPENAI_API_KEY")
    为什么需要：生产环境或 Docker 容器通常用环境变量而不是文件

    返回：
        OpenAISettings: 校验通过的配置对象
    """
    return settings_from_mapping(
        {key: os.environ.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")}
    )


def find_env_file(start: str | Path) -> Path | None:
    """从当前目录向上查找共享 .env，类似 Java 应用查找外部配置目录。

    这是什么：向上递归查找 .env 文件的工具函数
    Java 类比：类似 Maven 查找父 pom.xml 的逻辑
    为什么需要：允许所有章节共享 python/.env，不必每个章节复制一份

    参数：
        start: 起始查找路径（文件或目录）

    返回：
        Path | None: 找到的 .env 文件路径，未找到返回 None
    """
    # 从章节目录开始逐级向上找，因此所有章节可以共享 python/.env
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent  # 如果传入的是文件，从其父目录开始

    # `*current.parents` 是序列展开，类似 Java 的 List.of(current, ...parents)
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None
