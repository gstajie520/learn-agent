# 第 8 章：上下文压缩 Compaction 学习路线图

```mermaid
mindmap
  root((第 8 章：上下文压缩 Compaction))
    学习路线（推荐顺序）
      第一步：理解压缩动机
        为什么需要压缩？
        对话历史达到 token 上限
        大工具结果占用过多上下文
        模型调用成本和延迟
      第二步：读核心文件
        features/compaction.py
        CompactionManager 类
        MessageGroup 概念
        ArtifactStore 归档机制
      第三步：理解压缩策略
        响应式压缩（超限时触发）
        主动式压缩（预防超限）
        保留最近消息组
        总结旧消息
      第四步：读测试验证
        tests/test_compaction.py
        tests/test_ch08_integration.py
        理解压缩前后对比
    
    核心文件清单
      features/compaction.py（核心实现）
        CompactionManager 类
          prepare() - 历史处理器
          compact_tool_results() - 结果处理器
          两个 Protocol 接口的实现
        MessageGroup 概念
          assistant + tool_calls 配对
          不可拆分的原子单元
          保证消息协议完整性
        ArtifactStore 归档
          大结果写入磁盘
          消息保留引用 ID
          按需读取
        ModelHistorySummarizer
          调用模型总结旧消息
          生成压缩摘要
          减少上下文占用
      core/loop.py（集成点）
        history_processor 参数
        tool_result_processor 参数
        在请求前调用 prepare()
        在结果回填前调用 compact_tool_results()
      bootstrap.py（组装）
        P08 Profile 启用 compaction
        传入 CompactionManager
        注入到 AgentRunner
    
    Java 对照关系
      架构对照
        CompactionManager = Service
        MessageGroup = 不可变 DTO
        ArtifactStore = FileRepository
        Protocol 接口 = interface
      处理器模式
        RequestHistoryProcessor = 请求拦截器
        ToolResultProcessor = 响应拦截器
        类似 Servlet Filter 链
      数据结构
        tuple = List.copyOf()
        dataclass(frozen=True) = record
        bytes 计算 = UTF-8 编码
      文件操作
        Path = java.nio.file.Path
        write_text() = Files.writeString()
        read_text() = Files.readString()
    
    设计模式识别
      策略模式
        可选注入 CompactionManager
        可替换压缩策略
        测试时可用假实现
      适配器模式
        实现 Protocol 接口
        适配到 AgentRunner
        解耦核心循环和压缩逻辑
      模板方法
        固定调用时机
        请求前 prepare()
        结果后 compact_tool_results()
      组合模式
        MessageGroup 递归结构
        可以嵌套分组
        统一处理单个和批量
    
    关键概念理解
      为什么需要压缩
        模型上下文窗口有限
        长对话历史超出限制
        大工具结果占用过多
        成本和延迟问题
      MessageGroup 为什么不可拆分
        OpenAI API 协议要求
        tool_call 必须有配对结果
        拆分会导致 API 拒绝
        保证消息完整性
      响应式 vs 主动式压缩
        响应式：超限后压缩
        主动式：预防超限
        主动式更平滑
        避免紧急压缩
      为什么用字节数不用字符数
        模型计费按 token
        中文字符占多字节
        UTF-8 编码更准确
        避免低估上下文
    
    面试题速查
      Q1: 为什么需要上下文压缩？
        A: 模型上下文窗口有限
        长对话历史超出限制
        减少成本和延迟
      Q2: MessageGroup 为什么不能拆分？
        A: OpenAI API 协议要求
        每个 tool_call 必须有配对结果
        拆分会导致 400 错误
      Q3: 响应式和主动式压缩有什么区别？
        A: 响应式在超限后触发
        主动式提前预防超限
        主动式体验更平滑
      Q4: ArtifactStore 解决什么问题？
        A: 大工具结果写入磁盘
        消息只保留引用 ID
        按需读取，节省内存
      Q5: 为什么用 UTF-8 字节数而非字符数？
        A: 模型按 token 计费
        中文字符占 3 字节
        字节数更接近真实 token 数
      Q6: 压缩时保留哪些消息？
        A: system prompt 必须保留
        最近 N 个 MessageGroup 保留
        旧消息总结成摘要
      Q7: CompactionManager 实现了哪两个接口？
        A: RequestHistoryProcessor
        ToolResultProcessor
        分别在请求前和结果后调用
```
