# 第 10 章：动态模块化 System Prompt 学习导航图

## 学习脑图

```mermaid
mindmap
  root((第 10 章<br/>动态模块化 System Prompt))
    学习路线（推荐顺序）
      第一步：理解为什么需要动态 Prompt
        之前：静态 system_prompt 字符串
        问题：无法感知工具变化
        问题：无法感知记忆选择
        问题：无法感知 Skill 加载
      第二步：读 Renderer 测试
        tests/test_prompting.py
        看输入状态如何变成 Prompt
        理解固定顺序的 section
        理解缓存机制
      第三步：读核心实现
        features/prompting.py
        DynamicPromptRenderer 类
        DynamicPromptProvider 类
        严格 JSON 校验逻辑
      第四步：看与 AgentRunner 集成
        core/loop.py 的 SystemPromptProvider
        bootstrap.py 的依赖绑定
        tests/test_ch10_integration.py
    核心文件清单
      features/prompting.py（核心渲染器）
        DynamicPromptRenderer
          render 方法（从运行态生成 Prompt）
          cache_hits 属性（缓存命中统计）
          _last_key 字段（缓存键）
          _last_prompt 字段（缓存值）
        DynamicPromptProvider
          render 方法（零参数接口）
          构造器注入依赖
        辅助函数
          _normalize_identity
          _normalize_context
          _stable_json
      core/loop.py（接口定义）
        SystemPromptProvider Protocol
          render 方法签名
        AgentRunner 集成
          接受 SystemPromptProvider
          每轮调用 provider.render()
      bootstrap.py（组合根）
        _build_dynamic_prompt_provider
        绑定 Renderer + 依赖
        返回零参数 Provider
      core/profiles.py（章节配置）
        P10 = dynamic_prompt 能力
    Java 对照关系
      设计模式对照
        SystemPromptProvider = Supplier<String>
        DynamicPromptRenderer = View Renderer
        DynamicPromptProvider = Service Adapter
        固定顺序 section = 模板方法模式
      类型系统对照
        TypeAlias = 类型别名
        JsonValue 递归类型 = 自引用泛型
        Mapping[str, object] = Map<String, Object>
        cast = 类型强制转换
      缓存设计对照
        实例字段缓存 = 对象级缓存
        _last_key 比对 = equals() 方法
        _stable_json = 稳定序列化
    设计模式识别
      模板方法模式
        固定 section 顺序
        identity → tools → workspace → skills → memory
        子部分可选但顺序不变
      策略模式
        AgentRunner 只依赖接口
        不知道 Prompt 如何组装
        测试时可替换 Fake Provider
      依赖注入
        Provider 绑定所有依赖
        Renderer 无状态可复用
        引用传递感知变化
      缓存策略
        实例级缓存
        基于稳定 JSON 键
        状态变化自动失效
    关键概念理解
      为什么需要动态 Prompt
        工具注册表可能变化
        记忆选择每轮不同
        Skill 目录按需加载
        静态字符串无法感知
      固定顺序的意义
        identity 必须在最前
        tools 需要优先说明
        workspace 定义操作边界
        skills 和 memory 可选
      严格 JSON 校验
        context 必须可序列化
        拒绝循环引用
        拒绝 NaN/Infinity
        拒绝非字符串键
      缓存设计原理
        避免重复序列化
        键包含所有输入
        实例级防止跨 Agent 污染
      Provider 零参数接口
        封装所有依赖
        调用方无需传参
        类似 Supplier<String>
    面试题速查
      Q1：为什么不用静态 system_prompt 字符串
        A：无法感知运行态变化
        A：无法反映工具注册状态
        A：无法注入选中记忆
      Q2：为什么 section 顺序固定
        A：identity 是最高优先级指令
        A：tools 定义能力边界
        A：workspace 定义操作范围
        A：固定顺序易于测试和调试
      Q3：为什么 context 必须是严格 JSON
        A：避免不可序列化对象
        A：保证缓存键稳定
        A：支持跨语言通信
      Q4：缓存失效条件是什么
        A：工具列表变化
        A：记忆选择变化
        A：Skill 目录变化
        A：workspace 路径变化
      Q5：为什么用 tuple 而不是 list
        A：不可变保证稳定性
        A：可作为 JSON 数组序列化
        A：防止外部修改
      Q6：Provider 和 Renderer 的职责边界
        A：Renderer 负责渲染逻辑
        A：Provider 负责依赖绑定
        A：Runner 只依赖 Provider 接口
      Q7：为什么缓存放实例字段而非全局
        A：避免跨 Agent 污染
        A：每个 Agent 独立缓存
        A：便于测试和统计
      Q8：如何确保 JSON 序列化稳定
        A：sort_keys=True 排序键
        A：separators 固定格式
        A：递归标准化所有值
```

