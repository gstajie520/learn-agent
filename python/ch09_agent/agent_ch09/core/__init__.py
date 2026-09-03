"""核心领域与应用服务：不直接依赖具体 SDK 或操作系统实现。

这是什么：核心业务逻辑层的包标识
Java 类比：类似 package-info.java，标记 core 为 Python 模块
为什么需要：让 Python 识别此目录为可导入的包，包含所有领域模型和服务

包含模块：
- loop.py: Agent 核心循环和生命周期管理
- messages.py: 消息领域模型
- model.py: 模型交互接口
- tools.py: 工具注册表和执行管理
- permissions.py: 权限策略模型
- hooks.py: Hook 生命周期系统
- filesystem.py: 文件系统抽象接口
- commands.py: 命令执行抽象接口
- profiles.py: 章节能力配置
"""
