#!/usr/bin/env python3
"""生成第 12 章 XMind 8/2020+ 格式的脑图文件。

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
    "第 12 章：持久化 Task DAG",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解 Task 领域模型",
                    [
                        create_xmind_node("tests/test_tasks.py"),
                        create_xmind_node("features/tasks.py（Task 类和五个工具）"),
                        create_xmind_node("理解 Task DAG 与 TODO 的区别")
                    ]
                ),
                create_xmind_node(
                    "第二步：理解持久化机制",
                    [
                        create_xmind_node("adapters/task_json.py（JSON 存储）"),
                        create_xmind_node("文件锁和原子写入"),
                        create_xmind_node("DAG 校验和环检测")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解五个工具协议",
                    [
                        create_xmind_node("create_task（创建）"),
                        create_xmind_node("list_tasks（列出）"),
                        create_xmind_node("claim_task（认领）"),
                        create_xmind_node("complete_task（完成）"),
                        create_xmind_node("get_task（查询）")
                    ]
                ),
                create_xmind_node(
                    "第四步：集成测试理解流程",
                    [
                        create_xmind_node("tests/test_ch12_integration.py"),
                        create_xmind_node("创建 → 认领 → 完成 → 依赖解锁"),
                        create_xmind_node("并发访问和冲突处理")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "features/tasks.py（Task 领域模型）",
                    [
                        create_xmind_node(
                            "Task 数据类",
                            [
                                create_xmind_node("id（UUID）"),
                                create_xmind_node("subject（标题）"),
                                create_xmind_node("description（描述）"),
                                create_xmind_node("status（pending/in_progress/completed）"),
                                create_xmind_node("owner（认领者）"),
                                create_xmind_node("blocked_by（依赖任务 ID 列表）"),
                                create_xmind_node("created_at / completed_at（时间戳）")
                            ]
                        ),
                        create_xmind_node(
                            "异常定义",
                            [
                                create_xmind_node("TaskNotFoundError（任务不存在）"),
                                create_xmind_node("TaskGraphError（DAG 环或缺边）"),
                                create_xmind_node("TaskStateError（状态转换非法）"),
                                create_xmind_node("TaskBlockedError（依赖未完成）"),
                                create_xmind_node("TaskOwnershipError（认领冲突）"),
                                create_xmind_node("TaskStorageError（存储失败）")
                            ]
                        ),
                        create_xmind_node(
                            "五个工具函数",
                            [
                                create_xmind_node("register_task_tools（注册到 ToolRegistry）"),
                                create_xmind_node("_create_task_definition"),
                                create_xmind_node("_list_tasks_definition"),
                                create_xmind_node("_claim_task_definition"),
                                create_xmind_node("_complete_task_definition"),
                                create_xmind_node("_get_task_definition")
                            ]
                        ),
                        create_xmind_node(
                            "TaskStore 接口",
                            [
                                create_xmind_node("create（创建任务）"),
                                create_xmind_node("list_all（列出所有）"),
                                create_xmind_node("get（查询单个）"),
                                create_xmind_node("claim（认领任务）"),
                                create_xmind_node("complete（完成任务）")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "adapters/task_json.py（JSON 存储适配器）",
                    [
                        create_xmind_node(
                            "JsonTaskStore 类",
                            [
                                create_xmind_node("_file_path（任务图 JSON 路径）"),
                                create_xmind_node("_lock（文件锁对象）"),
                                create_xmind_node("_validate_graph（DAG 校验）"),
                                create_xmind_node("_detect_cycles（环检测算法）"),
                                create_xmind_node("_atomic_write（原子写入）")
                            ]
                        ),
                        create_xmind_node(
                            "并发安全机制",
                            [
                                create_xmind_node("fcntl.flock（POSIX 文件锁）"),
                                create_xmind_node("msvcrt.locking（Windows 文件锁）"),
                                create_xmind_node("write + rename 原子替换")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "features/skills.py（第 7 章 Skill 按需加载）",
                    [
                        create_xmind_node("SkillRegistry（技能注册表）"),
                        create_xmind_node("load_skill 工具（只读 frontmatter）"),
                        create_xmind_node("路径安全边界校验")
                    ]
                ),
                create_xmind_node(
                    "features/subagents.py（第 6 章子 Agent）",
                    [
                        create_xmind_node("SubagentTool（task 工具）"),
                        create_xmind_node("ModelClientFactory / ToolRegistryFactory"),
                        create_xmind_node("父子历史隔离，Hook/权限共享")
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
                        create_xmind_node("Task = @Entity / record Task"),
                        create_xmind_node("TaskStore = Repository interface"),
                        create_xmind_node("JsonTaskStore = RepositoryImpl（文件）"),
                        create_xmind_node("TaskError = BusinessException")
                    ]
                ),
                create_xmind_node(
                    "状态机对照",
                    [
                        create_xmind_node("pending → in_progress（claim）"),
                        create_xmind_node("in_progress → completed（complete）"),
                        create_xmind_node("类似订单状态机或工单流转")
                    ]
                ),
                create_xmind_node(
                    "DAG 对照",
                    [
                        create_xmind_node("blocked_by = List<String>（依赖 ID）"),
                        create_xmind_node("环检测 = 拓扑排序 / DFS"),
                        create_xmind_node("类似 Maven 依赖图或 Gradle Task Graph")
                    ]
                ),
                create_xmind_node(
                    "并发控制对照",
                    [
                        create_xmind_node("文件锁 = 分布式锁（单机版）"),
                        create_xmind_node("原子写入 = 数据库事务"),
                        create_xmind_node("乐观锁思想：完成时检查依赖状态")
                    ]
                ),
                create_xmind_node(
                    "工具注册对照",
                    [
                        create_xmind_node("register_task_tools = 命令总线注册"),
                        create_xmind_node("每个工具 = CommandHandler"),
                        create_xmind_node("ToolDefinition = @Command 元数据")
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
                        create_xmind_node("TaskStore 是领域层接口"),
                        create_xmind_node("JsonTaskStore 是基础设施层实现"),
                        create_xmind_node("可替换为 SQLite/Redis 存储")
                    ]
                ),
                create_xmind_node(
                    "状态模式",
                    [
                        create_xmind_node("Task.status 控制允许的操作"),
                        create_xmind_node("pending 可 claim，in_progress 可 complete"),
                        create_xmind_node("非法状态转换抛 TaskStateError")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("TaskStore 可注入不同存储策略"),
                        create_xmind_node("环检测算法可替换（DFS/拓扑排序）")
                    ]
                ),
                create_xmind_node(
                    "命令模式",
                    [
                        create_xmind_node("五个工具 = 五个命令"),
                        create_xmind_node("ToolDefinition 封装请求参数和校验"),
                        create_xmind_node("执行结果统一为 ToolResult")
                    ]
                ),
                create_xmind_node(
                    "防护策略",
                    [
                        create_xmind_node("canonical UUID 校验（正则表达式）"),
                        create_xmind_node("依赖完整性检查（缺边/自依赖）"),
                        create_xmind_node("环检测（防止循环依赖）"),
                        create_xmind_node("原子写入（防止脏读）")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "Task vs TODO 的区别",
                    [
                        create_xmind_node("TODO：会话内步骤清单，进程退出即丢失"),
                        create_xmind_node("Task：workspace 级项目状态，持久化到磁盘"),
                        create_xmind_node("Task 可以形成 DAG，TODO 只是顺序列表"),
                        create_xmind_node("Task 支持多人协作（owner 字段）")
                    ]
                ),
                create_xmind_node(
                    "为什么需要 blocked_by",
                    [
                        create_xmind_node("表达任务依赖关系（B 依赖 A）"),
                        create_xmind_node("自动解锁：A 完成后 B 才能认领"),
                        create_xmind_node("防止乱序执行导致错误")
                    ]
                ),
                create_xmind_node(
                    "环检测的必要性",
                    [
                        create_xmind_node("A 依赖 B，B 依赖 A → 死锁"),
                        create_xmind_node("创建和完成时都要检查"),
                        create_xmind_node("DFS 递归检测所有路径")
                    ]
                ),
                create_xmind_node(
                    "原子写入原理",
                    [
                        create_xmind_node("先写临时文件 .tmp"),
                        create_xmind_node("再 rename 替换原文件（原子操作）"),
                        create_xmind_node("避免并发写入导致 JSON 损坏")
                    ]
                ),
                create_xmind_node(
                    "文件锁的作用",
                    [
                        create_xmind_node("多进程/多线程访问同一 JSON 文件"),
                        create_xmind_node("读写操作串行化，防止竞态条件"),
                        create_xmind_node("POSIX 用 fcntl，Windows 用 msvcrt")
                    ]
                ),
                create_xmind_node(
                    "状态转换规则",
                    [
                        create_xmind_node("pending → in_progress：claim 时"),
                        create_xmind_node("in_progress → completed：complete 时"),
                        create_xmind_node("不能跳过 in_progress 直接完成"),
                        create_xmind_node("completed 任务不能再修改")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: Task DAG 和 TODO 有什么区别？",
                    [
                        create_xmind_node("A: TODO 是会话内步骤清单，进程退出丢失"),
                        create_xmind_node("Task 是持久化项目状态，支持 DAG 依赖关系"),
                        create_xmind_node("Task 有 owner 字段支持多人协作")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么需要环检测？如何实现？",
                    [
                        create_xmind_node("A: 防止循环依赖导致死锁（A 依赖 B，B 依赖 A）"),
                        create_xmind_node("DFS 递归检测：维护访问集合和递归栈"),
                        create_xmind_node("创建和完成时都要检查整个 DAG")
                    ]
                ),
                create_xmind_node(
                    "Q3: 原子写入如何保证 JSON 文件不损坏？",
                    [
                        create_xmind_node("A: 先写临时文件 .tmp，再 rename 替换"),
                        create_xmind_node("rename 在文件系统层面是原子操作"),
                        create_xmind_node("即使进程崩溃，也不会留下半截 JSON")
                    ]
                ),
                create_xmind_node(
                    "Q4: 文件锁在 Windows 和 Linux 上的区别？",
                    [
                        create_xmind_node("A: POSIX（Linux/macOS）用 fcntl.flock"),
                        create_xmind_node("Windows 用 msvcrt.locking"),
                        create_xmind_node("都是进程级锁，不跨机器（非分布式锁）")
                    ]
                ),
                create_xmind_node(
                    "Q5: TaskStore 接口为什么不直接用具体实现？",
                    [
                        create_xmind_node("A: 依赖倒置原则（领域层不依赖基础设施）"),
                        create_xmind_node("可替换存储方式（JSON → SQLite → Redis）"),
                        create_xmind_node("测试时可用 FakeTaskStore 替换")
                    ]
                ),
                create_xmind_node(
                    "Q6: 为什么 Task 状态不能直接从 pending 到 completed？",
                    [
                        create_xmind_node("A: 状态机设计：必须先 claim 再 complete"),
                        create_xmind_node("owner 字段记录认领者，防止多人同时执行"),
                        create_xmind_node("类似工单系统：领取 → 处理中 → 完成")
                    ]
                ),
                create_xmind_node(
                    "Q7: 如何处理依赖任务被删除的情况？",
                    [
                        create_xmind_node("A: DAG 校验会检测缺边（blocked_by 引用不存在的 ID）"),
                        create_xmind_node("抛 TaskGraphError 拒绝操作"),
                        create_xmind_node("必须先移除依赖关系再删除任务")
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
    "title": "第 12 章学习导航",
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
output_path = Path(__file__).parent / "ch12_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"[OK] XMind file generated: {output_path}")
print(f"   File size: {output_path.stat().st_size} bytes")
print(f"   Can be opened with XMind 8/2020/2023")
