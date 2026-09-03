"""核心领域与应用服务：不直接依赖具体 SDK 或操作系统实现。

这是什么：
    核心领域层，包含 Agent Loop、消息模型、工具注册表、权限策略和 Hook 生命周期。

Java 类比：
    类似 DDD 的 Domain + Application 层，或 Spring 的 Service + Domain Model 层。

为什么需要：
    - 核心逻辑不依赖具体技术选型（可以换模型供应商、换操作系统）
    - 通过 Protocol（接口）隔离外部依赖，便于单元测试
    - 实现业务规则的稳定性和可移植性
"""
