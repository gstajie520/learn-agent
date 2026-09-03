"""环境配置读取与校验。

这是什么：负责加载和验证环境配置的模块
Java 类比：类似 @ConfigurationProperties 配置绑定和校验逻辑
为什么需要：集中管理配置来源（.env 文件或环境变量），确保启动前配置完整合法
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


class ConfigurationError(Exception):
    """配置不完整或格式错误，类似 Spring 启动阶段的配置绑定异常。

    这是什么：表示配置加载失败的自定义异常
    Java 类比：类似 ConfigurationException 或 BindException
    为什么需要：区分配置错误和运行时错误，让启动流程能快速失败并提示缺失的配置项
    """

    def __init__(self, missing_fields: list[str]) -> None:
        """记录所有缺失的配置字段名。

        这是什么：构造器，保存缺失字段列表
        Java 类比：类似 super(message) 并存储 List<String> missingFields
        为什么需要：一次性告知用户所有缺失配置，避免逐个修复后反复重启
        """
        self.missing_fields = tuple(missing_fields)  # 转成 tuple，避免异常创建后被外部修改。
        super().__init__(f"缺少或填写错误的必要配置: {', '.join(missing_fields)}")


@dataclass(frozen=True, slots=True)
class OpenAISettings:
    """校验通过后的模型配置。后续代码不再处理空字符串。

    这是什么：已验证的模型服务配置对象
    Java 类比：类似 @ConfigurationProperties record OpenAISettings(...)
    为什么需要：将松散的字典转换为类型安全的不可变对象，确保配置一旦创建就合法

    base_url: OpenAI 兼容服务根地址，不包含 /chat/completions。
    api_key: 服务商密钥，不能写入日志或提交 Git。
    model: 默认模型名称，例如 deepseek-v4-flash。
    """

    base_url: str  # OpenAI 兼容服务根地址，不包含 /chat/completions。
    api_key: str  # 服务商密钥，不能写入日志或提交 Git。
    model: str  # 默认模型名称，例如 deepseek-v4-flash。


def settings_from_mapping(mapping: dict[str, str | None]) -> OpenAISettings:
    """一次性检查所有必填项，并转换成强类型配置对象。

    这是什么：从字典中提取并验证配置项的核心函数
    Java 类比：类似 ConfigBinder.bind(Map<String, String>) throws ValidationException
    为什么需要：集中配置验证逻辑，确保所有必填项存在且格式正确后才构造配置对象
    """
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
    """读取 .env 文件，然后复用同一套校验逻辑。

    这是什么：从 .env 文件加载配置的便捷方法
    Java 类比：类似 ConfigLoader.fromFile(Path) 读取 properties 文件
    为什么需要：支持开发环境通过 .env 文件管理配置，避免硬编码或手动设置环境变量
    """
    values = {key: value for key, value in dotenv_values(path).items()}
    return settings_from_mapping(values)


def settings_from_environment() -> OpenAISettings:
    """直接从操作系统环境变量读取配置，便于容器或 CI 使用。

    这是什么：从系统环境变量加载配置的方法
    Java 类比：类似 System.getenv() 读取环境变量后绑定到配置对象
    为什么需要：支持生产环境通过环境变量传递配置，符合 12-Factor App 原则
    """
    return settings_from_mapping(
        {key: os.environ.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")}
    )


def find_env_file(start: str | Path) -> Path | None:
    """从当前目录向上查找共享 .env，类似 Java 应用查找外部配置目录。

    这是什么：向上遍历目录树查找 .env 文件的工具函数
    Java 类比：类似递归查找 application.properties 的配置发现逻辑
    为什么需要：让所有章节项目共享同一个 .env 文件，避免配置重复和不一致
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