## Java 开发者 3 步速通指南

### 第 1 步：从测试理解需求（10 分钟）
```bash
# 阅读 Renderer 测试，理解输入输出
cat tests/test_prompting.py

# 关注点：
# - 输入：identity, tools, workspace, context, skills, memory
# - 输出：固定格式的多 section Prompt
# - 缓存：相同输入复用上次结果
```

**Java 对照**：这就像先读 `PromptRendererTest.java`，理解从 DTO 到模板字符串的转换。

### 第 2 步：读核心渲染逻辑（20 分钟）
```bash
# 阅读带详细注释的渲染器
cat features/prompting.py

# 阅读顺序：
# 1. SystemPromptProvider Protocol（接口定义）
# 2. DynamicPromptRenderer.render（核心渲染）
# 3. DynamicPromptProvider（依赖绑定）
# 4. _normalize_context（严格 JSON 校验）
```

**关键理解**：
- `SystemPromptProvider` = Java 的 `Supplier<String>`
- `DynamicPromptRenderer` = 无状态 View Renderer
- `DynamicPromptProvider` = 绑定依赖的 Adapter
- `_stable_json()` = 稳定序列化（固定键顺序）

### 第 3 步：理解集成方式（15 分钟）
```bash
# 看 AgentRunner 如何使用 Provider
grep -A 10 "SystemPromptProvider" core/loop.py

# 看 Bootstrap 如何绑定依赖
grep -A 20 "_build_dynamic_prompt_provider" bootstrap.py

# 看完整流程的集成测试
cat tests/test_ch10_integration.py
```

**不要深入细节**：只需理解 Provider 如何从组合根传递给 AgentRunner。

---

## 核心类比速查表

| Python 概念 | Java 对照 | 用途 |
|------------|----------|------|
| `SystemPromptProvider` | `Supplier<String>` | 零参数提供者接口 |
| `TypeAlias` | 类型别名 | 定义复杂类型的简短名称 |
| `cast()` | 类型强制转换 | 告诉类型检查器相信你 |
| `Mapping[K, V]` | `Map<K, V>` | 只读映射接口 |
| `frozenset` | `Set.copyOf()` | 不可变集合 |
| `tuple[T, ...]` | `List.copyOf()` | 不可变列表 |
| `id(obj)` | `System.identityHashCode()` | 对象身份哈希 |
| `math.isfinite()` | `Double.isFinite()` | 检查有限数字 |

---

## 学完本章你会理解

✅ **动态 Prompt 的必要性**：静态字符串无法感知运行态变化  
✅ **固定 section 顺序**：identity → tools → workspace → skills → memory  
✅ **严格 JSON 校验**：拒绝循环引用、非有限数字、非字符串键  
✅ **实例级缓存策略**：基于稳定 JSON 键，避免重复序列化  
✅ **Provider 接口模式**：封装依赖，零参数调用  
✅ **引用传递感知变化**：保存对象引用而非快照  

---

## 常见问题 FAQ

### Q1: 为什么不在 Bootstrap 时生成一次 Prompt 就固定？
**A**: 因为工具可能动态注册、记忆每轮选择不同、Skill 按需加载。Provider 每轮读取最新状态，确保 Prompt 反映当前运行态。

### Q2: 为什么 context 必须是严格 JSON 而不是任意 Python 对象？
**A**: 因为 context 会被序列化作为缓存键，必须保证稳定性。拒绝循环引用、自定义类、NaN 等不可序列化值。类比 DTO 必须是简单 POJO。

