# 第 9 章：文件级长期记忆 - 学习路线图

## 学习路线（推荐顺序）

### 第一步：读测试了解目标
- **tests/test_memory.py**
- 看记忆如何保存和选择
- 理解三文件协议

### 第二步：读记忆核心系统
- **features/memory.py**
  - MemoryRecord 值对象
  - MemoryStore 文件事务
  - MemorySession 生命周期

### 第三步：理解集成点
- **core/loop.py TurnLifecycle**
- **bootstrap.py P09 配置**
- **tests/test_ch09_integration.py**

---

## 核心文件清单

### features/memory.py（记忆系统）

#### MemoryRecord 值对象
- **name**: 逻辑名称（slug）
- **description**: 一行摘要
- **kind**: 分类（user/feedback/project/reference）
- **body**: 完整正文

#### MemoryStore Repository
- **save()**: 保存记忆
- **list()**: 列出所有记忆
- **get()**: 读取单条记忆
- **delete()**: 删除记忆
- **_commit()**: 原子事务

#### MemorySession 生命周期
- **begin_turn()**: 选择相关记忆
- **before_model()**: 注入记忆上下文
- **complete()**: 提取新记忆
- **_consolidate()**: 整理合并

#### 三个模型查询
- **_select_memory_names()**: 选择器
- **_extract_memories()**: 提取器
- **_consolidate()**: 整理器

### core/loop.py（生命周期接口）
- **TurnLifecycle Protocol**
- **begin_turn()**: 回合开始前
- **before_model()**: 模型请求前
- **complete()**: 回合结束后

### bootstrap.py（依赖注入）
- **P09 配置**
- 装配 MemoryStore
- 装配 MemorySession
- 注入生命周期

### 三文件协议
- **manifest.json**: 权威指针
- **MEMORY.md**: 轻量目录
- **<name>-<id>.md**: 记忆正文

---

## Java 对照关系

### 架构层次对照
- **MemoryRecord** = record 值对象
- **MemoryStore** = Repository + 本地事务
- **MemorySession** = HandlerInterceptor
- **TurnLifecycle** = 生命周期 interface

### 持久化对照
- **manifest.json** = 数据库主表
- **MEMORY.md** = 查询视图（可重建）
- **临时目录 + rename** = 文件事务
- **RLock** = synchronized 锁

### 模式对照
- **side-query** = 服务内调用
- **selector** = 查询服务
- **extractor** = 解析服务
- **consolidator** = 整理服务

### 数据结构对照
- **frozenset** = Set.of()
- **Path.resolve()** = File.getCanonicalPath()
- **yaml.safe_load** = Jackson YAML
- **tempfile.mkdtemp** = Files.createTempDirectory()

---

## 设计模式识别

### Repository 模式
- MemoryStore 封装文件操作
- 统一的 CRUD 接口
- 路径安全和事务保证

### 拦截器模式
- MemorySession 实现 TurnLifecycle
- 回合前选择记忆
- 回合后提取记忆

### 事务模式
- 临时目录写入所有文件
- 原子 rename 到目标位置
- manifest 最后更新

### 值对象模式
- MemoryRecord 不可变
- frozen dataclass
- __post_init__ 校验

### 策略模式
- 三个模型查询函数
- 可独立测试和替换
- 无工具 side-query

---

## 关键概念理解

### 记忆生命周期
1. **begin_turn**: 选择相关记忆
2. **before_model**: 临时注入上下文
3. **Agent Loop**: 正常执行
4. **complete**: 提取新记忆
5. **达到阈值时**: 整理合并

### 三文件协议
- **manifest.json** 是权威指针
- **MEMORY.md** 是可重建目录
- **<name>-<id>.md** 是记忆正文
- 三者必须保持一致

### 文件事务原子性
1. 先写临时目录
2. 原子 rename 所有文件
3. manifest 最后更新
4. 失败时临时目录被丢弃

### 无工具 side-query
- **selector**: 选择相关记忆名称
- **extractor**: 从对话提取新记忆
- **consolidator**: 整理合并重复
- 模型只提供决策，不直接操作文件

### 记忆注入方式
- 临时 system 消息
- 只影响当前请求
- 不追加到 canonical history
- 下次回合自动消失

### 整理触发时机
- 累积 5 条待处理记忆
- 调用 consolidator 合并
- 删除旧记忆文件
- 原子保存新记忆

---

## 面试题速查

### Q1: 第 9 章的记忆和第 8 章的压缩有什么区别？
**A**: 
- 压缩在当前会话内减少 token
- 记忆是跨会话保留知识
- 压缩丢失细节但保留脉络
- 记忆保留核心事实但不是完整对话

### Q2: 为什么 manifest.json 和 MEMORY.md 要分离？
**A**: 
- manifest 是事务权威（JSON 易解析）
- MEMORY.md 是轻量目录（模型友好）
- MEMORY.md 可以从 manifest 重建
- 选择器不需要解析完整 JSON

### Q3: 记忆的文件事务如何保证原子性？
**A**: 
- 先写临时目录（所有 .md 文件）
- 最后原子 rename 到目标路径
- 中途失败则临时目录被丢弃
- manifest.json 最后更新保证一致性

### Q4: 为什么记忆不是模型可直接调用的普通工具？
**A**: 
- 普通工具调用可能被拒绝或重试
- 会破坏事务一致性
- 用无工具 side-query + 受控 Store
- 保证逻辑由系统控制，模型只提供决策

### Q5: 记忆注入为什么用临时 system 消息？
**A**: 
- 记忆是辅助上下文，不应污染 history
- 临时注入只影响当前模型请求
- 下次回合自动消失
- history 保持对话真相

### Q6: 整理（consolidate）的触发时机和作用？
**A**: 
- 累积 5 条待处理记忆时触发
- 合并重复记忆、解决冲突、压缩冗余
- 输出 source_names（要替换的旧记忆）
- 输出 records（整理后的新记忆）
