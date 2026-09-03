"""环境配置读取与校验。"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


class ConfigurationError(Exception):
    """配置不完整或格式错误，类似 Spring 启动阶段的配置绑定异常。

    这是什么：配置错误的专用异常
    Java 类比：类似 ConfigurationException 或 BindException
    为什么需要：在启动阶段就明确告知缺失的配置项，避免运行时才发现配置问题
    """
    def __init__(self, missing_fields: list[str]) -> None:
        """保存缺失字段列表并生成描述性错误消息。

        这是什么：构造器，记录缺失的配置字段
        Java 类比：类似 public ConfigurationError(List<String> missing) { ... }
        为什么需要：让调用方能获取具体缺失字段列表，同时生成友好的错误提示
        """
        self.missing_fields = tuple(missing_fields)  # 转成 tuple，避免异常创建后被外部修改。
        super().__init__(f"缺少或填写错误的必要配置: {', '.join(missing_fields)}")


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    """校验通过后的模型配置。后续代码不再处理空字符串。

    这是什么：经过校验的模型配置值对象
    Java 类比：类似 record OpenAISettings(String baseUrl, String apiKey, String model)
    为什么需要：将配置从字符串字典转换为类型安全的不可变对象，确保后续代码拿到的都是有效值
    """
    base_url: str  # OpenAI 兼容服务根地址，不包含 /chat/completions。
    api_key: str  # 服务商密钥，不能写入日志或提交 Git。
    model: str  # 默认模型名称，例如 deepseek-v4-flash。


def settings_from_mapping(mapping: dict[str, str | None]) -> OpenAISettings:
    """一次性检查所有必填项，并转换成强类型配置对象。

    这是什么：配置字典的校验与转换器
    Java 类比：类似 public OpenAISettings validate(Map<String, String> props)
    为什么需要：从任意来源（环境变量、.env 文件）的字典统一校验，避免重复逻辑
    """
    # 先收集全部缺失字段，让使用者一次修改完，不必启动三次才发现三个问题。
    required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"]
    missing = [name for name in required if not (mapping.get(name) or "").strip()]
    if missing:
        raise ConfigurationError(missing)
    base_url = (mapping["OPENAI_BASE_URL"] or "").strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.path.rstrip("/").endswith("/chat/completions"):
        raise ConfigurationError(["OPENAI_BASE_URL"])
    return OpenAISettings(base_url, (mapping["OPENAI_API_KEY"] or "").strip(), (mapping["OPENAI_MODEL"] or "").strip())


def settings_from_env_file(path: str | Path) -> OpenAISettings:
    """读取 .env 文件，然后复用同一套校验逻辑。

    这是什么：从 .env 文件加载配置的便捷方法
    Java 类比：类似 @ConfigurationProperties(prefix="openai") 绑定到 .properties 文件
    为什么需要：开发环境常用 .env 文件管理密钥，提供专用方法简化调用
    """
    values = {key: value for key, value in dotenv_values(path).items()}
    return settings_from_mapping(values)


def settings_from_environment() -> OpenAISettings:
    """直接从操作系统环境变量读取配置，便于容器或 CI 使用。

    这是什么：从系统环境变量加载配置的便捷方法
    Java 类比：类似 System.getenv() 加载配置
    为什么需要：容器化部署和 CI 环境通常通过环境变量注入配置，而非文件
    """
    return settings_from_mapping({key: os.environ.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")})


def find_env_file(start: str | Path) -> Path | None:
    """从当前目录向上查找共享 .env，类似 Java 应用查找外部配置目录。

    这是什么：向上递归查找配置文件的工具方法
    Java 类比：类似 findConfigFile(Path start) 向上遍历父目录
    为什么需要：让各章节项目能共享上层 python/.env，避免每个目录重复配置文件
    """
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
