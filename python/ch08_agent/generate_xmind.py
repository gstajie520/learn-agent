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
    "第 8 章：上下文压缩 Compaction",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解压缩动机",
                    [
                        create_xmind_node("为什么需要压缩？"),
                        create_xmind_node("对话历史达到 token 上限"),
                        create_xmind_node("大工具结果占用过多上下文"),
                        create_xmind_node("模型调用成本和延迟")
                    ]
                ),
                create_xmind_node(
                    "第二步：读核心文件",
                    [
                        create_xmind_node("features/compaction.py"),
                        create_xmind_node("CompactionManager 类"),
                        create_xmind_node("MessageGroup 概念"),
                        create_xmind_node("ArtifactStore 归档机制")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解压缩策略",
                    [
                        create_xmind_node("响应式压缩（超限时触发）"),
                        create_xmind_node("主动式压缩（预防超限）"),
                        create_xmind_node("保留最近消息组"),
                        create_xmind_node("总结旧消息")
                    ]
                ),
                create_xmind_node(
                    "第四步：读测试验证",
                    [
                        create_xmind_node("tests/test_compaction.py"),
                        create_xmind_node("tests/test_ch08_integration.py"),
                        create_xmind_node("理解压缩前后对比")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "features/compaction.py（核心实现）",
                    [
                        create_xmind_node(
                            "CompactionManager 类",
                            [
                                create_xmind_node("prepare() - 历史处理器"),
                                create_xmind_node("compact_tool_results() - 结果处理器"),
                                create_xmind_node("两个 Protocol 接口的实现")
                            ]
                        ),
                        create_xmind_node(
                            "MessageGroup 概念",
                            [
                                create_xmind_node("assistant + tool_calls 配对"),
                                create_xmind_node("不可拆分的原子单元"),
                                create_xmind_node("保证消息协议完整性")
                            ]
                        ),
                        create_xmind_node(
                            "ArtifactStore 归档",
                            [
                                create_xmind_node("大结果写入磁盘"),
                                create_xmind_node("消息保留引用 ID"),
                                create_xmind_node("按需读取")
                            ]
                        ),
                        create_xmind_node(
                            "ModelHistorySummarizer",
                            [
                                create_xmind_node("调用模型总结旧消息"),
                                create_xmind_node("生成压缩摘要"),
                                create_xmind_node("减少上下文占用")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（集成点）",
                    [
                        create_xmind_node("history_processor 参数"),
                        create_xmind_node("tool_result_processor 参数"),
                        create_xmind_node("在请求前调用 prepare()"),
                        create_xmind_node("在结果回填前调用 compact_tool_results()")
                    ]
                ),
                create_xmind_node(
                    "bootstrap.py（组装）",
                    [
                        create_xmind_node("P08 Profile 启用 compaction"),
                        create_xmind_node("传入 CompactionManager"),
                        create_xmind_node("注入到 AgentRunner")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "架构对照",
                    [
                        create_xmind_node("CompactionManager = Service"),
                        create_xmind_node("MessageGroup = 不可变 DTO"),
                        create_xmind_node("ArtifactStore = FileRepository"),
                        create_xmind_node("Protocol 接口 = interface")
                    ]
                ),
                create_xmind_node(
                    "处理器模式",
                    [
                        create_xmind_node("RequestHistoryProcessor = 请求拦截器"),
                        create_xmind_node("ToolResultProcessor = 响应拦截器"),
                        create_xmind_node("类似 Servlet Filter 链")
                    ]
                ),
                create_xmind_node(
                    "数据结构",
                    [
                        create_xmind_node("tuple = List.copyOf()"),
                        create_xmind_node("dataclass(frozen=True) = record"),
                        create_xmind_node("bytes 计算 = UTF-8 编码")
                    ]
                ),
                create_xmind_node(
                    "文件操作",
                    [
                        create_xmind_node("Path = java.nio.file.Path"),
                        create_xmind_node("write_text() = Files.writeString()"),
                        create_xmind_node("read_text() = Files.readString()")
                    ]
                )
            ]
        ),

        # 设计模式识别分支
        create_xmind_node(
            "设计模式识别",
            [
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("可选注入 CompactionManager"),
                        create_xmind_node("可替换压缩策略"),
                        create_xmind_node("测试时可用假实现")
                    ]
                ),
                create_xmind_node(
                    "适配器模式",
                    [
                        create_xmind_node("实现 Protocol 接口"),
                        create_xmind_node("适配到 AgentRunner"),
                        create_xmind_node("解耦核心循环和压缩逻辑")
                    ]
                ),
                create_xmind_node(
                    "模板方法",
                    [
                        create_xmind_node("固定调用时机"),
                        create_xmind_node("请求前 prepare()"),
                        create_xmind_node("结果后 compact_tool_results()")
                    ]
                ),
                create_xmind_node(
                    "组合模式",
                    [
                        create_xmind_node("MessageGroup 递归结构"),
                        create_xmind_node("可以嵌套分组"),
                        create_xmind_node("统一处理单个和批量")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "为什么需要压缩",
                    [
                        create_xmind_node("模型上下文窗口有限"),
                        create_xmind_node("长对话历史超出限制"),
                        create_xmind_node("大工具结果占用过多"),
                        create_xmind_node("成本和延迟问题")
                    ]
                ),
                create_xmind_node(
                    "MessageGroup 为什么不可拆分",
                    [
                        create_xmind_node("OpenAI API 协议要求"),
                        create_xmind_node("tool_call 必须有配对结果"),
                        create_xmind_node("拆分会导致 API 拒绝"),
                        create_xmind_node("保证消息完整性")
                    ]
                ),
                create_xmind_node(
                    "响应式 vs 主动式压缩",
                    [
                        create_xmind_node("响应式：超限后压缩"),
                        create_xmind_node("主动式：预防超限"),
                        create_xmind_node("主动式更平滑"),
                        create_xmind_node("避免紧急压缩")
                    ]
                ),
                create_xmind_node(
                    "为什么用字节数不用字符数",
                    [
                        create_xmind_node("模型计费按 token"),
                        create_xmind_node("中文字符占多字节"),
                        create_xmind_node("UTF-8 编码更准确"),
                        create_xmind_node("避免低估上下文")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 为什么需要上下文压缩？",
                    [
                        create_xmind_node("A: 模型上下文窗口有限"),
                        create_xmind_node("长对话历史超出限制"),
                        create_xmind_node("减少成本和延迟")
                    ]
                ),
                create_xmind_node(
                    "Q2: MessageGroup 为什么不能拆分？",
                    [
                        create_xmind_node("A: OpenAI API 协议要求"),
                        create_xmind_node("每个 tool_call 必须有配对结果"),
                        create_xmind_node("拆分会导致 400 错误")
                    ]
                ),
                create_xmind_node(
                    "Q3: 响应式和主动式压缩有什么区别？",
                    [
                        create_xmind_node("A: 响应式在超限后触发"),
                        create_xmind_node("主动式提前预防超限"),
                        create_xmind_node("主动式体验更平滑")
                    ]
                ),
                create_xmind_node(
                    "Q4: ArtifactStore 解决什么问题？",
                    [
                        create_xmind_node("A: 大工具结果写入磁盘"),
                        create_xmind_node("消息只保留引用 ID"),
                        create_xmind_node("按需读取，节省内存")
                    ]
                ),
                create_xmind_node(
                    "Q5: 为什么用 UTF-8 字节数而非字符数？",
                    [
                        create_xmind_node("A: 模型按 token 计费"),
                        create_xmind_node("中文字符占 3 字节"),
                        create_xmind_node("字节数更接近真实 token 数")
                    ]
                ),
                create_xmind_node(
                    "Q6: 压缩时保留哪些消息？",
                    [
                        create_xmind_node("A: system prompt 必须保留"),
                        create_xmind_node("最近 N 个 MessageGroup 保留"),
                        create_xmind_node("旧消息总结成摘要")
                    ]
                ),
                create_xmind_node(
                    "Q7: CompactionManager 实现了哪两个接口？",
                    [
                        create_xmind_node("A: RequestHistoryProcessor"),
                        create_xmind_node("ToolResultProcessor"),
                        create_xmind_node("分别在请求前和结果后调用")
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
    "title": "第 8 章学习导航",
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
output_path = Path(__file__).parent / "ch08_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"✅ XMind 文件已生成: {output_path}")
print(f"   文件大小: {output_path.stat().st_size} 字节")
print(f"   可直接用 XMind 8/2020/2023 打开")
