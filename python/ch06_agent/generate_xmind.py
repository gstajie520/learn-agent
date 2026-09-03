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
    "第 6 章：子 Agent + TODO 跟踪器",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解 TODO 跟踪器",
                    [
                        create_xmind_node("features/todos.py"),
                        create_xmind_node("TodoTracker 如何记录计划快照"),
                        create_xmind_node("_check_stale_plan 检测过期计划")
                    ]
                ),
                create_xmind_node(
                    "第二步：理解子 Agent 机制",
                    [
                        create_xmind_node("features/subagents.py"),
                        create_xmind_node("SubagentTool 委派任务"),
                        create_xmind_node("父子 Agent 的隔离与共享")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解循环集成点",
                    [
                        create_xmind_node("core/loop.py"),
                        create_xmind_node("ToolRoundObserver 观察器协议"),
                        create_xmind_node("Hook 集成的 TODO 提醒")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "features/todos.py（TODO 跟踪器）",
                    [
                        create_xmind_node(
                            "TodoTracker 类",
                            [
                                create_xmind_node("observe_tool_round（记录工具轮次）"),
                                create_xmind_node("_check_stale_plan（检测过期计划）"),
                                create_xmind_node("_install_hooks（安装 Hook）")
                            ]
                        ),
                        create_xmind_node(
                            "TODO 工具实现",
                            [
                                create_xmind_node("todo_read_tool（读取计划）"),
                                create_xmind_node("todo_write_tool（更新计划）"),
                                create_xmind_node("todo_archive_tool（归档计划）")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "features/subagents.py（子 Agent）",
                    [
                        create_xmind_node(
                            "SubagentTool 类",
                            [
                                create_xmind_node("task 工具定义"),
                                create_xmind_node("创建隔离的 AgentRunner"),
                                create_xmind_node("父子共享 Hook 和权限")
                            ]
                        ),
                        create_xmind_node(
                            "工厂接口",
                            [
                                create_xmind_node("ModelClientFactory"),
                                create_xmind_node("ToolRegistryFactory")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（循环扩展）",
                    [
                        create_xmind_node("ToolRoundObserver 协议"),
                        create_xmind_node("observe_tool_round 回调点"),
                        create_xmind_node("max_turns 检查前通知观察器")
                    ]
                ),
                create_xmind_node(
                    "bootstrap.py（组合根）",
                    [
                        create_xmind_node("P06 Profile"),
                        create_xmind_node("组装 todo + subagent 能力"),
                        create_xmind_node("子 Agent 模型工厂配置")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "子 Agent 对照",
                    [
                        create_xmind_node("SubagentTool = @Service 委派服务"),
                        create_xmind_node("父子隔离 = 创建新的 Service 实例"),
                        create_xmind_node("共享 Hook = 依赖注入相同的监听器")
                    ]
                ),
                create_xmind_node(
                    "观察器对照",
                    [
                        create_xmind_node("ToolRoundObserver = 观察者接口"),
                        create_xmind_node("observe_tool_round = @EventListener"),
                        create_xmind_node("可选观察器 = Optional<Observer>")
                    ]
                ),
                create_xmind_node(
                    "工厂对照",
                    [
                        create_xmind_node("ModelClientFactory = Supplier<ModelClient>"),
                        create_xmind_node("ToolRegistryFactory = Supplier<Registry>"),
                        create_xmind_node("返回 tuple = 返回配对对象")
                    ]
                ),
                create_xmind_node(
                    "状态管理对照",
                    [
                        create_xmind_node("_snapshot = 快照对象"),
                        create_xmind_node("_rounds_since_write = 计数器"),
                        create_xmind_node("_check_stale_plan = 定时检查逻辑")
                    ]
                )
            ]
        ),

        # 设计模式识别分支
        create_xmind_node(
            "设计模式识别",
            [
                create_xmind_node(
                    "观察者模式",
                    [
                        create_xmind_node("ToolRoundObserver 协议"),
                        create_xmind_node("循环通知观察器"),
                        create_xmind_node("解耦循环与跟踪逻辑")
                    ]
                ),
                create_xmind_node(
                    "工厂模式",
                    [
                        create_xmind_node("ModelClientFactory"),
                        create_xmind_node("ToolRegistryFactory"),
                        create_xmind_node("每次创建独立实例")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("Hook 定制 TODO 提醒"),
                        create_xmind_node("可选观察器注入"),
                        create_xmind_node("灵活的扩展点")
                    ]
                ),
                create_xmind_node(
                    "模板方法",
                    [
                        create_xmind_node("子 Agent 复用循环结构"),
                        create_xmind_node("固定的 system_prompt"),
                        create_xmind_node("独立的 max_turns")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "TODO 快照机制",
                    [
                        create_xmind_node("todo_write 记录快照"),
                        create_xmind_node("每轮检查是否过期"),
                        create_xmind_node("3 轮未更新触发提醒")
                    ]
                ),
                create_xmind_node(
                    "父子 Agent 隔离",
                    [
                        create_xmind_node("独立的消息历史"),
                        create_xmind_node("独立的工具注册表"),
                        create_xmind_node("独立的 TODO 跟踪器")
                    ]
                ),
                create_xmind_node(
                    "父子 Agent 共享",
                    [
                        create_xmind_node("共享 HookRegistry"),
                        create_xmind_node("共享 PermissionPolicy"),
                        create_xmind_node("共享工作区和身份")
                    ]
                ),
                create_xmind_node(
                    "观察器协议优势",
                    [
                        create_xmind_node("核心循环不感知 TODO 细节"),
                        create_xmind_node("可选注入灵活扩展"),
                        create_xmind_node("符合开闭原则")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 什么是 TODO 跟踪器的快照机制？",
                    [
                        create_xmind_node("A: 模型调用 todo_write 时记录计划快照"),
                        create_xmind_node("每轮工具执行后检查是否 3 轮未更新"),
                        create_xmind_node("过期时通过 Hook 注入提醒消息")
                    ]
                ),
                create_xmind_node(
                    "Q2: 父子 Agent 如何做到隔离和共享？",
                    [
                        create_xmind_node("A: 隔离：独立的历史、工具表、TODO 跟踪器"),
                        create_xmind_node("共享：Hook、权限策略、工作区、身份"),
                        create_xmind_node("通过工厂模式创建独立实例")
                    ]
                ),
                create_xmind_node(
                    "Q3: ToolRoundObserver 协议的作用是什么？",
                    [
                        create_xmind_node("A: 定义观察器接口，在每轮工具执行后回调"),
                        create_xmind_node("核心循环通过协议通知观察器"),
                        create_xmind_node("TodoTracker 实现该协议检测过期计划")
                    ]
                ),
                create_xmind_node(
                    "Q4: 子 Agent 为什么不能再委派子 Agent？",
                    [
                        create_xmind_node("A: system_prompt 明确禁止再次委派"),
                        create_xmind_node("避免委派层级过深"),
                        create_xmind_node("保持任务边界清晰")
                    ]
                ),
                create_xmind_node(
                    "Q5: 为什么 TODO 工具需要三个操作？",
                    [
                        create_xmind_node("A: read 查看当前计划"),
                        create_xmind_node("write 更新计划并记录快照"),
                        create_xmind_node("archive 完成后清空状态")
                    ]
                ),
                create_xmind_node(
                    "Q6: 子 Agent 的 max_turns 如何设置？",
                    [
                        create_xmind_node("A: 默认 30 轮（父 Agent 通常 20 轮）"),
                        create_xmind_node("子任务通常需要更多步骤"),
                        create_xmind_node("测试可调低，生产不能调高")
                    ]
                ),
                create_xmind_node(
                    "Q7: 如何测试 TODO 过期检测逻辑？",
                    [
                        create_xmind_node("A: 模拟 todo_write 记录快照"),
                        create_xmind_node("连续 3 次 observe_tool_round 不再 write"),
                        create_xmind_node("第 4 轮触发 Hook 提醒")
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
    "title": "第 6 章学习导航",
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
output_path = Path(__file__).parent / "ch06_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"XMind file generated: {output_path}")
print(f"File size: {output_path.stat().st_size} bytes")
print(f"Can be opened with XMind 8/2020/2023")
