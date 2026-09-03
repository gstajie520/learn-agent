# 第 5 章：TODO 跟踪与观察器模式

```mermaid
mindmap
  root((第 5 章：TODO 跟踪与观察器模式))
    学习路线（推荐顺序）
      第一步：理解工具轮观察器
        core/loop.py:ToolRoundObserver
        before_model() 临时指导消息
        record_tool_round() 记录工具名
      第二步：读 TODO 追踪器
        features/todos.py
        TodoTracker 同时是工具和观察器
        会话级状态管理
      第三步：理解防抖提醒
        连续 N 轮未更新 TODO
        before_model 触发临时提醒
        提醒后立即重置计数器
      第四步：集成测试
        tests/test_ch05_integration.py
        验证 TODO 提醒机制
        验证完整快照提交
    
    核心文件清单
      features/todos.py（TODO 追踪器）
        TodoTracker 类
          _todos: 当前任务快照
          _non_todo_tool_rounds: 计数器
          tool_definition: todo_write 工具
          before_model() 临时提醒
          record_tool_round() 计数逻辑
        TodoItem 数据类
          content: 任务描述
          status: 三态枚举
        常量定义
          MAX_TODOS = 50
          STALE_TOOL_ROUNDS = 3
          TODO_STALE_REMINDER
      core/loop.py（观察器集成）
        ToolRoundObserver 接口
        before_model() → 临时指导
        record_tool_round() → 整轮记录
        observer_guidance 不进入 history
      bootstrap.py（组合根）
        第 5 章能力检查
        创建 TodoTracker
        注册 todo_write 工具
        作为 tool_round_observer 注入
    
    Java 对照关系
      设计模式对照
        TodoTracker = 观察者 + 工具
        ToolRoundObserver = interface
        before_model = 模板方法钩子
        record_tool_round = 事件回调
      状态管理对照
        _todos = 会话级私有状态
        todos 属性 = getter
        _write_todos = handler 修改状态
        无持久化 = 会话结束即消失
      数据结构对照
        tuple[TodoItem, ...] = List.copyOf
        TodoStatus = 字面量枚举
        MAX_TODOS = static final int
        _serialize_snapshot = toJson()
      校验对照
        _validate_todo_input = 严格校验
        set(value) != {"todos"} = 拒绝未知字段
        validator 参数 = JSON Schema
        prepare 前校验 = Bean Validation
    
    设计模式识别
      观察者模式
        AgentRunner = 主题
        TodoTracker = 观察者
        工具轮结束 = 事件通知
        before_model = 反向影响
      单一职责
        TodoTracker 只管 TODO 状态
        不关心权限、Hook 或模型
        AgentRunner 负责调度
      防抖机制
        连续 3 轮未更新才提醒
        提醒后立即重置计数
        避免每轮都提醒骚扰模型
      完整快照提交
        todo_write 要求提交全部任务
        不支持增量修改
        降低并发冲突复杂度
    
    关键概念理解
      工具轮观察器
        工具轮 = assistant + 所有 tool 结果
        整轮结束后才计数
        观察器不能看到半轮状态
      临时指导消息
        只拼到本次 ModelRequest
        不进入正式 history
        下次请求自动消失
      会话级状态
        TODO 只存在于当前会话
        AgentRunner 销毁即消失
        不持久化到磁盘或数据库
      为什么是完整快照
        避免 CRUD 接口复杂度
        模型提交完整 JSON 更简单
        无需处理增删改冲突
      为什么计数按轮
        一轮可能调用多个工具
        按调用数会误判
        整轮统计更稳定
    
    面试题速查
      Q1: 观察器模式和 Hook 有什么区别？
        A: Hook 可以修改或阻断工具调用
        观察器只能被动观察和记录
        Hook 在单次调用链路，观察器在整轮结束
      Q2: 为什么 before_model 返回的消息不进 history？
        A: 临时指导只对下次请求生效
        持久化会污染长期历史
        防止提醒累积消耗 token
      Q3: 为什么 TODO 用完整快照而不是增量更新？
        A: 避免实现 add/update/delete 三个接口
        模型生成完整 JSON 更简单
        无需处理并发修改冲突
      Q4: 为什么计数器按工具轮而不是调用次数？
        A: 一轮可能调用多个工具
        按次数统计会误判
        整轮结束才计数更准确
      Q5: TodoTracker 的状态在哪里存储？
        A: 存在 TodoTracker 实例的私有字段
        会话级状态，不持久化
        AgentRunner 销毁时自动消失
      Q6: 防抖机制为什么是 3 轮？
        A: 经验值，平衡提醒及时性和骚扰度
        太小会频繁提醒干扰模型
        太大会导致计划长期过时
      Q7: observer_guidance 在循环的哪个位置注入？
        A: 构建 ModelRequest 时拼到末尾
        在 history 之后，不进入 history
        下次循环时不再出现
```

## 学习建议

1. **先理解接口**：从 `ToolRoundObserver` 接口开始，理解观察器的契约
2. **再看实现**：阅读 `TodoTracker` 如何同时实现工具和观察器两个角色
3. **理解时机**：明确 `before_model` 和 `record_tool_round` 的调用时机
4. **对比 Hook**：理解观察器（只读）和 Hook（可修改）的区别
5. **调试验证**：用测试验证防抖机制和完整快照提交

## 核心设计理念

- **观察者模式**：TodoTracker 观察工具轮，但不干预执行
- **临时指导**：提醒消息不污染长期历史
- **完整快照**：避免增量修改的复杂度
- **防抖机制**：平衡提醒及时性和干扰度
- **会话级状态**：状态生命周期与 AgentRunner 一致
