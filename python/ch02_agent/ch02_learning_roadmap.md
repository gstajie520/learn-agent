# 第 2 章学习导航

```mermaid
mindmap
  root((第 2 章：配置管理与文件系统抽象))
    学习路线（推荐顺序）
      第一步：读测试理解目标
        tests/test_ch02_tools.py
        tests/test_config.py
        看第二章新增了什么能力
        理解 P01 和 P02 的区别
      第二步：读核心抽象接口
        core/profiles.py（章节配置）
        core/commands.py（命令接口）
        core/filesystem.py（文件系统接口）
        理解 Protocol 的作用
      第三步：读适配器实现
        adapters/powershell.py
        adapters/filesystem.py
        理解路径安全检查机制
      第四步：读配置管理
        config.py（配置加载与校验）
        理解一次性校验所有字段的设计
      第五步：读工具组装
        features/builtin_tools.py
        bootstrap.py（依赖注入）
        理解工具如何按章节分层开放
    
    核心文件清单
      core/profiles.py（章节配置）
        ChapterProfile 类
          chapter: 章节编号
          capabilities: 能力白名单（frozenset）
        预定义配置常量
          P01: 第一章（loop, powershell）
          P02: 第二章（增加 tool_registry, files）
        profile_for_chapter()
      core/commands.py（命令接口）
        CommandResult 值对象
          output: 合并的输出文本
          exit_code: 进程退出码
          timed_out: 超时标记
          truncated: 截断标记
        CommandRunner 接口
          run(command, cwd, timeout_ms)
      core/filesystem.py（文件系统接口）
        领域异常定义
          WorkspacePathError（路径逃逸）
          TextNotFoundError（文本未找到）
          InvalidUtf8Error（编码错误）
          FileNotFoundError（文件不存在）
          InvalidFilePathError（类型错误）
          FileSystemOperationError（通用错误）
        WorkspaceFileSystem 接口
          read_file(workspace, path, limit)
          write_file(workspace, path, content)
          edit_file(workspace, path, old, new)
          glob_files(workspace, pattern)
      config.py（配置管理）
        ConfigurationError（配置异常）
        OpenAISettings 值对象
          base_url: API 基础地址
          api_key: 服务密钥
          model: 模型名称
        settings_from_mapping()
        settings_from_env_file()
        settings_from_environment()
        find_env_file()（向上查找）
      adapters/filesystem.py（文件系统实现）
        路径安全函数
          _relative_parts（词法检查）
          _workspace_root（工作区验证）
          safe_path（双重边界检查）
          _is_windows_reserved（Windows 保留名）
        LocalWorkspaceFileSystem 类
          read_file（带行数限制）
          write_file（自动创建目录）
          edit_file（精确替换一次）
          glob_files（稳定排序）
      features/builtin_tools.py（内置工具）
        create_shell_tool（保留第一章）
        create_read_file_tool
        create_write_file_tool
        create_edit_file_tool
        create_glob_tool
        create_chapter_one_tools（P01）
        create_chapter_two_tools（P02）
      bootstrap.py（组合根）
        SYSTEM_PROMPT 常量
        build_agent 工厂函数
          验证章节配置常量（is 比较）
          根据章节选择工具集
          支持测试时注入 Fake 依赖
    
    Java 对照关系
      数据结构对照
        dataclass(frozen=True) = record
        frozenset = Collections.unmodifiableSet
        tuple = List.copyOf()
        Path = java.nio.file.Path
      类型系统对照
        Protocol = interface
        str | None = Optional<String>
        Literal = 枚举或字面量类型
        int | None = Integer（可空）
      语法对照
        value or default = value != null ? value : default
        a is b = a == b（引用相等）
        not value = !value
        value.get(key) = map.get(key)
      异常处理对照
        raise ValueError = throw IllegalArgumentException
        except OSError = catch IOException
        自定义领域异常 = 业务异常体系
    
    设计模式识别
      依赖注入（构造器注入）
        build_agent 接收所有依赖
        支持测试时传入 Fake 实现
        类似 Spring @Autowired
      适配器模式
        CommandRunner 适配 PowerShell
        WorkspaceFileSystem 适配 pathlib
        核心层不依赖具体实现
      策略模式
        根据 ChapterProfile 选择工具集
        P01 vs P02 不同策略
      仓储模式（Repository）
        LocalWorkspaceFileSystem 类似仓储
        隔离文件系统细节
        提供领域友好的接口
      值对象（Value Object）
        CommandResult（不可变）
        OpenAISettings（不可变）
        ChapterProfile（不可变）
      异常映射
        _translate_os_error 转换 OS 异常
        _map_file_error 映射文件系统异常
        统一异常类型便于上层处理
    
    关键概念理解
      第 2 章与第 1 章的区别
        第 1 章：只有 loop 和 shell
        第 2 章：增加配置管理和文件操作
        新增 4 个文件工具：read/write/edit/glob
        引入 Profile 概念控制能力边界
      配置管理的设计原则
        一次性收集所有错误（避免反复启动）
        校验通过后返回强类型对象
        支持 .env 文件和环境变量两种来源
        向上查找 .env 支持多章节共享
      命令执行抽象的意义
        核心层不依赖 subprocess
        返回结构化 CommandResult
        测试时可以替换为 Fake
        统一处理超时和截断
      文件系统抽象的必要性
        防止路径遍历攻击（.. 逃逸）
        防止符号链接绕过安全检查
        拒绝 Windows 保留设备名（CON/NUL）
        统一异常类型便于工具层处理
      双重路径边界检查
        词法检查：_relative_parts 拒绝 .. 和绝对路径
        物理检查：safe_path 解析符号链接后再验证
        防御深度：两层检查都必须通过
        实战案例：symbolic_link 测试
      为什么章节配置用 is 比较
        is 比较对象身份而非字段值
        防止调用方伪造相同内容的 DTO
        只接受预定义的 P01/P02 常量
        类似 Java 的单例常量检查
    
    面试题速查
      Q1: 第 2 章相比第 1 章增加了哪些能力？
        A: 增加了 4 个文件操作工具
        read_file/write_file/edit_file/glob
        引入配置管理和 Profile 概念
        抽象了 CommandRunner 和 FileSystem 接口
      Q2: 什么是双重路径边界检查？为什么需要？
        A: 词法检查拒绝 .. 和绝对路径
        物理检查解析符号链接后再验证
        防止符号链接绕过词法检查逃逸工作区
        这是路径安全的核心防护
      Q3: 配置管理为什么一次性收集所有错误？
        A: 避免用户反复启动才发现所有问题
        一次性列出所有缺失或错误的字段
        提升开发体验和调试效率
        类似 Spring Boot 的配置绑定
      Q4: Protocol 和 ABC 有什么区别？
        A: Protocol 是结构化类型（鸭子类型）
        不需要显式继承，只要方法签名匹配即可
        ABC 是名义类型，必须显式继承
        Protocol 更灵活，适合定义接口契约
      Q5: 为什么 edit_file 只替换第一次匹配？
        A: 避免全文件替换的误操作风险
        精确定位要修改的位置
        找不到旧文本时快速失败不写盘
        类似 IDE 的精确重构操作
      Q6: 为什么 ChapterProfile 用 is 而不是 == 比较？
        A: is 比较对象身份（引用相等）
        防止外部伪造内容相同的配置对象
        只接受预定义的 P01/P02 单例常量
        增强安全性和意图明确性
      Q7: glob_files 为什么要跳过符号链接？
        A: 防止符号链接指向工作区外导致逃逸
        避免循环链接导致无限递归
        保证 glob 结果都在工作区安全边界内
        每个结果路径仍需通过 safe_path 验证
```
