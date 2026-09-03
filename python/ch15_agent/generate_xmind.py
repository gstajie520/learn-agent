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
    "第 15 章：持久队友与 Mailbox 通信",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解 Mailbox 领域模型",
                    [
                        create_xmind_node("features/mailbox.py"),
                        create_xmind_node("看 MailboxMessage 6 个字段"),
                        create_xmind_node("理解四态状态机：ready/processing/done/quarantine"),
                        create_xmind_node("message.id 同时是事件 ID 和幂等键")
                    ]
                ),
                create_xmind_node(
                    "第二步：原子持久化与状态迁移",
                    [
                        create_xmind_node("adapters/mailbox_json.py"),
                        create_xmind_node("临时文件 + fsync + atomic rename"),
                        create_xmind_node("目录名即状态，rename 即状态迁移"),
                        create_xmind_node("processing 状态即租约")
                    ]
                ),
                create_xmind_node(
                    "第三步：队友生命周期管理",
                    [
                        create_xmind_node("features/teammates.py"),
                        create_xmind_node("每个队友独立 AgentRunner + 独立历史"),
                        create_xmind_node("spawn → running → idle → running (复用)"),
                        create_xmind_node("工作循环：claim → run → send result → ack")
                    ]
                ),
                create_xmind_node(
                    "第四步：事件回合与 ack-after-processing",
                    [
                        create_xmind_node("core/loop.py 的 run_events()"),
                        create_xmind_node("事件回合完成后才 ack"),
                        create_xmind_node("ack 失败保存到 _pending_event_acks"),
                        create_xmind_node("下次只补确认不重复调用模型")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "features/mailbox.py（领域模型）",
                    [
                        create_xmind_node(
                            "MailboxMessage（不可变消息）",
                            [
                                create_xmind_node("id, sender, recipient"),
                                create_xmind_node("kind, content, created_at_utc"),
                                create_xmind_node("属性：event_id, context_identity, idempotency_key")
                            ]
                        ),
                        create_xmind_node(
                            "MailboxStore Protocol（Repository 接口）",
                            [
                                create_xmind_node("send() - 原子写入 ready"),
                                create_xmind_node("claim() - 原子迁移 ready → processing"),
                                create_xmind_node("ack() - 原子迁移 processing → done"),
                                create_xmind_node("release() - 重试回 ready"),
                                create_xmind_node("quarantine() - 隔离坏消息"),
                                create_xmind_node("recover_processing() - 恢复遗留租约")
                            ]
                        ),
                        create_xmind_node(
                            "工具函数",
                            [
                                create_xmind_node("canonical_agent_name() - 安全 slug 校验"),
                                create_xmind_node("canonical_message_id() - UUID 格式校验"),
                                create_xmind_node("messages_equal() - 完整快照比较")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "adapters/mailbox_json.py（Repository 实现）",
                    [
                        create_xmind_node(
                            "FileMailboxStore 核心方法",
                            [
                                create_xmind_node("_atomic_write() - 临时文件 + fsync + rename"),
                                create_xmind_node("_move() - 原子状态迁移"),
                                create_xmind_node("_load() - 读取并校验 JSON"),
                                create_xmind_node("_valid_entries() - 自动隔离坏文件")
                            ]
                        ),
                        create_xmind_node(
                            "目录结构",
                            [
                                create_xmind_node(".agent_tutorial/mailboxes/"),
                                create_xmind_node("{recipient}/ready/*.json"),
                                create_xmind_node("{recipient}/processing/*.json"),
                                create_xmind_node("{recipient}/done/*.json"),
                                create_xmind_node("{recipient}/quarantine/*.json")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "features/teammates.py（运行时管理）",
                    [
                        create_xmind_node(
                            "TeammateRuntime 类",
                            [
                                create_xmind_node("spawn() - 注册队友 + 启动 worker"),
                                create_xmind_node("send() - 发消息 + 唤醒 idle 队友"),
                                create_xmind_node("state() - 查询队友状态"),
                                create_xmind_node("_run_worker() - 工作循环"),
                                create_xmind_node("_publish_lead() - Lead 消息发布到 EventInbox")
                            ]
                        ),
                        create_xmind_node(
                            "_Worker 内部状态",
                            [
                                create_xmind_node("teammate - 不可变快照"),
                                create_xmind_node("runner - 独立 AgentRunner"),
                                create_xmind_node("thread - 可复用线程"),
                                create_xmind_node("current - 当前处理消息")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/loop.py 的 run_events()",
                    [
                        create_xmind_node("优先处理 _pending_event_acks"),
                        create_xmind_node("取下一条事件（deferred 或 drain）"),
                        create_xmind_node("执行事件回合"),
                        create_xmind_node("ack 成功 → 返回结果"),
                        create_xmind_node("ack 失败 → 保存到 pending 字典"),
                        create_xmind_node("模型失败 → release 租约")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "领域模型对照",
                    [
                        create_xmind_node("MailboxMessage = record MailboxMessage(...)"),
                        create_xmind_node("MailboxStore = MailboxRepository 接口"),
                        create_xmind_node("FileMailboxStore = 文件版 Repository 实现"),
                        create_xmind_node("四态状态机 = 数据库状态字段")
                    ]
                ),
                create_xmind_node(
                    "运行时对照",
                    [
                        create_xmind_node("TeammateRuntime = ExecutorService + 队友注册表"),
                        create_xmind_node("_Worker = Callable<Void> 或 Runnable"),
                        create_xmind_node("EventInbox = BlockingQueue<RuntimeEvent>"),
                        create_xmind_node("_run_worker 循环 = @Scheduled 或 Quartz Job")
                    ]
                ),
                create_xmind_node(
                    "持久化对照",
                    [
                        create_xmind_node("_atomic_write = Files.move(ATOMIC_MOVE)"),
                        create_xmind_node("_move 状态迁移 = UPDATE WHERE state=?"),
                        create_xmind_node("recover_processing = @EventListener(ContextRefreshedEvent)"),
                        create_xmind_node("quarantine = Dead Letter Queue")
                    ]
                ),
                create_xmind_node(
                    "安全边界对照",
                    [
                        create_xmind_node("canonical_agent_name = @Pattern 校验注解"),
                        create_xmind_node("ToolContext.identity = @AuthenticationPrincipal"),
                        create_xmind_node("sender 保护 = Spring Security"),
                        create_xmind_node("ack-after-processing = Kafka manual commit")
                    ]
                )
            ]
        ),

        # 设计模式识别分支
        create_xmind_node(
            "设计模式识别",
            [
                create_xmind_node(
                    "Repository 模式",
                    [
                        create_xmind_node("MailboxStore 定义存储接口"),
                        create_xmind_node("FileMailboxStore 实现文件存储"),
                        create_xmind_node("领域模型不依赖存储技术")
                    ]
                ),
                create_xmind_node(
                    "Worker 模式",
                    [
                        create_xmind_node("每个队友独立工作线程"),
                        create_xmind_node("idle 状态可复用"),
                        create_xmind_node("失败后报告 result 给 Lead")
                    ]
                ),
                create_xmind_node(
                    "租约模式",
                    [
                        create_xmind_node("processing 状态即租约"),
                        create_xmind_node("只有租约持有者可 ack/release"),
                        create_xmind_node("recover_processing 恢复遗留租约")
                    ]
                ),
                create_xmind_node(
                    "事件溯源",
                    [
                        create_xmind_node("message.id 同时是事件 ID"),
                        create_xmind_node("done 目录保留完整历史"),
                        create_xmind_node("可审计和重放")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "四态状态机",
                    [
                        create_xmind_node("ready - 等待被消费"),
                        create_xmind_node("processing - 正在处理（租约）"),
                        create_xmind_node("done - 已完成"),
                        create_xmind_node("quarantine - 隔离坏消息")
                    ]
                ),
                create_xmind_node(
                    "message.id 三重身份",
                    [
                        create_xmind_node("消息主键（全局唯一）"),
                        create_xmind_node("事件去重 ID（_seen_event_ids）"),
                        create_xmind_node("工具幂等键（ToolContext.idempotency_key）")
                    ]
                ),
                create_xmind_node(
                    "ack-after-processing 原则",
                    [
                        create_xmind_node("claim 后不立即 ack"),
                        create_xmind_node("模型处理完成后才 ack"),
                        create_xmind_node("ack 失败保留租约 + 保存到 pending"),
                        create_xmind_node("模型失败 release 租约")
                    ]
                ),
                create_xmind_node(
                    "队友复用机制",
                    [
                        create_xmind_node("idle 队友保留 Runner 和历史"),
                        create_xmind_node("收到消息时改状态 → running"),
                        create_xmind_node("启动新线程，复用原 Runner"),
                        create_xmind_node("历史自然延续")
                    ]
                ),
                create_xmind_node(
                    "sender 来源保护",
                    [
                        create_xmind_node("sender 只能来自 ToolContext.identity"),
                        create_xmind_node("模型不能在 arguments 中传递 sender"),
                        create_xmind_node("防止伪造发送者身份"),
                        create_xmind_node("保证审计追踪可信")
                    ]
                ),
                create_xmind_node(
                    "故障恢复策略",
                    [
                        create_xmind_node("临时文件崩溃 → 无残留"),
                        create_xmind_node("claim 后崩溃 → recover_processing"),
                        create_xmind_node("ack 失败崩溃 → 保留租约补 ack"),
                        create_xmind_node("模型失败 → release 重试")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 为什么 message.id 同时充当事件 ID 和幂等键？",
                    [
                        create_xmind_node("A: 事件去重 - _seen_event_ids 防止重复注入"),
                        create_xmind_node("工具幂等 - idempotency_key 让工具副作用去重"),
                        create_xmind_node("统一身份 - 一个消息一个稳定标识"),
                        create_xmind_node("租约关联 - processing 文件名就是消息 ID")
                    ]
                ),
                create_xmind_node(
                    "Q2: FileMailboxStore 如何通过 rename 实现原子状态迁移？",
                    [
                        create_xmind_node("A: 目录名即状态（ready/processing/done/quarantine）"),
                        create_xmind_node("rename 原子性 - 文件系统保证"),
                        create_xmind_node("条件更新 - 先检查目标不存在再 rename"),
                        create_xmind_node("租约机制 - 只有 processing 可 ack/release")
                    ]
                ),
                create_xmind_node(
                    "Q3: 为什么事件回合完成后才 ack？",
                    [
                        create_xmind_node("A: at-least-once 语义 - claim 后立即 ack 会丢消息"),
                        create_xmind_node("可重试性 - ack 前失败消息仍在 processing"),
                        create_xmind_node("补确认机制 - ack 失败保存 pending 不重复调用模型"),
                        create_xmind_node("租约保护 - 模型执行期间租约一直持有")
                    ]
                ),
                create_xmind_node(
                    "Q4: TeammateRuntime 如何复用 idle 队友的 Runner？",
                    [
                        create_xmind_node("A: 状态转换 - 任务完成后 idle，线程退出"),
                        create_xmind_node("唤醒机制 - send() 检测 idle 改状态 running"),
                        create_xmind_node("历史保留 - _Worker.runner 不清空"),
                        create_xmind_node("线程复用 - 新线程复用同一 Runner")
                    ]
                ),
                create_xmind_node(
                    "Q5: 为什么 sender 只能来自 ToolContext.identity？",
                    [
                        create_xmind_node("A: 安全边界 - 防止模型伪造发送者"),
                        create_xmind_node("审计追踪 - sender 由可信运行时提供"),
                        create_xmind_node("身份传播 - Lead 回合是 lead，队友回合是队友名"),
                        create_xmind_node("攻击场景 - 防止恶意 prompt 冒充身份")
                    ]
                ),
                create_xmind_node(
                    "Q6: recover_processing 在什么时机调用？",
                    [
                        create_xmind_node("A: 启动时机 - TeammateRuntime.start() 和 spawn()"),
                        create_xmind_node("故障场景 - claim 后、ack 前崩溃"),
                        create_xmind_node("租约语义 - processing 即某消费者正在处理"),
                        create_xmind_node("恢复策略 - 把所有 processing 退回 ready")
                    ]
                ),
                create_xmind_node(
                    "Q7: quarantine 目录的作用是什么？",
                    [
                        create_xmind_node("A: 隔离坏消息 - JSON 损坏、字段缺失"),
                        create_xmind_node("保留审计 - 不删除便于事后排查"),
                        create_xmind_node("不阻塞队列 - 坏消息不卡住其他消息"),
                        create_xmind_node("触发场景 - _valid_entries 自动隔离、主动调用")
                    ]
                ),
                create_xmind_node(
                    "Q8: _pending_event_acks 如何解决 ack 失败问题？",
                    [
                        create_xmind_node("A: 问题场景 - 模型回合完成但 ack 失败"),
                        create_xmind_node("租约状态 - 消息仍在 processing"),
                        create_xmind_node("重复风险 - 直接 release 会重复调用模型"),
                        create_xmind_node("解决方案 - 保存 (event, result) 下次只补 ack")
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
    "title": "第 15 章学习导航",
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
output_path = Path(__file__).parent / "ch15_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"XMind file generated: {output_path}")
print(f"File size: {output_path.stat().st_size} bytes")
print(f"Compatible with XMind 8/2020/2023")
