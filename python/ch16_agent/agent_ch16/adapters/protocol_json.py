"""协议 JSON Repository 适配器。

实现暂时放在领域模块中以便教学时集中阅读；此模块提供标准 Adapter 导入路径，
后续可以在不改变调用方的情况下把文件存储实现拆出。
"""

from ..features.protocol import JsonProtocolStore

__all__ = ["JsonProtocolStore"]
