#!/usr/bin/env python3
"""生成第 14 章 XMind 8/2020+ 格式的脑图文件。

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
    "第 14 章：Hook 生命周期与后台事件",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解 Hook 系统设计",
                    [
                        create_xmind_node("core/hooks.py（核心机制）"),
                        create_xmind_node("HookRegistry 注册和执行"),
                        create_xmind_node("HookContext/HookResult 数据流")
                    ]
                ),
                create_xmind_node(
                    "第二步：理解后台事件系统",
                    [
                        create_xmind_node("core/events.py（事件队列）"),
                        create_xmind_node("RuntimeEvent 接口"),
                        create_xmind_node("EventInbox 线程安全机制")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解权限系统集成",
                    [
                        create_xmind_node("core/permissions.py（策略引擎）"),
                        create_xmind_node("PermissionPolicy 决策流程"),
                        create_xmind_node("Hook 影响权限行为")
                    ]
                ),
                create_xmind_node(
                    "第四步：理解 Agent Loop 集成",
                    [
                        create_xmind_node("core/loop.py（完整循环）"),
                        create_xmind_node("Hook 四个触发点"),
                        create_xmind_node("后台事件注入时机")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "core/hooks.py（Hook 系统）",
                    [
                        create_xmind_node(
                            "HookRegistry 类",
                            [
                                create_xmind_node("register() 注册回调"),
                                create_xmind_node("run() 执行回调链"),
                                create_xmind_node("_normalize_input() 规范化修改"),
                                create_xmind_node("_merge_results() 合并结果")
                            ]
                        ),
                        create_xmind_node(
                            "HookContext 数据类",
                            [
                                create_xmind_node("event 字段（事件类型）"),
                                create_xmind_node("message/prepared/result 字段"),
                                create_xmind_node("__post_init__ 字段归属校验")
                            ]
                        ),
                        create_xmind_node(
                            "HookResult 数据类",
                            [
                                create_xmind_node("permission_behavior 影响权限"),
                                create_xmind_node("updated_input/output 改写数据"),
                                create_xmind_node("blocking_error 阻断执行"),
                                create_xmind_node("force_continue 强制继续"),
                                create_xmind_node("validate_for() 分组校验")
                            ]
                        ),
                        create_xmind_node(
                            "四种生命周期事件",
                            [
                                create_xmind_node("UserPromptSubmit（用户提交）"),
                                create_xmind_node("PreToolUse（工具执行前）"),
                                create_xmind_node("PostToolUse（工具执行后）"),
                                create_xmind_node("Stop（循环停止时）")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/events.py（后台事件）",
                    [
                        create_xmind_node(
                            "RuntimeEvent 接口",
                            [
                                create_xmind_node("event_id（唯一标识）"),
                                create_xmind_node("context_identity（上下文）"),
                                create_xmind_node("idempotency_key（幂等键）"),
                                create_xmind_node("to_payload() 序列化")
                            ]
                        ),
                        create_xmind_node(
                            "EventInbox 类",
                            [
                                create_xmind_node("publish() 发布事件"),
                                create_xmind_node("drain() 非阻塞取出"),
                                create_xmind_node("wait() 阻塞等待"),
                                create_xmind_node("Condition 线程安全")
                            ]
                        ),
                        create_xmind_node(
                            "runtime_event_message()",
                            [
                                create_xmind_node("包装成 user 消息"),
                                create_xmind_node("不伪装成 tool result"),
                                create_xmind_node("支持批处理")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/permissions.py（权限系统）",
                    [
                        create_xmind_node(
                            "PermissionPolicy 类",
                            [
                                create_xmind_node("decide() 决策入口"),
                                create_xmind_node("规则优先级匹配"),
                                create_xmind_node("支持通配符")
                            ]
                        ),
                        create_xmind_node(
                            "PermissionBehavior",
                            [
                                create_xmind_node("passthrough（透传）"),
                                create_xmind_node("allow（允许）"),
                                create_xmind_node("ask（询问用户）"),
                                create_xmind_node("deny（拒绝）")
                            ]
                        ),
                        create_xmind_node("PermissionRequest/Decision")
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（完整循环）",
                    [
                        create_xmind_node(
                            "AgentRunner 类",
                            [
                                create_xmind_node("run() 主循环"),
                                create_xmind_node("_execute_tool_chain() 工具链"),
                                create_xmind_node("集成 HookRegistry"),
                                create_xmind_node("集成 PermissionPolicy"),
                                create_xmind_node("集成 RuntimeEventPump")
                            ]
                        ),
                        create_xmind_node(
                            "生命周期协议",
                            [
                                create_xmind_node("ToolRoundObserver"),
                                create_xmind_node("RequestHistoryProcessor"),
                                create_xmind_node("ToolResultProcessor"),
                                create_xmind_node("TurnLifecycle"),
                                create_xmind_node("SystemPromptProvider")
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
                    "设计模式对照",
                    [
                        create_xmind_node("HookRegistry = 观察者模式 + 责任链"),
                        create_xmind_node("EventInbox = BlockingQueue<Event>"),
                        create_xmind_node("RuntimeEvent = Event 接口"),
                        create_xmind_node("PermissionPolicy = 策略模式")
                    ]
                ),
                create_xmind_node(
                    "并发机制对照",
                    [
                        create_xmind_node("threading.Condition = ReentrantLock + Condition"),
                        create_xmind_node("deque = ArrayDeque"),
                        create_xmind_node("with lock = synchronized 或 try-finally"),
                        create_xmind_node("notify_all() = notifyAll()")
                    ]
                ),
                create_xmind_node(
                    "类型系统对照",
                    [
                        create_xmind_node("Protocol = interface"),
                        create_xmind_node("Literal = 枚举常量"),
                        create_xmind_node("Awaitable = CompletableFuture"),
                        create_xmind_node("Callable = Function/Consumer")
                    ]
                ),
                create_xmind_node(
                    "数据结构对照",
                    [
                        create_xmind_node("frozen dataclass = record"),
                        create_xmind_node("tuple = List.copyOf()"),
                        create_xmind_node("__post_init__ = 构造后校验"),
                        create_xmind_node("object.__setattr__ = 反射修改")
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
                        create_xmind_node("HookRegistry 管理观察者"),
                        create_xmind_node("四种事件类型"),
                        create_xmind_node("回调函数作为观察者")
                    ]
                ),
                create_xmind_node(
                    "责任链模式",
                    [
                        create_xmind_node("回调链串行执行"),
                        create_xmind_node("上下文传递改写"),
                        create_xmind_node("提前终止机制")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("PermissionPolicy 可插拔"),
                        create_xmind_node("四种权限行为"),
                        create_xmind_node("Hook 可影响策略")
                    ]
                ),
                create_xmind_node(
                    "命令模式",
                    [
                        create_xmind_node("HookResult 作为命令对象"),
                        create_xmind_node("声明式影响循环"),
                        create_xmind_node("不直接修改状态")
                    ]
                ),
                create_xmind_node(
                    "生产者-消费者模式",
                    [
                        create_xmind_node("EventInbox 作为缓冲区"),
                        create_xmind_node("后台线程生产事件"),
                        create_xmind_node("主循环消费事件")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "Hook 系统的本质",
                    [
                        create_xmind_node("不修改核心循环代码"),
                        create_xmind_node("在固定节点触发回调"),
                        create_xmind_node("通过声明式结果影响循环"),
                        create_xmind_node("避免 if/else 堆积")
                    ]
                ),
                create_xmind_node(
                    "字段归属校验",
                    [
                        create_xmind_node("PreToolUse 只能改输入"),
                        create_xmind_node("PostToolUse 只能改输出"),
                        create_xmind_node("Stop 只能强制继续"),
                        create_xmind_node("防止误用字段")
                    ]
                ),
                create_xmind_node(
                    "回调链合并规则",
                    [
                        create_xmind_node("additional_context 累加"),
                        create_xmind_node("改写字段后者覆盖"),
                        create_xmind_node("权限取最严格"),
                        create_xmind_node("阻断和继续后者优先")
                    ]
                ),
                create_xmind_node(
                    "后台事件注入",
                    [
                        create_xmind_node("包装成 user 消息"),
                        create_xmind_node("不伪装成 tool result"),
                        create_xmind_node("保持消息配对契约"),
                        create_xmind_node("线程安全队列")
                    ]
                ),
                create_xmind_node(
                    "防御性复制",
                    [
                        create_xmind_node("HookResult 复制所有对象字段"),
                        create_xmind_node("防止引用泄漏"),
                        create_xmind_node("保证不可变性"),
                        create_xmind_node("类似 Java 的 clone()")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: Hook 系统和直接修改循环代码有什么区别？",
                    [
                        create_xmind_node("A: 直接修改会让核心循环堆积 if/else"),
                        create_xmind_node("Hook 系统通过固定节点触发回调"),
                        create_xmind_node("扩展逻辑按契约声明影响而不是直接修改状态"),
                        create_xmind_node("类似观察者模式，核心循环不依赖具体扩展")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么 HookContext 要校验字段归属？",
                    [
                        create_xmind_node("A: 不同事件阶段只应看到对应数据"),
                        create_xmind_node("PreToolUse 不应访问 result"),
                        create_xmind_node("防止 Hook 读取错误阶段的字段"),
                        create_xmind_node("类似 Java Bean Validation 的分组校验")
                    ]
                ),
                create_xmind_node(
                    "Q3: 为什么 HookResult 要防御性复制？",
                    [
                        create_xmind_node("A: 防止 Hook 持有内部状态的引用"),
                        create_xmind_node("外部修改对象会破坏循环的不可变性"),
                        create_xmind_node("复制后 Hook 无法影响已返回的对象"),
                        create_xmind_node("类似 Java 的 Defensive Copy 模式")
                    ]
                ),
                create_xmind_node(
                    "Q4: 为什么后台事件要包装成 user 消息？",
                    [
                        create_xmind_node("A: Agent 循环只接受标准消息类型"),
                        create_xmind_node("伪装成 tool result 会破坏配对契约"),
                        create_xmind_node("user 消息是明确的外部输入"),
                        create_xmind_node("保持消息历史的完整性和可审计性")
                    ]
                ),
                create_xmind_node(
                    "Q5: 回调链如何处理冲突？",
                    [
                        create_xmind_node("A: 合并规则解决冲突"),
                        create_xmind_node("additional_context 累加（都保留）"),
                        create_xmind_node("改写字段后者覆盖（最后修改生效）"),
                        create_xmind_node("权限取最严格（deny > ask > allow）")
                    ]
                ),
                create_xmind_node(
                    "Q6: EventInbox 如何保证线程安全？",
                    [
                        create_xmind_node("A: 使用 threading.Condition 保护队列"),
                        create_xmind_node("类似 Java 的 ReentrantLock + Condition"),
                        create_xmind_node("publish 时 notify_all 唤醒等待线程"),
                        create_xmind_node("drain 和 wait 都在锁内操作")
                    ]
                ),
                create_xmind_node(
                    "Q7: Hook 系统支持异步回调吗？",
                    [
                        create_xmind_node("A: 支持，回调可返回 Awaitable[HookResult]"),
                        create_xmind_node("HookRegistry.run() 是 async 方法"),
                        create_xmind_node("inspect.isawaitable() 检测并 await"),
                        create_xmind_node("类似 Java 的 CompletableFuture")
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
    "title": "第 14 章学习导航",
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
output_path = Path(__file__).parent / "ch14_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"[OK] XMind file generated: {output_path}")
print(f"   Size: {output_path.stat().st_size} bytes")
print(f"   Compatible with XMind 8/2020/2023")
