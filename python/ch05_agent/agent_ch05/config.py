"""环境配置读取与校验。

Java 对照：类似 Spring Boot 的 @ConfigurationProperties，负责从环境变量或
.env 文件读取配置，并在启动时完整校验。

这是什么：配置加载和校验模块
为什么需要：集中管理配置读取，尽早发现配置错误
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values  # 第三方库，用于解析 .env 文件


class ConfigurationError(Exception):
    """配置不完整或格式错误，类似 Spring 启动阶段的配置绑定异常。

    这是什么：配置错误的专用异常
    Java 类比：class ConfigurationException extends RuntimeException
    为什么需要：区分配置错误和运行时错误，返回不同退出码
    """

    def __init__(self, missing_fields: list[str]) -> None:
        """保存缺失字段列表，并生成可读的错误消息。

        这是什么：异常构造方法
        Java 类比：public ConfigurationException(List<String> missingFields)
        为什么需要：一次性列出所有缺失字段，让用户一次修复完
        """
        self.missing_fields = tuple(missing_fields)  # 转成 tuple，避免异常创建后被外部修改
        super().__init__(f"缺少或填写错误的必要配置: {', '.join(missing_fields)}")


@dataclass(frozen=True, slots=True)  # 不可变配置对象
class OpenAISettings:
    """校验通过后的模型配置。后续代码不再处理空字符串。

    这是什么：模型配置的强类型对象
    Java 类比：record OpenAISettings(String baseUrl, String apiKey, String model)
    为什么需要：封装配置项，确保后续代码拿到的都是合法值
    """
    base_url: str  # OpenAI 兼容服务根地址，不包含 /chat/completions
    api_key: str  # 服务商密钥，不能写入日志或提交 Git
    model: str  # 默认模型名称，例如 deepseek-v4-flash


def settings_from_mapping(mapping: dict[str, str | None]) -> OpenAISettings:
    """一次性检查所有必填项，并转换成强类型配置对象。

    这是什么：从字典构建配置对象的工厂方法
    Java 类比：static OpenAISettings fromMap(Map<String, String> mapping)
    为什么需要：统一校验逻辑，避免在多处重复检查配置

    参数：
        mapping: 包含配置键值的字典（值可能为 None）

    返回：
        OpenAISettings: 校验通过的配置对象

    异常：
        ConfigurationError: 缺少必填项或格式错误
    """
    # 先收集全部缺失字段，让使用者一次修改完，不必启动三次才发现三个问题
    required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"]
    missing = [name for name in required if not (mapping.get(name) or "").strip()]

    if missing:
        raise ConfigurationError(missing)

    # 校验 base_url 格式：必须是 http/https，且不能包含 /chat/completions 路径
    base_url = (mapping["OPENAI_BASE_URL"] or "").strip()
    parsed = urlparse(base_url)

    # scheme 必须是 http 或 https，且路径不能以 /chat/completions 结尾
    if parsed.scheme not in {"http", "https"} or parsed.path.rstrip("/").endswith("/chat/completions"):
        raise ConfigurationError(["OPENAI_BASE_URL"])

    return OpenAISettings(
        base_url,
        (mapping["OPENAI_API_KEY"] or "").strip(),
        (mapping["OPENAI_MODEL"] or "").strip()
    )


def settings_from_env_file(path: str | Path) -> OpenAISettings:
    """读取 .env 文件，然后复用同一套校验逻辑。

    这是什么：从 .env 文件加载配置的便利方法
    Java 类比：static OpenAISettings fromEnvFile(Path path)
    为什么需要：支持开发环境的 .env 文件配置方式

    参数：
        path: .env 文件路径

    返回：
        OpenAISettings: 校验通过的配置对象
    """
    # dotenv_values 返回 dict[str, str | None]，键是变量名，值是变量值
    values = {key: value for key, value in dotenv_values(path).items()}
    return settings_from_mapping(values)


def settings_from_environment() -> OpenAISettings:
    """直接从操作系统环境变量读取配置，便于容器或 CI 使用。

    这是什么：从系统环境变量加载配置的便利方法
    Java 类比：static OpenAISettings fromEnvironment()
    为什么需要：支持生产环境的环境变量配置方式（容器、CI/CD）
    """
    return settings_from_mapping({
        key: os.environ.get(key)
        for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")
    })


def find_env_file(start: str | Path) -> Path | None:
    """从当前目录向上查找共享 .env，类似 Java 应用查找外部配置目录。

    这是什么：向上查找 .env 文件的辅助函数
    Java 类比：static Optional<Path> findEnvFile(Path start)
    为什么需要：所有章节可以共享 python/.env，避免每章都复制配置

    从章节目录开始逐级向上找，因此所有章节可以共享 python/.env。

    参数：
        start: 开始查找的目录或文件路径

    返回：
        Path | None: 找到的 .env 文件路径，未找到返回 None
    """
    current = Path(start).resolve()

    # 如果传入的是文件路径，先切换到父目录
    if current.is_file():
        current = current.parent

    # `*current.parents` 是序列展开，类似先 new List，再 addAll(current.getParents())
    # 从当前目录开始，逐级向上查找
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate

    return None  # 查找到根目录仍未找到
