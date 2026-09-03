#!/usr/bin/env python3
"""生成 XMind 8/2020+ 格式的脑图文件。

XMind 文件本质是 zip 压缩包，包含：
- content.json: 脑图节点树
- metadata.json: 元数据
- manifest.json: 文件清单
"""

import json
import zipfile
from pathlib import Path
from datetime import datetime


def create_xmind_node(title: str, children: list = None) -> dict:
    """创建一个 XMind 节点。

    Args:
        title: 节点标题
        children: 子节点列表

    Returns:
        符合 XMind JSON 格式的节点字典
    """
    node = {
        "id": f"node_{abs(hash(title))}",
        "title": title,
        "class": "topic"
    }

    if children:
        node["children"] = {
            "attached": children
        }

    return node


# 构建脑图结构
root_node = create_xmind_node(
    "第 2 章：配置管理与文件系统抽象",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：读测试理解目标",
                    [
                        create_xmind_node("tests/test_ch02_tools.py"),
                        create_xmind_node("tests/test_config.py"),
                        create_xmind_node("看第二章新增了什么能力"),
                        create_xmind_node("理解 P01 和 P02 的区别")
                    ]
                ),
                create_xmind_node(
                    "第二步：读核心抽象接口",
                    [
                        create_xmind_node("core/profiles.py（章节配置）"),
                        create_xmind_node("core/commands.py（命令接口）"),
                        create_xmind_node("core/filesystem.py（文件系统接口）"),
                        create_xmind_node("理解 Protocol 的作用")
                    ]
                ),
                create_xmind_node(
                    "第三步：读适配器实现",
                    [
                        create_xmind_node("adapters/powershell.py"),
                        create_xmind_node("adapters/filesystem.py"),
                        create_xmind_node("理解路径安全检查机制")
                    ]
                ),
                create_xmind_node(
                    "第四步：读配置管理",
                    [
                        create_xmind_node("config.py（配置加载与校验）"),
                        create_xmind_node("理解一次性校验所有字段的设计")
                    ]
                ),
                create_xmind_node(
                    "第五步：读工具组装",
                    [
                        create_xmind_node("features/builtin_tools.py"),
                        create_xmind_node("bootstrap.py（依赖注入）"),
                        create_xmind_node("理解工具如何按章节分层开放")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "core/profiles.py（章节配置）",
                    [
                        create_xmind_node(
                            "ChapterProfile 类",
                            [
                                create_xmind_node("chapter: 章节编号"),
                                create_xmind_node("capabilities: 能力白名单（frozenset）")
                            ]
                        ),
                        create_xmind_node(
                            "预定义配置常量",
                            [
                                create_xmind_node("P01: 第一章（loop, powershell）"),
                                create_xmind_node("P02: 第二章（增加 tool_registry, files）")
                            ]
                        ),
                        create_xmind_node("profile_for_chapter()")
                    ]
                ),
                create_xmind_node(
                    "core/commands.py（命令接口）",
                    [
                        create_xmind_node(
                            "CommandResult 值对象",
                            [
                                create_xmind_node("output: 合并的输出文本"),
                                create_xmind_node("exit_code: 进程退出码"),
                                create_xmind_node("timed_out: 超时标记"),
                                create_xmind_node("truncated: 截断标记")
                            ]
                        ),
                        create_xmind_node(
                            "CommandRunner 接口",
                            [
                                create_xmind_node("run(command, cwd, timeout_ms)")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/filesystem.py（文件系统接口）",
                    [
                        create_xmind_node(
                            "领域异常定义",
                            [
                                create_xmind_node("WorkspacePathError（路径逃逸）"),
                                create_xmind_node("TextNotFoundError（文本未找到）"),
                                create_xmind_node("InvalidUtf8Error（编码错误）"),
                                create_xmind_node("FileNotFoundError（文件不存在）"),
                                create_xmind_node("InvalidFilePathError（类型错误）"),
                                create_xmind_node("FileSystemOperationError（通用错误）")
                            ]
                        ),
                        create_xmind_node(
                            "WorkspaceFileSystem 接口",
                            [
                                create_xmind_node("read_file(workspace, path, limit)"),
                                create_xmind_node("write_file(workspace, path, content)"),
                                create_xmind_node("edit_file(workspace, path, old, new)"),
                                create_xmind_node("glob_files(workspace, pattern)")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "config.py（配置管理）",
                    [
                        create_xmind_node("ConfigurationError（配置异常）"),
                        create_xmind_node(
                            "OpenAISettings 值对象",
                            [
                                create_xmind_node("base_url: API 基础地址"),
                                create_xmind_node("api_key: 服务密钥"),
                                create_xmind_node("model: 模型名称")
                            ]
                        ),
                        create_xmind_node("settings_from_mapping()"),
                        create_xmind_node("settings_from_env_file()"),
                        create_xmind_node("settings_from_environment()"),
                        create_xmind_node("find_env_file()（向上查找）")
                    ]
                ),
                create_xmind_node(
                    "adapters/filesystem.py（文件系统实现）",
                    [
                        create_xmind_node(
                            "路径安全函数",
                            [
                                create_xmind_node("_relative_parts（词法检查）"),
                                create_xmind_node("_workspace_root（工作区验证）"),
                                create_xmind_node("safe_path（双重边界检查）"),
                                create_xmind_node("_is_windows_reserved（Windows 保留名）")
                            ]
                        ),
                        create_xmind_node(
                            "LocalWorkspaceFileSystem 类",
                            [
                                create_xmind_node("read_file（带行数限制）"),
                                create_xmind_node("write_file（自动创建目录）"),
                                create_xmind_node("edit_file（精确替换一次）"),
                                create_xmind_node("glob_files（稳定排序）")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "features/builtin_tools.py（内置工具）",
                    [
                        create_xmind_node("create_shell_tool（保留第一章）"),
                        create_xmind_node("create_read_file_tool"),
                        create_xmind_node("create_write_file_tool"),
                        create_xmind_node("create_edit_file_tool"),
                        create_xmind_node("create_glob_tool"),
                        create_xmind_node("create_chapter_one_tools（P01）"),
                        create_xmind_node("create_chapter_two_tools（P02）")
                    ]
                ),
                create_xmind_node(
                    "bootstrap.py（组合根）",
                    [
                        create_xmind_node("SYSTEM_PROMPT 常量"),
                        create_xmind_node(
                            "build_agent 工厂函数",
                            [
                                create_xmind_node("验证章节配置常量（is 比较）"),
                                create_xmind_node("根据章节选择工具集"),
                                create_xmind_node("支持测试时注入 Fake 依赖")
                            ]
                        )
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "数据结构对照",
                    [
                        create_xmind_node("dataclass(frozen=True) = record"),
                        create_xmind_node("frozenset = Collections.unmodifiableSet"),
                        create_xmind_node("tuple = List.copyOf()"),
                        create_xmind_node("Path = java.nio.file.Path")
                    ]
                ),
                create_xmind_node(
                    "类型系统对照",
                    [
                        create_xmind_node("Protocol = interface"),
                        create_xmind_node("str | None = Optional<String>"),
                        create_xmind_node("Literal = 枚举或字面量类型"),
                        create_xmind_node("int | None = Integer（可空）")
                    ]
                ),
                create_xmind_node(
                    "语法对照",
                    [
                        create_xmind_node("value or default = value != null ? value : default"),
                        create_xmind_node("a is b = a == b（引用相等）"),
                        create_xmind_node("not value = !value"),
                        create_xmind_node("value.get(key) = map.get(key)")
                    ]
                ),
                create_xmind_node(
                    "异常处理对照",
                    [
                        create_xmind_node("raise ValueError = throw IllegalArgumentException"),
                        create_xmind_node("except OSError = catch IOException"),
                        create_xmind_node("自定义领域异常 = 业务异常体系")
                    ]
                )
            ]
        ),

        # 设计模式识别分支
        create_xmind_node(
            "设计模式识别",
            [
                create_xmind_node(
                    "依赖注入（构造器注入）",
                    [
                        create_xmind_node("build_agent 接收所有依赖"),
                        create_xmind_node("支持测试时传入 Fake 实现"),
                        create_xmind_node("类似 Spring @Autowired")
                    ]
                ),
                create_xmind_node(
                    "适配器模式",
                    [
                        create_xmind_node("CommandRunner 适配 PowerShell"),
                        create_xmind_node("WorkspaceFileSystem 适配 pathlib"),
                        create_xmind_node("核心层不依赖具体实现")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("根据 ChapterProfile 选择工具集"),
                        create_xmind_node("P01 vs P02 不同策略")
                    ]
                ),
                create_xmind_node(
                    "仓储模式（Repository）",
                    [
                        create_xmind_node("LocalWorkspaceFileSystem 类似仓储"),
                        create_xmind_node("隔离文件系统细节"),
                        create_xmind_node("提供领域友好的接口")
                    ]
                ),
                create_xmind_node(
                    "值对象（Value Object）",
                    [
                        create_xmind_node("CommandResult（不可变）"),
                        create_xmind_node("OpenAISettings（不可变）"),
                        create_xmind_node("ChapterProfile（不可变）")
                    ]
                ),
                create_xmind_node(
                    "异常映射",
                    [
                        create_xmind_node("_translate_os_error 转换 OS 异常"),
                        create_xmind_node("_map_file_error 映射文件系统异常"),
                        create_xmind_node("统一异常类型便于上层处理")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "第 2 章与第 1 章的区别",
                    [
                        create_xmind_node("第 1 章：只有 loop 和 shell"),
                        create_xmind_node("第 2 章：增加配置管理和文件操作"),
                        create_xmind_node("新增 4 个文件工具：read/write/edit/glob"),
                        create_xmind_node("引入 Profile 概念控制能力边界")
                    ]
                ),
                create_xmind_node(
                    "配置管理的设计原则",
                    [
                        create_xmind_node("一次性收集所有错误（避免反复启动）"),
                        create_xmind_node("校验通过后返回强类型对象"),
                        create_xmind_node("支持 .env 文件和环境变量两种来源"),
                        create_xmind_node("向上查找 .env 支持多章节共享")
                    ]
                ),
                create_xmind_node(
                    "命令执行抽象的意义",
                    [
                        create_xmind_node("核心层不依赖 subprocess"),
                        create_xmind_node("返回结构化 CommandResult"),
                        create_xmind_node("测试时可以替换为 Fake"),
                        create_xmind_node("统一处理超时和截断")
                    ]
                ),
                create_xmind_node(
                    "文件系统抽象的必要性",
                    [
                        create_xmind_node("防止路径遍历攻击（.. 逃逸）"),
                        create_xmind_node("防止符号链接绕过安全检查"),
                        create_xmind_node("拒绝 Windows 保留设备名（CON/NUL）"),
                        create_xmind_node("统一异常类型便于工具层处理")
                    ]
                ),
                create_xmind_node(
                    "双重路径边界检查",
                    [
                        create_xmind_node("词法检查：_relative_parts 拒绝 .. 和绝对路径"),
                        create_xmind_node("物理检查：safe_path 解析符号链接后再验证"),
                        create_xmind_node("防御深度：两层检查都必须通过"),
                        create_xmind_node("实战案例：symbolic_link 测试")
                    ]
                ),
                create_xmind_node(
                    "为什么章节配置用 is 比较",
                    [
                        create_xmind_node("is 比较对象身份而非字段值"),
                        create_xmind_node("防止调用方伪造相同内容的 DTO"),
                        create_xmind_node("只接受预定义的 P01/P02 常量"),
                        create_xmind_node("类似 Java 的单例常量检查")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 第 2 章相比第 1 章增加了哪些能力？",
                    [
                        create_xmind_node("A: 增加了 4 个文件操作工具"),
                        create_xmind_node("read_file/write_file/edit_file/glob"),
                        create_xmind_node("引入配置管理和 Profile 概念"),
                        create_xmind_node("抽象了 CommandRunner 和 FileSystem 接口")
                    ]
                ),
                create_xmind_node(
                    "Q2: 什么是双重路径边界检查？为什么需要？",
                    [
                        create_xmind_node("A: 词法检查拒绝 .. 和绝对路径"),
                        create_xmind_node("物理检查解析符号链接后再验证"),
                        create_xmind_node("防止符号链接绕过词法检查逃逸工作区"),
                        create_xmind_node("这是路径安全的核心防护")
                    ]
                ),
                create_xmind_node(
                    "Q3: 配置管理为什么一次性收集所有错误？",
                    [
                        create_xmind_node("A: 避免用户反复启动才发现所有问题"),
                        create_xmind_node("一次性列出所有缺失或错误的字段"),
                        create_xmind_node("提升开发体验和调试效率"),
                        create_xmind_node("类似 Spring Boot 的配置绑定")
                    ]
                ),
                create_xmind_node(
                    "Q4: Protocol 和 ABC 有什么区别？",
                    [
                        create_xmind_node("A: Protocol 是结构化类型（鸭子类型）"),
                        create_xmind_node("不需要显式继承，只要方法签名匹配即可"),
                        create_xmind_node("ABC 是名义类型，必须显式继承"),
                        create_xmind_node("Protocol 更灵活，适合定义接口契约")
                    ]
                ),
                create_xmind_node(
                    "Q5: 为什么 edit_file 只替换第一次匹配？",
                    [
                        create_xmind_node("A: 避免全文件替换的误操作风险"),
                        create_xmind_node("精确定位要修改的位置"),
                        create_xmind_node("找不到旧文本时快速失败不写盘"),
                        create_xmind_node("类似 IDE 的精确重构操作")
                    ]
                ),
                create_xmind_node(
                    "Q6: 为什么 ChapterProfile 用 is 而不是 == 比较？",
                    [
                        create_xmind_node("A: is 比较对象身份（引用相等）"),
                        create_xmind_node("防止外部伪造内容相同的配置对象"),
                        create_xmind_node("只接受预定义的 P01/P02 单例常量"),
                        create_xmind_node("增强安全性和意图明确性")
                    ]
                ),
                create_xmind_node(
                    "Q7: glob_files 为什么要跳过符号链接？",
                    [
                        create_xmind_node("A: 防止符号链接指向工作区外导致逃逸"),
                        create_xmind_node("避免循环链接导致无限递归"),
                        create_xmind_node("保证 glob 结果都在工作区安全边界内"),
                        create_xmind_node("每个结果路径仍需通过 safe_path 验证")
                    ]
                )
            ]
        )
    ]
)

# 构建完整的 content.json
content = [{
    "id": "sheet_1",
    "class": "sheet",
    "title": "第 2 章学习导航",
    "rootTopic": root_node
}]

# 构建 metadata.json
metadata = {
    "creator": {
        "name": "Agent Learning System",
        "version": "1.0"
    },
    "created": datetime.now().isoformat()
}

# 构建 manifest.json
manifest = {
    "file-entries": {
        "content.json": {},
        "metadata.json": {}
    }
}

# 创建 XMind 文件（ZIP 格式）
output_path = Path(__file__).parent / "ch02_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"XMind 文件已生成: {output_path}")
print(f"文件大小: {output_path.stat().st_size} 字节")
print(f"可直接用 XMind 8/2020/2023 打开")
