#!/usr/bin/env python3
"""生成第五章 XMind 8/2020+ 格式的脑图文件。

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
    "第 5 章：TODO 跟踪与观察器模式",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解工具轮观察器",
                    [
                        create_xmind_node("core/loop.py:ToolRoundObserver"),
                        create_xmind_node("before_model() 临时指导消息"),
                        create_xmind_node("record_tool_round() 记录工具名")
                    ]
                ),
                create_xmind_node(
                    "第二步：读 TODO 追踪器",
                    [
                        create_xmind_node("features/todos.py"),
                        create_xmind_node("TodoTracker 同时是工具和观察器"),
                        create_xmind_node("会话级状态管理")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解防抖提醒",
                    [
                        create_xmind_node("连续 N 轮未更新 TODO"),
                        create_xmind_node("before_model 触发临时提醒"),
                        create_xmind_node("提醒后立即重置计数器")
                    ]
                ),
                create_xmind_node(
                    "第四步：集成测试",
                    [
                        create_xmind_node("tests/test_ch05_integration.py"),
                        create_xmind_node("验证 TODO 提醒机制"),
                        create_xmind_node("验证完整快照提交")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "features/todos.py（TODO 追踪器）",
                    [
                        create_xmind_node(
                            "TodoTracker 类",
                            [
                                create_xmind_node("_todos: 当前任务快照"),
                                create_xmind_node("_non_todo_tool_rounds: 计数器"),
                                create_xmind_node("tool_definition: todo_write 工具"),
                                create_xmind_node("before_model() 临时提醒"),
                                create_xmind_node("record_tool_round() 计数逻辑")
                            ]
                        ),
                        create_xmind_node(
                            "TodoItem 数据类",
                            [
                                create_xmind_node("content: 任务描述"),
                                create_xmind_node("status: 三态枚举")
                            ]
                        ),
                        create_xmind_node(
                            "常量定义",
                            [
                                create_xmind_node("MAX_TODOS = 50"),
                                create_xmind_node("STALE_TOOL_ROUNDS = 3"),
                                create_xmind_node("TODO_STALE_REMINDER")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（观察器集成）",
                    [
                        create_xmind_node("ToolRoundObserver 接口"),
                        create_xmind_node("before_model() → 临时指导"),
                        create_xmind_node("record_tool_round() → 整轮记录"),
                        create_xmind_node("observer_guidance 不进入 history")
                    ]
                ),
                create_xmind_node(
                    "bootstrap.py（组合根）",
                    [
                        create_xmind_node("第 5 章能力检查"),
                        create_xmind_node("创建 TodoTracker"),
                        create_xmind_node("注册 todo_write 工具"),
                        create_xmind_node("作为 tool_round_observer 注入")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "设计模式对照",
                    [
                        create_xmind_node("TodoTracker = 观察者 + 工具"),
                        create_xmind_node("ToolRoundObserver = interface"),
                        create_xmind_node("before_model = 模板方法钩子"),
                        create_xmind_node("record_tool_round = 事件回调")
                    ]
                ),
                create_xmind_node(
                    "状态管理对照",
                    [
                        create_xmind_node("_todos = 会话级私有状态"),
                        create_xmind_node("todos 属性 = getter"),
                        create_xmind_node("_write_todos = handler 修改状态"),
                        create_xmind_node("无持久化 = 会话结束即消失")
                    ]
                ),
                create_xmind_node(
                    "数据结构对照",
                    [
                        create_xmind_node("tuple[TodoItem, ...] = List.copyOf"),
                        create_xmind_node("TodoStatus = 字面量枚举"),
                        create_xmind_node("MAX_TODOS = static final int"),
                        create_xmind_node("_serialize_snapshot = toJson()")
                    ]
                ),
                create_xmind_node(
                    "校验对照",
                    [
                        create_xmind_node("_validate_todo_input = 严格校验"),
                        create_xmind_node("set(value) != {\"todos\"} = 拒绝未知字段"),
                        create_xmind_node("validator 参数 = JSON Schema"),
                        create_xmind_node("prepare 前校验 = Bean Validation")
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
                        create_xmind_node("AgentRunner = 主题"),
                        create_xmind_node("TodoTracker = 观察者"),
                        create_xmind_node("工具轮结束 = 事件通知"),
                        create_xmind_node("before_model = 反向影响")
                    ]
                ),
                create_xmind_node(
                    "单一职责",
                    [
                        create_xmind_node("TodoTracker 只管 TODO 状态"),
                        create_xmind_node("不关心权限、Hook 或模型"),
                        create_xmind_node("AgentRunner 负责调度")
                    ]
                ),
                create_xmind_node(
                    "防抖机制",
                    [
                        create_xmind_node("连续 3 轮未更新才提醒"),
                        create_xmind_node("提醒后立即重置计数"),
                        create_xmind_node("避免每轮都提醒骚扰模型")
                    ]
                ),
                create_xmind_node(
                    "完整快照提交",
                    [
                        create_xmind_node("todo_write 要求提交全部任务"),
                        create_xmind_node("不支持增量修改"),
                        create_xmind_node("降低并发冲突复杂度")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "工具轮观察器",
                    [
                        create_xmind_node("工具轮 = assistant + 所有 tool 结果"),
                        create_xmind_node("整轮结束后才计数"),
                        create_xmind_node("观察器不能看到半轮状态")
                    ]
                ),
                create_xmind_node(
                    "临时指导消息",
                    [
                        create_xmind_node("只拼到本次 ModelRequest"),
                        create_xmind_node("不进入正式 history"),
                        create_xmind_node("下次请求自动消失")
                    ]
                ),
                create_xmind_node(
                    "会话级状态",
                    [
                        create_xmind_node("TODO 只存在于当前会话"),
                        create_xmind_node("AgentRunner 销毁即消失"),
                        create_xmind_node("不持久化到磁盘或数据库")
                    ]
                ),
                create_xmind_node(
                    "为什么是完整快照",
                    [
                        create_xmind_node("避免 CRUD 接口复杂度"),
                        create_xmind_node("模型提交完整 JSON 更简单"),
                        create_xmind_node("无需处理增删改冲突")
                    ]
                ),
                create_xmind_node(
                    "为什么计数按轮",
                    [
                        create_xmind_node("一轮可能调用多个工具"),
                        create_xmind_node("按调用数会误判"),
                        create_xmind_node("整轮统计更稳定")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 观察器模式和 Hook 有什么区别？",
                    [
                        create_xmind_node("A: Hook 可以修改或阻断工具调用"),
                        create_xmind_node("观察器只能被动观察和记录"),
                        create_xmind_node("Hook 在单次调用链路，观察器在整轮结束")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么 before_model 返回的消息不进 history？",
                    [
                        create_xmind_node("A: 临时指导只对下次请求生效"),
                        create_xmind_node("持久化会污染长期历史"),
                        create_xmind_node("防止提醒累积消耗 token")
                    ]
                ),
                create_xmind_node(
                    "Q3: 为什么 TODO 用完整快照而不是增量更新？",
                    [
                        create_xmind_node("A: 避免实现 add/update/delete 三个接口"),
                        create_xmind_node("模型生成完整 JSON 更简单"),
                        create_xmind_node("无需处理并发修改冲突")
                    ]
                ),
                create_xmind_node(
                    "Q4: 为什么计数器按工具轮而不是调用次数？",
                    [
                        create_xmind_node("A: 一轮可能调用多个工具"),
                        create_xmind_node("按次数统计会误判"),
                        create_xmind_node("整轮结束才计数更准确")
                    ]
                ),
                create_xmind_node(
                    "Q5: TodoTracker 的状态在哪里存储？",
                    [
                        create_xmind_node("A: 存在 TodoTracker 实例的私有字段"),
                        create_xmind_node("会话级状态，不持久化"),
                        create_xmind_node("AgentRunner 销毁时自动消失")
                    ]
                ),
                create_xmind_node(
                    "Q6: 防抖机制为什么是 3 轮？",
                    [
                        create_xmind_node("A: 经验值，平衡提醒及时性和骚扰度"),
                        create_xmind_node("太小会频繁提醒干扰模型"),
                        create_xmind_node("太大会导致计划长期过时")
                    ]
                ),
                create_xmind_node(
                    "Q7: observer_guidance 在循环的哪个位置注入？",
                    [
                        create_xmind_node("A: 构建 ModelRequest 时拼到末尾"),
                        create_xmind_node("在 history 之后，不进入 history"),
                        create_xmind_node("下次循环时不再出现")
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
    "title": "第 5 章学习导航",
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
output_path = Path(__file__).parent / "ch05_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"[OK] XMind 文件已生成: {output_path}")
print(f"   文件大小: {output_path.stat().st_size} 字节")
print(f"   可直接用 XMind 8/2020/2023 打开")
