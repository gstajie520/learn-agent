"""外部系统适配器。

这是什么：OpenAI SDK、PowerShell 进程、本地文件系统的具体实现。
Java 类比：类似 infrastructure 包，实现核心层定义的 Protocol（interface）。
为什么需要：隔离外部依赖，让核心层可测试且不受第三方 API 变化影响。
"""
