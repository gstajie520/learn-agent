# 第 3 章学习导航：权限策略系统

```mermaid
mindmap
  root((第 3 章：权限策略系统))
    学习路线（推荐顺序）
      第一步：理解权限需求（10 分钟）
        tests/test_permissions.py
        tests/test_ch03_integration.py
        理解权限决策过程
        工作区边界保护
      第二步：读权限核心（20 分钟）
        core/permissions.py
        PermissionPolicy.decide() 方法
        规则、审批、审计流程
        理解 fail-closed 原则
      第三步：理解集成点（15 分钟）
        core/loop.py - 权限检查点
        cli.py - 终端审批适配器
        bootstrap.py - 策略装配
    
    核心文件清单
      core/permissions.py（权限策略核心）
        PermissionPolicy 类
          decide() 主决策方法
          规则评估与合并
          工作区边界检查
          审批流程收敛
        领域模型
          PermissionDecision（决策结果）
          PermissionRequest（请求快照）
          PermissionRule（不可变规则）
          PermissionBehavior（四态行为）
        外部边界
          ApprovalProvider（审批接口）
          AuditSink（审计接口）
          WorkspaceWriteBoundary（边界检查）
      core/loop.py（集成权限）
        AgentRunner 添加 permission_policy
        run() 方法中权限检查点
        权限评估失败时 fail-closed
        保证每个 tool_call 都有配对结果
      core/filesystem.py（工作区边界）
        WorkspaceWriteBoundary 接口
        is_path_within_workspace()
        路径逃逸检查
      adapters/filesystem.py（边界实现）
        LocalWorkspaceFileSystem
        safe_path() 函数
        符号链接和绝对路径拒绝
        Windows 保留名检查
      cli.py（终端适配器）
        TerminalApprovalProvider
        TerminalAuditSink
        交互式 y/N 确认
        stderr 审计日志
      bootstrap.py（策略装配）
        P03 章节配置
        confirm-file-write 规则
        必需审批器和审计器
        PermissionPolicy 构造
    
    Java 对照关系
      设计模式对照
        PermissionPolicy = 策略模式 + 责任链
        ApprovalProvider = 策略接口
        AuditSink = 观察者接口
        PermissionRule = 不可变规则对象
      类型系统对照
        Literal['allow', 'deny', ...] = 枚举
        Callable[[Request], bool] = Predicate<Request>
        Protocol = interface
        frozenset = Collections.unmodifiableSet
      异常处理对照
        PermissionContractError = 契约异常
        except Exception: 默认拒绝 = fail-closed
        审批器异常时统一处理
      依赖注入对照
        构造器注入规则列表
        可选依赖：approval/audit
        接口隔离：只依赖 Protocol
    
    设计模式识别
      策略模式
        PermissionPolicy 可替换
        ApprovalProvider 策略接口
        AuditSink 可选注入
      责任链模式
        边界检查 → 默认策略 → 规则评估 → 审批
        每个环节产生候选决策
        _strongest() 合并冲突
      适配器模式
        TerminalApprovalProvider 适配终端
        TerminalAuditSink 适配 stderr
        未来可替换为 Web/RPC 实现
      不可变对象
        PermissionDecision frozen=True
        PermissionRequest 快照
        PermissionRule 不可变
    
    关键概念理解
      四态权限行为
        allow：明确允许执行
        deny：明确拒绝执行
        ask：需要审批收敛
        passthrough：没有规则参与
      fail-closed 原则
        审批器异常时默认拒绝
        权限评估异常时默认拒绝
        安全优先于可用性
      工作区边界保护
        拒绝绝对路径和父目录片段
        拒绝符号链接逃逸
        拒绝 Windows 保留名
        边界 deny 不能被 allow 覆盖
      决策合并策略
        deny > ask > allow 优先级
        取最保守候选
        passthrough 变 allow
      审计不可绕过
        审计失败时向上抛出
        阻止工具执行
        保证所有决定都记录
    
    面试题速查
      Q1: 为什么需要权限策略？
        A: shell 和文件工具可能破坏系统
        需要人工审批高风险操作
        审计记录用于事后追溯
      Q2: 四态权限行为如何收敛？
        A: ask 交给 ApprovalProvider 收敛
        passthrough 变为 allow（默认放行）
        allow/deny 是最终决定
      Q3: 什么是 fail-closed 原则？
        A: 权限系统故障时默认拒绝
        审批器抛异常返回 deny
        安全优先于可用性
      Q4: 工作区边界如何保护？
        A: 拒绝绝对路径和 .. 片段
        解析真实路径检查是否逃逸
        符号链接也不能指向工作区外
      Q5: 决策冲突时如何合并？
        A: _strongest() 选最保守候选
        优先级: deny > ask > allow
        边界 deny 不能被覆盖
      Q6: 审计失败会怎样？
        A: 向上抛异常，阻止工具执行
        不能让决定未记录就执行
        保证审计日志完整性
      Q7: 为什么 PermissionRequest 要快照？
        A: 规则和审批器是外部代码
        防止修改影响后续评估
        frozen=True 保证不可变
      Q8: 权限层在 Agent Loop 哪个位置？
        A: prepare() 之后、invoke() 之前
        工具参数已校验，但未执行
        拒绝时仍要生成配对 tool 消息
```
