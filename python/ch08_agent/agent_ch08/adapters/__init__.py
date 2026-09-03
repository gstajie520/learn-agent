"""外部系统适配器。

这是什么：将第三方服务（OpenAI、文件系统、PowerShell）封装成符合核心接口的实现
Java 类比：类似 adapter 包，存放 XxxAdapter 实现类（如 OpenAiModelAdapter）
为什么需要：隔离外部依赖，让核心逻辑不直接依赖具体的 HTTP 客户端或进程管理库
"""
