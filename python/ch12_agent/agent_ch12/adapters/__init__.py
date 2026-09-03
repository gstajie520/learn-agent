"""外部系统适配器。

这是什么：与外部系统交互的适配器层（文件系统、PowerShell、OpenAI、JSON 存储）
Java 类比：类似 Spring 的 infrastructure 包，包含 Repository、Client 实现
为什么需要：隔离外部依赖，让核心层只依赖接口，测试时可以用 Fake 替换
"""
