#!/usr/bin/env python3
"""生成第 7 章学习路线图 XMind 文件。

ch07 核心特性：按需加载 Skill（技能系统）
- 启动时只扫描 frontmatter（name + description）
- 模型调用 load_skill 时才加载完整正文
- 路径安全边界：所有 Skill 必须在 workspace/skills 目录内
"""

import json
import zipfile
from pathlib import Path
from datetime import datetime


def create_xmind_node(title: str, children: list = None) -> dict:
    """创建一个 XMind 节点。"""
    node = {
        "id": f"node_{abs(hash(title))}",
        "title": title,
        "class": "topic"
    }
    if children:
        node["children"] = {"attached": children}
    return node


# 构建脑图结构
root_node = create_xmind_node(
    "第 7 章：按需加载 Skill",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解 Skill 延迟加载设计（15分钟）",
                    [
                        create_xmind_node("agent_ch07/features/skills.py"),
                        create_xmind_node("核心类：SkillRegistry"),
                        create_xmind_node("扫描阶段只读 frontmatter"),
                        create_xmind_node("加载阶段读取完整正文")
                    ]
                ),
                create_xmind_node(
                    "第二步：阅读路径安全边界（10分钟）",
                    [
                        create_xmind_node("_validate_skill_name 名称校验"),
                        create_xmind_node("_resolve_skill_root 目录解析"),
                        create_xmind_node("_checked_real_directory 防逃逸"),
                        create_xmind_node("防止符号链接穿越")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解两级加载流程（15分钟）",
                    [
                        create_xmind_node("SkillRegistry.scan() 扫描元数据"),
                        create_xmind_node("render_catalog() 生成目录"),
                        create_xmind_node("load_skill() 加载正文"),
                        create_xmind_node("_handle_load() 工具处理器")
                    ]
                ),
                create_xmind_node(
                    "第四步：浏览集成测试（10分钟）",
                    [
                        create_xmind_node("tests/test_skills.py"),
                        create_xmind_node("tests/test_ch07_integration.py"),
                        create_xmind_node("理解 Skill 如何被注册和调用")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "agent_ch07/features/skills.py（本章核心）",
                    [
                        create_xmind_node(
                            "SkillRegistry 类",
                            [
                                create_xmind_node("scan() 扫描 Skill 目录"),
                                create_xmind_node("render_catalog() 生成目录"),
                                create_xmind_node("load_skill() 加载正文"),
                                create_xmind_node("tool_definition 工具定义")
                            ]
                        ),
                        create_xmind_node(
                            "路径安全函数",
                            [
                                create_xmind_node("_validate_skill_name"),
                                create_xmind_node("_resolve_skill_root"),
                                create_xmind_node("_checked_real_directory"),
                                create_xmind_node("_checked_real_file")
                            ]
                        ),
                        create_xmind_node(
                            "数据类型",
                            [
                                create_xmind_node("SkillSummary（目录条目）"),
                                create_xmind_node("_SkillRecord（内部记录）")
                            ]
                        ),
                        create_xmind_node(
                            "异常类型",
                            [
                                create_xmind_node("SkillPathError（路径逃逸）"),
                                create_xmind_node("SkillManifestError（manifest错误）"),
                                create_xmind_node("SkillNotFoundError（未找到）"),
                                create_xmind_node("SkillNameError（名称非法）")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "agent_ch07/bootstrap.py（接线）",
                    [
                        create_xmind_node("build_agent 组合根"),
                        create_xmind_node("P07 Profile 包含 skills 能力"),
                        create_xmind_node("注册 load_skill 工具"),
                        create_xmind_node("父子 Agent 都能调用 load_skill")
                    ]
                ),
                create_xmind_node(
                    "继承自前章的能力",
                    [
                        create_xmind_node("core/loop.py（Agent循环）"),
                        create_xmind_node("core/hooks.py（Hook生命周期）"),
                        create_xmind_node("core/permissions.py（权限策略）"),
                        create_xmind_node("features/subagents.py（子Agent）"),
                        create_xmind_node("features/todos.py（TODO追踪）")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "SkillRegistry 类比",
                    [
                        create_xmind_node("类似只读配置注册表"),
                        create_xmind_node("scan() = @PostConstruct 初始化"),
                        create_xmind_node("load_skill() = 延迟加载服务方法"),
                        create_xmind_node("tool_definition = Bean 注册")
                    ]
                ),
                create_xmind_node(
                    "数据结构对照",
                    [
                        create_xmind_node("SkillSummary = DTO record"),
                        create_xmind_node("_SkillRecord = 内部领域对象"),
                        create_xmind_node("frozenset = Collections.unmodifiableSet()"),
                        create_xmind_node("Path.resolve() = Files.realPath()")
                    ]
                ),
                create_xmind_node(
                    "安全校验对照",
                    [
                        create_xmind_node("_validate_skill_name = Bean Validation"),
                        create_xmind_node("_is_inside() = 路径包含判断"),
                        create_xmind_node("realpath 防符号链接 = 防路径穿越"),
                        create_xmind_node("Windows保留名 = 跨平台兼容")
                    ]
                ),
                create_xmind_node(
                    "异常处理对照",
                    [
                        create_xmind_node("SkillError = 业务异常基类"),
                        create_xmind_node("领域错误 -> tool_error()"),
                        create_xmind_node("不向模型暴露堆栈"),
                        create_xmind_node("错误码稳定可解析")
                    ]
                )
            ]
        ),

        # 设计模式识别分支
        create_xmind_node(
            "设计模式识别",
            [
                create_xmind_node(
                    "延迟加载（Lazy Loading）",
                    [
                        create_xmind_node("扫描阶段只读元数据"),
                        create_xmind_node("真正使用时才加载正文"),
                        create_xmind_node("节省启动时 System Prompt 空间"),
                        create_xmind_node("适用于大量可选技能场景")
                    ]
                ),
                create_xmind_node(
                    "工厂方法",
                    [
                        create_xmind_node("SkillRegistry.scan() 类工厂"),
                        create_xmind_node("校验后返回不可变注册表"),
                        create_xmind_node("封装复杂创建逻辑")
                    ]
                ),
                create_xmind_node(
                    "门面模式（Facade）",
                    [
                        create_xmind_node("SkillRegistry 封装路径校验细节"),
                        create_xmind_node("对外提供简单的 load_skill 接口"),
                        create_xmind_node("隐藏 frontmatter 解析复杂度")
                    ]
                ),
                create_xmind_node(
                    "防御式边界",
                    [
                        create_xmind_node("扫描和加载都检查路径安全"),
                        create_xmind_node("拒绝绝对路径和 .. 片段"),
                        create_xmind_node("防止符号链接替换后逃逸"),
                        create_xmind_node("Windows 保留名黑名单")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "为什么需要两级加载",
                    [
                        create_xmind_node("System Prompt 有长度限制"),
                        create_xmind_node("模型可能有几十个可用 Skill"),
                        create_xmind_node("启动时只给名称和一句描述"),
                        create_xmind_node("模型决定需要哪个才加载正文")
                    ]
                ),
                create_xmind_node(
                    "路径安全边界",
                    [
                        create_xmind_node("所有 Skill 必须在 workspace/skills 内"),
                        create_xmind_node("名称只能用小写字母数字和连字符"),
                        create_xmind_node("拒绝 ../、绝对路径、Windows 设备名"),
                        create_xmind_node("扫描和加载都做 realpath 校验")
                    ]
                ),
                create_xmind_node(
                    "frontmatter 元数据",
                    [
                        create_xmind_node("YAML 格式，包裹在 --- 之间"),
                        create_xmind_node("必须字段：name、description"),
                        create_xmind_node("name 必须等于目录名"),
                        create_xmind_node("description 必须是非空单行")
                    ]
                ),
                create_xmind_node(
                    "目录预算控制",
                    [
                        create_xmind_node("最多 100 条（DEFAULT_MAX_CATALOG_ENTRIES）"),
                        create_xmind_node("最多 8000 UTF-8 字节"),
                        create_xmind_node("不截断半条目录行"),
                        create_xmind_node("按名称排序保证稳定")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: ch07 相比 ch06 新增了什么核心能力？",
                    [
                        create_xmind_node("A: 按需加载 Skill（技能系统）"),
                        create_xmind_node("启动时只扫描 frontmatter 元数据"),
                        create_xmind_node("模型调用 load_skill 工具时才加载完整正文"),
                        create_xmind_node("节省 System Prompt 空间，支持大量可选技能")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么 Skill 需要两级加载？",
                    [
                        create_xmind_node("A: System Prompt 长度受限"),
                        create_xmind_node("可能有几十个 Skill，全部加载会超限"),
                        create_xmind_node("启动时只给目录（名称+描述）"),
                        create_xmind_node("模型判断需要哪个才调用 load_skill")
                    ]
                ),
                create_xmind_node(
                    "Q3: Skill 路径安全边界如何保证？",
                    [
                        create_xmind_node("A: 名称只允许 [a-z0-9-]，拒绝 .. 和绝对路径"),
                        create_xmind_node("扫描和加载都检查 realpath 仍在 workspace 内"),
                        create_xmind_node("防止符号链接替换后路径逃逸"),
                        create_xmind_node("拒绝 Windows 设备名（NUL、CON 等）")
                    ]
                ),
                create_xmind_node(
                    "Q4: frontmatter 是什么，包含哪些字段？",
                    [
                        create_xmind_node("A: YAML 格式的 Skill 元数据"),
                        create_xmind_node("包裹在两个 --- 之间"),
                        create_xmind_node("必须包含 name（等于目录名）和 description（单行）"),
                        create_xmind_node("扫描阶段只读这部分，不读取正文")
                    ]
                ),
                create_xmind_node(
                    "Q5: SkillRegistry.scan() 和 load_skill() 的区别？",
                    [
                        create_xmind_node("A: scan() 在启动时执行一次"),
                        create_xmind_node("遍历 skills/ 目录，只读取每个 SKILL.md 的 frontmatter"),
                        create_xmind_node("load_skill() 在模型调用时执行"),
                        create_xmind_node("重新校验路径，读取完整正文并返回")
                    ]
                ),
                create_xmind_node(
                    "Q6: 为什么加载时要重新校验路径？",
                    [
                        create_xmind_node("A: 防止扫描后符号链接被替换"),
                        create_xmind_node("攻击者可能在扫描后修改链接指向"),
                        create_xmind_node("加载时重新 realpath 并判断是否仍在边界内"),
                        create_xmind_node("TOCTOU（Time-of-Check Time-of-Use）防御")
                    ]
                ),
                create_xmind_node(
                    "Q7: 子 Agent 能调用 load_skill 吗？",
                    [
                        create_xmind_node("A: 可以"),
                        create_xmind_node("bootstrap.py 中 child_tools_factory 注册了 load_skill"),
                        create_xmind_node("但子 Agent 仍然没有 task 工具（不能再次委派）"),
                        create_xmind_node("Skill 正文只进入调用它的那条历史")
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
    "title": "第 7 章学习导航",
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
output_path = Path(__file__).parent / "ch07_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"✅ XMind 文件已生成: {output_path}")
print(f"   文件大小: {output_path.stat().st_size} 字节")
print(f"   可直接用 XMind 8/2020/2023 打开")
