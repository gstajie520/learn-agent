"""环境配置读取与校验。

这是什么：配置管理层，负责加载和验证环境配置
Java 类比：类似 Spring Boot 的 @ConfigurationProperties 或配置读取工具类
为什么需要：集中管理配置加载逻辑，统一校验规则，避免运行时配置错误
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


class ConfigurationError(Exception):
    """配置不完整或格式错误，类似 Spring 启动阶段的配置绑定异常。

    这是什么：配置异常，表示必填配置缺失或格式错误
    Java 类比：类似 ConfigurationException 或 BindException
    为什么需要：区分配置错误和运行时错误，让应用启动时快速失败
    """
    def __init__(self, missing_fields: list[str]) -> None:
        """初始化配置异常，记录缺失的配置项。

        这是什么：构造器，保存缺失字段列表并生成错误消息
        Java 类比：类似 public ConfigurationException(List<String> missingFields)
        为什么需要：提供明确的错误信息，帮助用户快速定位配置问题
        """
        self.missing_fields = tuple(missing_fields)  # 转成 tuple，避免异常创建后被外部修改。
        super().__init__(f"缺少或填写错误的必要配置: {', '.join(missing_fields)}")


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    """校验通过后的模型配置。后续代码不再处理空字符串。

    这是什么：OpenAI 兼容服务的配置对象（不可变）
    Java 类比：类似 @ConfigurationProperties("openai") record OpenAISettings
    为什么需要：封装已验证的配置，保证类型安全，避免字符串传递配置
    """
    base_url: str  # OpenAI 兼容服务根地址，不包含 /chat/completions。
    api_key: str  # 服务商密钥，不能写入日志或提交 Git。
    model: str  # 默认模型名称，例如 deepseek-v4-flash。


def settings_from_mapping(mapping: dict[str, str | None]) -> OpenAISettings:
    """一次性检查所有必填项，并转换成强类型配置对象。

    这是什么：配置验证和转换器，从字典构造配置对象
    Java 类比：类似 static OpenAISettings bind(Map<String, String> properties) throws ValidationException
    为什么需要：统一校验逻辑，一次性收集所有错误，避免用户反复修复启动
    """
    # 先收集全部缺失字段，让使用者一次修改完，不必启动三次才发现三个问题。
    required = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"]  # 必填配置项列表
    missing = [name for name in required if not (mapping.get(name) or "").strip()]  # 收集空或缺失的字段
    if missing:  # 有缺失字段时立即抛出异常
        raise ConfigurationError(missing)
    base_url = (mapping["OPENAI_BASE_URL"] or "").strip()  # 提取并清理 URL
    parsed = urlparse(base_url)  # 解析 URL 结构
    if parsed.scheme not in {"http", "https"} or parsed.path.rstrip("/").endswith("/chat/completions"):  # 校验 URL 格式
        raise ConfigurationError(["OPENAI_BASE_URL"])
    return OpenAISettings(base_url, (mapping["OPENAI_API_KEY"] or "").strip(), (mapping["OPENAI_MODEL"] or "").strip())  # 构造配置对象


def settings_from_env_file(path: str | Path) -> OpenAISettings:
    """读取 .env 文件，然后复用同一套校验逻辑。

    这是什么：从 .env 文件加载配置的便捷方法
    Java 类比：类似 static OpenAISettings loadFromFile(Path envFile)
    为什么需要：支持本地开发使用 .env 文件，避免硬编码或污染环境变量
    """
    values = {key: value for key, value in dotenv_values(path).items()}  # 读取 .env 文件为字典
    return settings_from_mapping(values)  # 复用统一的校验逻辑


def settings_from_environment() -> OpenAISettings:
    """直接从操作系统环境变量读取配置，便于容器或 CI 使用。

    这是什么：从环境变量加载配置的便捷方法
    Java 类比：类似 static OpenAISettings loadFromEnvironment()
    为什么需要：支持生产环境和 CI/CD 使用环境变量，符合 12-factor 应用原则
    """
    return settings_from_mapping({key: os.environ.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")})  # 从 os.environ 读取配置


def find_env_file(start: str | Path) -> Path | None:
    """从当前目录向上查找共享 .env，类似 Java 应用查找外部配置目录。

    这是什么：配置文件查找器，向上遍历目录树查找 .env
    Java 类比：类似 static Path findConfigFile(Path startDir)
    为什么需要：支持多章节共享一个配置文件，避免重复配置
    """
    # 从章节目录开始逐级向上找，因此所有章节可以共享 python/.env。
    current = Path(start).resolve()  # 转换为绝对路径
    if current.is_file():  # 如果起点是文件，从其父目录开始查找
        current = current.parent
    # `*current.parents` 是序列展开，类似先 new List，再 addAll(current.getParents())。
    for directory in (current, *current.parents):  # 遍历当前目录及所有父目录
        candidate = directory / ".env"  # 拼接 .env 文件路径
        if candidate.is_file():  # 找到文件即返回
            return candidate
    return None  # 未找到时返回 None
