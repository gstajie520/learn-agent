# 第 4 章：Agent Hook 生命周期 - 学习路线图

```mermaid
mindmap
  root((第 4 章：Agent Hook 生命周期))
    学习路线（推荐顺序）
      第一步：读测试了解 Hook 契约
        tests/test_hooks.py
        理解四个生命周期事件
        HookContext 和 HookResult 的结构
      第二步：理解 Hook 系统设计
        core/hooks.py
        HookRegistry 注册机制
        事件触发点和回调执行
      第三步：看 Hook 如何接入循环
        tests/test_ch04_integration.py
        core/loop.py（带 Hook 的 AgentRunner）
        tool_call_id 配对保证
      第四步：理解权限与 Hook 协作
        core/permissions.py
        系统 deny 高于 Hook allow
        审批和审计流程
    
    核心文件清单
      core/hooks.py（Hook 生命周期）
        HookContext
          event: 四种事件类型
          message: UserPromptSubmit 的用户消息
          prepared: PreToolUse/PostToolUse 的工具调用
          result: PostToolUse 的工具结果
          history: Stop 的完整历史
        HookResult
          deny: 阻止工具执行
          stop: 主动结束 Agent
          append_messages: 注入上下文
          replace_prepared: 修改工具调用
          replace_result: 修改工具结果
        HookRegistry
          register: 注册回调
          run_user_prompt: UserPromptSubmit
          run_pre_tool: PreToolUse
          run_post_tool: PostToolUse
          run_stop: Stop
      core/loop.py（带 Hook 的循环）
        AgentRunner 构造器接受 HookRegistry
        四个 Hook 触发点
        tool_call_id 强配对保证
        _execute_tool 工具执行链路
      core/permissions.py（权限策略）
        PermissionPolicy（策略引擎）
        PermissionRule（规则对象）
        PermissionDecision（四态决策）
        ApprovalProvider（审批接口）
        AuditSink（审计接口）
      bootstrap.py（组合根）
        build_agent 工厂方法
        P04 才允许注入 HookRegistry
        能力越级检查
    
    Java 对照关系
      Hook 设计模式
        HookRegistry = 观察者注册表
        HookContext = 不可变 DTO
        HookResult = 影响声明对象
        回调 = BiConsumer<Context, Result>
      异步处理对照
        async/await = CompletableFuture
        asyncio.run = future.join()
        Awaitable = CompletionStage
        异步回调 = async 函数
      数据不可变性
        @dataclass(frozen=True) = record
        replace() = record.with(...)
        tuple = List.copyOf()
        MappingProxyType = Collections.unmodifiableMap
      契约校验
        __post_init__ = 构造器校验
        HookContractError = 领域异常
        isinstance 类型检查 = instanceof
        Literal 类型 = enum
    
    设计模式识别
      观察者模式
        HookRegistry 是事件总线
        回调按事件类型分组
        回调按注册顺序执行
      责任链模式
        Hook 回调链式执行
        每个回调可修改上下文
        stop=True 中断链路
      策略模式
        PermissionPolicy 可替换
        ApprovalProvider 可注入
        AuditSink 可注入
      模板方法
        AgentRunner.run 固定流程
        四个 Hook 点可扩展
        工具执行链路固定
      工厂模式
        build_agent 工厂方法
        按 Profile 组装依赖
        能力越级检查
    
    关键概念理解
      四个生命周期事件
        UserPromptSubmit: 用户问题提交后
        PreToolUse: 工具执行前（可阻断）
        PostToolUse: 工具执行后（可修改结果）
        Stop: Agent 停止前（可追加总结）
      tool_call_id 强配对
        每个 tool_call 必须有且仅有一条 tool 消息
        Hook deny 时回填拒绝消息
        异常时回填错误消息
        OpenAI API 协议要求
      权限与 Hook 协作
        系统 deny 高于 Hook allow
        Hook deny 会被尊重
        审批在权限层，Hook 在生命周期层
      Hook 回调契约
        只能访问事件对应字段
        返回 HookResult 声明影响
        不能直接修改 Agent 状态
        支持同步和异步回调
      不可变数据流
        HookContext 不可变输入
        HookResult 不可变输出
        replace() 创建新对象
        防止回调间相互影响
    
    面试题速查
      Q1: Hook 和普通回调有什么区别？
        A: Hook 有严格的生命周期事件定义
        每个事件对应特定的上下文字段
        通过返回值声明影响，不直接修改状态
        支持同步和异步回调
      Q2: 为什么需要 tool_call_id 强配对？
        A: OpenAI API 协议要求
        每个 assistant.tool_calls[i] 必须有对应 tool 消息
        Hook deny/异常时也要回填消息
        否则 API 400 拒绝请求
      Q3: Hook 如何阻止工具执行？
        A: PreToolUse 回调返回 HookResult(deny=True)
        循环会跳过 invoke，直接回填拒绝消息
        deny_reason 会进入 tool 消息给模型看
      Q4: 权限 deny 和 Hook deny 有什么区别？
        A: 权限 deny 是系统级决策，优先级最高
        Hook deny 是业务逻辑扩展点
        权限 deny 后不会触发 PreToolUse
        Hook deny 后仍会触发 PostToolUse
      Q5: 为什么 Hook 要用不可变对象？
        A: 防止回调间相互影响
        确保每个回调看到一致的上下文
        通过 replace() 声明式修改
        符合函数式编程原则
      Q6: Stop Hook 有什么用？
        A: 在 Agent 结束前追加总结
        可以注入最终上下文消息
        用于审计、日志、清理工作
        看到完整对话历史
      Q7: 如何区分同步和异步 Hook？
        A: 回调签名决定：def 同步，async def 异步
        HookRegistry 自动识别
        同步回调直接调用，异步回调用 await
        inspect.iscoroutinefunction 判断
```

## 说明

本文件是 `ch04_learning_roadmap.xmind` 的 Markdown 备份版本，使用 Mermaid mindmap 格式。

可以在支持 Mermaid 的工具中查看（如 GitHub、Typora、VS Code + Markdown Preview Enhanced 等）。