### Q3: 为什么缓存放实例字段而不是模块全局变量？
**A**: 因为每个 AgentRunner 有独立的运行态。全局缓存会导致 Agent A 的 Prompt 被 Agent B 误用。类似线程局部存储。

### Q4: `_stable_json` 为什么要 `sort_keys=True`？
**A**: 因为 Python dict 的迭代顺序虽然从 3.7 开始保证插入顺序，但不同构建路径可能产生不同顺序。排序键保证相同内容得到相同 JSON 字符串。

### Q5: 为什么 Provider 保存对象引用而不是值快照？
**A**: 因为要感知运行态变化。保存 `ToolRegistry` 引用后，下一轮调用 `tools.names` 能读取最新工具列表。类似依赖注入的引用传递。

### Q6: 为什么工具列表空时显示 `(none)` 而不是省略 section？
**A**: 因为 tools section 是必需的，明确显示 `(none)` 比完全省略更清晰，告诉模型当前没有可用工具。

### Q7: 为什么用 `TypeAlias` 而不是直接写联合类型？
**A**: 因为 `JsonValue` 是递归类型（`dict[str, JsonValue]`），必须先声明别名再自引用。类似 Java 的前向声明。

---

## 下一步学习建议

1. **动手运行测试**：`pytest tests/test_prompting.py -v`
2. **修改 context**：添加非 JSON 值，看校验如何失败
3. **观察缓存命中**：打印 `renderer.cache_hits`，理解何时复用
4. **实现自定义 Provider**：练习 `SystemPromptProvider` 接口

---

## 文件依赖关系图

```
DynamicPromptRenderer (features/prompting.py)
    └── render() → 读取运行态 → 生成固定格式 Prompt

DynamicPromptProvider (features/prompting.py)
    ├── depends on → DynamicPromptRenderer
    ├── depends on → ToolRegistry (引用)
    ├── depends on → SkillRegistry (引用)
    └── depends on → MemorySession (引用)

AgentRunner (core/loop.py)
    └── depends on → SystemPromptProvider (接口)

Bootstrap (bootstrap.py)
    └── 组装 → DynamicPromptProvider → 注入 AgentRunner
```

---

## 调试断点速查（VSCode/PyCharm 适用）

### 【必打断点】理解主流程（5 个）

**[1] prompting.py:71** → `DynamicPromptRenderer.render()` 方法开始  
观察：identity, tools.names, workspace, skills, memory  
目的：确认输入参数是否符合预期

**[2] prompting.py:100** → 缓存键比对前  
观察：key, self._last_key, 是否相等  
目的：理解缓存何时命中、何时失效

**[3] prompting.py:116** → 准备返回最终 Prompt 前  
观察：sections 列表内容、prompt 字符串  
目的：检查生成的 Prompt 格式是否正确

**[4] prompting.py:152** → `DynamicPromptProvider.render()` 转发调用  
观察：self._tools.names, self._memory.selected  
目的：确认读取的是最新运行态

**[5] prompting.py:212** → `_normalize_json_value()` 递归校验  
观察：value 类型、active 集合（检测循环引用）  
目的：理解严格 JSON 校验的逻辑

### 【可选断点】深入理解（3 个）

**[6] prompting.py:83** → `_stable_json()` 序列化  
观察：normalized_context 的结构  
目的：理解如何生成稳定缓存键

**[7] loop.py:XXX** → AgentRunner 调用 `provider.render()`  
观察：返回的 system_prompt 字符串  
目的：确认每轮读取最新 Prompt

**[8] bootstrap.py:XXX** → `_build_dynamic_prompt_provider()` 组装  
观察：renderer, tools, skills, memory 引用  
目的：理解依赖如何绑定

---

## 总结：动态 Prompt 的三个核心价值

1. **感知运行态变化**：工具、记忆、Skill 变化自动反映在 Prompt 中
2. **固定顺序可预测**：identity → tools → workspace → skills → memory
3. **实例级缓存优化**：相同输入复用结果，避免重复序列化

**记住**：`DynamicPromptRenderer` 是展示层，不负责发现工具或选择记忆；它只从运行态对象读取已有状态。
