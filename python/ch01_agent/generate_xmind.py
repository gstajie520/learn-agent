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
    "第 1 章：Agent Loop 基础",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：读测试了解目标",
                    [
                        create_xmind_node("tests/test_loop.py"),
                        create_xmind_node("看 Agent 应该做什么"),
                        create_xmind_node("理解成功标准")
                    ]
                ),
                create_xmind_node(
                    "第二步：读核心循环",
                    [
                        create_xmind_node("core/loop.py"),
                        create_xmind_node("AgentRunner.run 方法"),
                        create_xmind_node("理解循环终止条件")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解支撑概念",
                    [
                        create_xmind_node("core/messages.py"),
                        create_xmind_node("core/tools.py"),
                        create_xmind_node("core/model.py")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "core/loop.py（核心循环）",
                    [
                        create_xmind_node(
                            "AgentRunner 类",
                            [
                                create_xmind_node("run 方法（主循环）"),
                                create_xmind_node("消息历史管理"),
                                create_xmind_node("停止条件判断")
                            ]
                        ),
                        create_xmind_node(
                            "异常定义",
                            [
                                create_xmind_node("AgentLimitError"),
                                create_xmind_node("IncompleteModelReplyError")
                            ]
                        ),
                        create_xmind_node(
                            "授权机制",
                            [
                                create_xmind_node("ToolAuthorizer 接口"),
                                create_xmind_node("ToolAuthorizationDecision")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/tools.py（工具系统）",
                    [
                        create_xmind_node("ToolRegistry（工具注册表）"),
                        create_xmind_node("ToolDefinition（工具定义）"),
                        create_xmind_node("PreparedToolCall（已校验调用）"),
                        create_xmind_node("ToolResult（执行结果）"),
                        create_xmind_node("ToolContext（运行环境）")
                    ]
                ),
                create_xmind_node(
                    "core/messages.py（消息类型）",
                    [
                        create_xmind_node("ChatMessage 联合类型"),
                        create_xmind_node("SystemMessage / UserMessage"),
                        create_xmind_node("AssistantMessage / ToolMessage"),
                        create_xmind_node("validate_tool_pairing")
                    ]
                ),
                create_xmind_node(
                    "core/model.py（模型接口）",
                    [
                        create_xmind_node("ModelClient 接口"),
                        create_xmind_node("ModelRequest / ModelReply")
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
                        create_xmind_node("dataclass = record"),
                        create_xmind_node("frozen=True = 不可变 record"),
                        create_xmind_node("tuple = List.copyOf()"),
                        create_xmind_node("list = ArrayList")
                    ]
                ),
                create_xmind_node(
                    "类型系统对照",
                    [
                        create_xmind_node("Protocol = interface"),
                        create_xmind_node("Literal = 字面量类型"),
                        create_xmind_node("A | B = 联合类型"),
                        create_xmind_node("None = null")
                    ]
                ),
                create_xmind_node(
                    "语法对照",
                    [
                        create_xmind_node("match-case = switch"),
                        create_xmind_node("for...in = 增强for"),
                        create_xmind_node("*list = 列表展开"),
                        create_xmind_node("@property = getter")
                    ]
                ),
                create_xmind_node(
                    "异常处理对照",
                    [
                        create_xmind_node("Exception = Exception"),
                        create_xmind_node("自定义异常 = 业务异常"),
                        create_xmind_node("except = catch")
                    ]
                )
            ]
        ),

        # 设计模式识别分支
        create_xmind_node(
            "设计模式识别",
            [
                create_xmind_node(
                    "依赖注入",
                    [
                        create_xmind_node("构造器注入所有依赖"),
                        create_xmind_node("接口隔离原则")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("ModelClient 可替换"),
                        create_xmind_node("ToolAuthorizer 可选注入")
                    ]
                ),
                create_xmind_node(
                    "模板方法",
                    [
                        create_xmind_node("run 方法固定流程"),
                        create_xmind_node("工具授权点可扩展")
                    ]
                ),
                create_xmind_node(
                    "状态管理",
                    [
                        create_xmind_node("不可变消息对象"),
                        create_xmind_node("可变历史列表"),
                        create_xmind_node("快照隔离")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "Agent 循环本质",
                    [
                        create_xmind_node("用户问题 → 模型"),
                        create_xmind_node("模型回复 → 文本或工具调用"),
                        create_xmind_node("工具执行 → 结果回填"),
                        create_xmind_node("继续循环 → 直到模型返回文本")
                    ]
                ),
                create_xmind_node(
                    "为什么需要 max_turns",
                    [
                        create_xmind_node("防止无限循环"),
                        create_xmind_node("控制成本"),
                        create_xmind_node("避免超时")
                    ]
                ),
                create_xmind_node(
                    "工具调用必须配对",
                    [
                        create_xmind_node("OpenAI API 协议要求"),
                        create_xmind_node("每个 tool_call 必须有结果"),
                        create_xmind_node("否则 API 会拒绝请求")
                    ]
                ),
                create_xmind_node(
                    "fail-closed 原则",
                    [
                        create_xmind_node("授权系统故障时默认拒绝"),
                        create_xmind_node("安全优先于可用性")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: Agent Loop 和普通 while 循环有什么区别？",
                    [
                        create_xmind_node("A: 普通循环处理固定数据"),
                        create_xmind_node("Agent Loop 每轮输入来自模型的动态决策"),
                        create_xmind_node("且可能触发外部工具执行")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么需要 max_turns 限制？",
                    [
                        create_xmind_node("A: 防止模型陷入工具调用死循环"),
                        create_xmind_node("避免成本失控和超时"),
                        create_xmind_node("生产环境通常设置 10-20 轮")
                    ]
                ),
                create_xmind_node(
                    "Q3: 什么是 fail-closed 原则？",
                    [
                        create_xmind_node("A: 授权系统故障时默认拒绝"),
                        create_xmind_node("返回 allowed=False"),
                        create_xmind_node("安全优先于可用性")
                    ]
                ),
                create_xmind_node(
                    "Q4: 工具调用为什么必须配对？",
                    [
                        create_xmind_node("A: OpenAI API 协议要求"),
                        create_xmind_node("每个 tool_call 必须有对应的 tool 结果"),
                        create_xmind_node("否则 API 400 拒绝请求")
                    ]
                ),
                create_xmind_node(
                    "Q5: Agent 和 RAG 有什么区别？",
                    [
                        create_xmind_node("A: RAG 是检索后增强生成（单次调用）"),
                        create_xmind_node("Agent 是循环调用工具的编排系统"),
                        create_xmind_node("可以调用 RAG 作为工具之一")
                    ]
                ),
                create_xmind_node(
                    "Q6: 如果模型一直调用工具不返回文本怎么办？",
                    [
                        create_xmind_node("A: 达到 max_turns 后抛 AgentLimitError"),
                        create_xmind_node("上层可以让模型总结当前进度"),
                        create_xmind_node("或提示用户介入")
                    ]
                ),
                create_xmind_node(
                    "Q7: 为什么消息历史用 tuple 不用 list？",
                    [
                        create_xmind_node("A: 对外返回的 history 用 tuple（不可变）"),
                        create_xmind_node("防止调用方修改后影响下次运行"),
                        create_xmind_node("内部用 list 可变列表")
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
    "title": "第 1 章学习导航",
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
output_path = Path(__file__).parent / "ch01_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"✅ XMind 文件已生成: {output_path}")
print(f"   文件大小: {output_path.stat().st_size} 字节")
print(f"   可直接用 XMind 8/2020/2023 打开")
