# 第 7 章：按需加载 Skill 学习路线图

```mermaid
mindmap
  root((第 7 章：按需加载 Skill))
    学习路线（推荐顺序）
      第一步：理解 Skill 延迟加载设计（15分钟）
        agent_ch07/features/skills.py
        核心类：SkillRegistry
        扫描阶段只读 frontmatter
        加载阶段读取完整正文
      第二步：阅读路径安全边界（10分钟）
        _validate_skill_name 名称校验
        _resolve_skill_root 目录解析
        _checked_real_directory 防逃逸
        防止符号链接穿越
      第三步：理解两级加载流程（15分钟）
        SkillRegistry.scan() 扫描元数据
        render_catalog() 生成目录
        load_skill() 加载正文
        _handle_load() 工具处理器
      第四步：浏览集成测试（10分钟）
        tests/test_skills.py
        tests/test_ch07_integration.py
        理解 Skill 如何被注册和调用
    
    核心文件清单
      agent_ch07/features/skills.py（本章核心）
        SkillRegistry 类
          scan() 扫描 Skill 目录
          render_catalog() 生成目录
          load_skill() 加载正文
          tool_definition 工具定义
        路径安全函数
          _validate_skill_name
          _resolve_skill_root
          _checked_real_directory
          _checked_real_file
        数据类型
          SkillSummary（目录条目）
          _SkillRecord（内部记录）
        异常类型
          SkillPathError（路径逃逸）
          SkillManifestError（manifest错误）
          SkillNotFoundError（未找到）
          SkillNameError（名称非法）
      agent_ch07/bootstrap.py（接线）
        build_agent 组合根
        P07 Profile 包含 skills 能力
        注册 load_skill 工具
        父子 Agent 都能调用 load_skill
      继承自前章的能力
        core/loop.py（Agent循环）
        core/hooks.py（Hook生命周期）
        core/permissions.py（权限策略）
        features/subagents.py（子Agent）
        features/todos.py（TODO追踪）
    
    Java 对照关系
      SkillRegistry 类比
        类似只读配置注册表
        scan() = @PostConstruct 初始化
        load_skill() = 延迟加载服务方法
        tool_definition = Bean 注册
      数据结构对照
        SkillSummary = DTO record
        _SkillRecord = 内部领域对象
        frozenset = Collections.unmodifiableSet()
        Path.resolve() = Files.realPath()
      安全校验对照
        _validate_skill_name = Bean Validation
        _is_inside() = 路径包含判断
        realpath 防符号链接 = 防路径穿越
        Windows保留名 = 跨平台兼容
      异常处理对照
        SkillError = 业务异常基类
        领域错误 -> tool_error()
        不向模型暴露堆栈
        错误码稳定可解析
    
    设计模式识别
      延迟加载（Lazy Loading）
        扫描阶段只读元数据
        真正使用时才加载正文
        节省启动时 System Prompt 空间
        适用于大量可选技能场景
      工厂方法
        SkillRegistry.scan() 类工厂
        校验后返回不可变注册表
        封装复杂创建逻辑
      门面模式（Facade）
        SkillRegistry 封装路径校验细节
        对外提供简单的 load_skill 接口
        隐藏 frontmatter 解析复杂度
      防御式边界
        扫描和加载都检查路径安全
        拒绝绝对路径和 .. 片段
        防止符号链接替换后逃逸
        Windows 保留名黑名单
    
    关键概念理解
      为什么需要两级加载
        System Prompt 有长度限制
        模型可能有几十个可用 Skill
        启动时只给名称和一句描述
        模型决定需要哪个才加载正文
      路径安全边界
        所有 Skill 必须在 workspace/skills 内
        名称只能用小写字母数字和连字符
        拒绝 ../、绝对路径、Windows 设备名
        扫描和加载都做 realpath 校验
      frontmatter 元数据
        YAML 格式，包裹在 --- 之间
        必须字段：name、description
        name 必须等于目录名
        description 必须是非空单行
      目录预算控制
        最多 100 条（DEFAULT_MAX_CATALOG_ENTRIES）
        最多 8000 UTF-8 字节
        不截断半条目录行
        按名称排序保证稳定
    
    面试题速查
      Q1: ch07 相比 ch06 新增了什么核心能力？
        A: 按需加载 Skill（技能系统）
        启动时只扫描 frontmatter 元数据
        模型调用 load_skill 工具时才加载完整正文
        节省 System Prompt 空间，支持大量可选技能
      Q2: 为什么 Skill 需要两级加载？
        A: System Prompt 长度受限
        可能有几十个 Skill，全部加载会超限
        启动时只给目录（名称+描述）
        模型判断需要哪个才调用 load_skill
      Q3: Skill 路径安全边界如何保证？
        A: 名称只允许 [a-z0-9-]，拒绝 .. 和绝对路径
        扫描和加载都检查 realpath 仍在 workspace 内
        防止符号链接替换后路径逃逸
        拒绝 Windows 设备名（NUL、CON 等）
      Q4: frontmatter 是什么，包含哪些字段？
        A: YAML 格式的 Skill 元数据
        包裹在两个 --- 之间
        必须包含 name（等于目录名）和 description（单行）
        扫描阶段只读这部分，不读取正文
      Q5: SkillRegistry.scan() 和 load_skill() 的区别？
        A: scan() 在启动时执行一次
        遍历 skills/ 目录，只读取每个 SKILL.md 的 frontmatter
        load_skill() 在模型调用时执行
        重新校验路径，读取完整正文并返回
      Q6: 为什么加载时要重新校验路径？
        A: 防止扫描后符号链接被替换
        攻击者可能在扫描后修改链接指向
        加载时重新 realpath 并判断是否仍在边界内
        TOCTOU（Time-of-Check Time-of-Use）防御
      Q7: 子 Agent 能调用 load_skill 吗？
        A: 可以
        bootstrap.py 中 child_tools_factory 注册了 load_skill
        但子 Agent 仍然没有 task 工具（不能再次委派）
        Skill 正文只进入调用它的那条历史
```

## 核心概念速记

**两级加载模式**：
- 第一层（启动时）：扫描 `skills/` 目录，只读取 `SKILL.md` 的 frontmatter（name + description）
- 第二层（使用时）：模型调用 `load_skill` 工具时，重新校验路径并读取完整正文

**路径安全边界**：
- 名称只能是 `[a-z0-9-]+`，拒绝 `..`、绝对路径和 Windows 设备名
- 扫描和加载都做 `realpath` 校验，防止符号链接逃逸
- 所有 Skill 必须在 `workspace/skills/` 目录内

**frontmatter 元数据**：
```yaml
---
name: python-style
description: Use when 编写或审查 Python 模块；Don't use for SQL。
---
# Python Style

外部输入先按 unknown 思路处理...
```

**目录预算控制**：
- 最多 100 条 Skill（可配置）
- 最多 8000 UTF-8 字节（可配置）
- 不截断半条目录行，按名称排序

**与 ch06 对比**：
- ch06：子 Agent + TODO 追踪
- ch07：在 ch06 基础上新增按需加载 Skill
- 父子 Agent 都能调用 `load_skill`，但子 Agent 无 `task` 工具

## 学完你会掌握

✓ 延迟加载模式的设计与实现  
✓ 路径安全边界的防御式编程  
✓ frontmatter 元数据解析  
✓ TOCTOU 攻击防御（Time-of-Check Time-of-Use）  
✓ 工具注册表的动态扩展  
✓ 目录预算控制与截断策略
