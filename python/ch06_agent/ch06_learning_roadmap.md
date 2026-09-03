# 第 6 章学习路线图

```mermaid
mindmap
  root((第 6 章：子 Agent + TODO 跟踪器))
    学习路线（推荐顺序）
      第一步：理解 TODO 跟踪器
        features/todos.py
        TodoTracker 如何记录计划快照
        _check_stale_plan 检测过期计划
      第二步：理解子 Agent 机制
        features/subagents.py
        SubagentTool 委派任务
        父子 Agent 的隔离与共享
      第三步：理解循环集成点
        core/loop.py
        ToolRoundObserver 观察器协议
        Hook 集成的 TODO 提醒
    
    核心文件清单
      features/todos.py（TODO 跟踪器）
        TodoTracker 类
          observe_tool_round（记录工具轮次）
          _check_stale_plan（检测过期计划）
          _install_hooks（安装 Hook）
        TODO 工具实现
          todo_read_tool（读取计划）
          todo_write_tool（更新计划）
          todo_archive_tool（归档计划）
      features/subagents.py（子 Agent）
        SubagentTool 类
          task 工具定义
          创建隔离的 AgentRunner
          父子共享 Hook 和权限
        工厂接口
          ModelClientFactory
          ToolRegistryFactory
      core/loop.py（循环扩展）
        ToolRoundObserver 协议
        observe_tool_round 回调点
        max_turns 检查前通知观察器
      bootstrap.py（组合根）
        P06 Profile
        组装 todo + subagent 能力
        子 Agent 模型工厂配置
    
    Java 对照关系
      子 Agent 对照
        SubagentTool = @Service 委派服务
        父子隔离 = 创建新的 Service 实例
        共享 Hook = 依赖注入相同的监听器
      观察器对照
        ToolRoundObserver = 观察者接口
        observe_tool_round = @EventListener
        可选观察器 = Optional<Observer>
      工厂对照
        ModelClientFactory = Supplier<ModelClient>
        ToolRegistryFactory = Supplier<Registry>
        返回 tuple = 返回配对对象
      状态管理对照
        _snapshot = 快照对象
        _rounds_since_write = 计数器
        _check_stale_plan = 定时检查逻辑
    
    设计模式识别
      观察者模式
        ToolRoundObserver 协议
        循环通知观察器
        解耦循环与跟踪逻辑
      工厂模式
        ModelClientFactory
        ToolRegistryFactory
        每次创建独立实例
      策略模式
        Hook 定制 TODO 提醒
        可选观察器注入
        灵活的扩展点
      模板方法
        子 Agent 复用循环结构
        固定的 system_prompt
        独立的 max_turns
    
    关键概念理解
      TODO 快照机制
        todo_write 记录快照
        每轮检查是否过期
        3 轮未更新触发提醒
      父子 Agent 隔离
        独立的消息历史
        独立的工具注册表
        独立的 TODO 跟踪器
      父子 Agent 共享
        共享 HookRegistry
        共享 PermissionPolicy
        共享工作区和身份
      观察器协议优势
        核心循环不感知 TODO 细节
        可选注入灵活扩展
        符合开闭原则
    
    面试题速查
      Q1: 什么是 TODO 跟踪器的快照机制？
        A: 模型调用 todo_write 时记录计划快照
        每轮工具执行后检查是否 3 轮未更新
        过期时通过 Hook 注入提醒消息
      Q2: 父子 Agent 如何做到隔离和共享？
        A: 隔离：独立的历史、工具表、TODO 跟踪器
        共享：Hook、权限策略、工作区、身份
        通过工厂模式创建独立实例
      Q3: ToolRoundObserver 协议的作用是什么？
        A: 定义观察器接口，在每轮工具执行后回调
        核心循环通过协议通知观察器
        TodoTracker 实现该协议检测过期计划
      Q4: 子 Agent 为什么不能再委派子 Agent？
        A: system_prompt 明确禁止再次委派
        避免委派层级过深
        保持任务边界清晰
      Q5: 为什么 TODO 工具需要三个操作？
        A: read 查看当前计划
        write 更新计划并记录快照
        archive 完成后清空状态
      Q6: 子 Agent 的 max_turns 如何设置？
        A: 默认 30 轮（父 Agent 通常 20 轮）
        子任务通常需要更多步骤
        测试可调低，生产不能调高
      Q7: 如何测试 TODO 过期检测逻辑？
        A: 模拟 todo_write 记录快照
        连续 3 次 observe_tool_round 不再 write
        第 4 轮触发 Hook 提醒
```

## 使用说明

这个 Markdown 文件包含 Mermaid mindmap 格式的脑图，可以在以下环境中渲染：
- GitHub/GitLab 的 Markdown 预览
- VSCode + Mermaid 插件
- 支持 Mermaid 的在线编辑器（如 mermaid.live）

如果需要更好的交互体验，建议使用 `ch06_learning_roadmap.xmind` 文件。
