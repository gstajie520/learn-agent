#!/usr/bin/env python3
"""生成第 9 章 XMind 8/2020+ 格式的脑图文件。

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
    "第 9 章：文件级长期记忆",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：读测试了解目标",
                    [
                        create_xmind_node("tests/test_memory.py"),
                        create_xmind_node("看记忆如何保存和选择"),
                        create_xmind_node("理解三文件协议")
                    ]
                ),
                create_xmind_node(
                    "第二步：读记忆核心系统",
                    [
                        create_xmind_node("features/memory.py"),
                        create_xmind_node("MemoryRecord 值对象"),
                        create_xmind_node("MemoryStore 文件事务"),
                        create_xmind_node("MemorySession 生命周期")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解集成点",
                    [
                        create_xmind_node("core/loop.py TurnLifecycle"),
                        create_xmind_node("bootstrap.py P09 配置"),
                        create_xmind_node("tests/test_ch09_integration.py")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "features/memory.py（记忆系统）",
                    [
                        create_xmind_node(
                            "MemoryRecord 值对象",
                            [
                                create_xmind_node("name: 逻辑名称（slug）"),
                                create_xmind_node("description: 一行摘要"),
                                create_xmind_node("kind: 分类（user/feedback/project/reference）"),
                                create_xmind_node("body: 完整正文")
                            ]
                        ),
                        create_xmind_node(
                            "MemoryStore Repository",
                            [
                                create_xmind_node("save() 保存记忆"),
                                create_xmind_node("list() 列出所有记忆"),
                                create_xmind_node("get() 读取单条记忆"),
                                create_xmind_node("delete() 删除记忆"),
                                create_xmind_node("_commit() 原子事务")
                            ]
                        ),
                        create_xmind_node(
                            "MemorySession 生命周期",
                            [
                                create_xmind_node("begin_turn() 选择相关记忆"),
                                create_xmind_node("before_model() 注入记忆上下文"),
                                create_xmind_node("complete() 提取新记忆"),
                                create_xmind_node("_consolidate() 整理合并")
                            ]
                        ),
                        create_xmind_node(
                            "三个模型查询",
                            [
                                create_xmind_node("_select_memory_names() 选择器"),
                                create_xmind_node("_extract_memories() 提取器"),
                                create_xmind_node("_consolidate() 整理器")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（生命周期接口）",
                    [
                        create_xmind_node("TurnLifecycle Protocol"),
                        create_xmind_node("begin_turn() 回合开始前"),
                        create_xmind_node("before_model() 模型请求前"),
                        create_xmind_node("complete() 回合结束后")
                    ]
                ),
                create_xmind_node(
                    "bootstrap.py（依赖注入）",
                    [
                        create_xmind_node("P09 配置"),
                        create_xmind_node("装配 MemoryStore"),
                        create_xmind_node("装配 MemorySession"),
                        create_xmind_node("注入生命周期")
                    ]
                ),
                create_xmind_node(
                    "三文件协议",
                    [
                        create_xmind_node("manifest.json（权威指针）"),
                        create_xmind_node("MEMORY.md（轻量目录）"),
                        create_xmind_node("<name>-<id>.md（记忆正文）")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "架构层次对照",
                    [
                        create_xmind_node("MemoryRecord = record 值对象"),
                        create_xmind_node("MemoryStore = Repository + 本地事务"),
                        create_xmind_node("MemorySession = HandlerInterceptor"),
                        create_xmind_node("TurnLifecycle = 生命周期 interface")
                    ]
                ),
                create_xmind_node(
                    "持久化对照",
                    [
                        create_xmind_node("manifest.json = 数据库主表"),
                        create_xmind_node("MEMORY.md = 查询视图（可重建）"),
                        create_xmind_node("临时目录 + rename = 文件事务"),
                        create_xmind_node("RLock = synchronized 锁")
                    ]
                ),
                create_xmind_node(
                    "模式对照",
                    [
                        create_xmind_node("side-query = 服务内调用"),
                        create_xmind_node("selector = 查询服务"),
                        create_xmind_node("extractor = 解析服务"),
                        create_xmind_node("consolidator = 整理服务")
                    ]
                ),
                create_xmind_node(
                    "数据结构对照",
                    [
                        create_xmind_node("frozenset = Set.of()"),
                        create_xmind_node("Path.resolve() = File.getCanonicalPath()"),
                        create_xmind_node("yaml.safe_load = Jackson YAML"),
                        create_xmind_node("tempfile.mkdtemp = Files.createTempDirectory")
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
                        create_xmind_node("MemoryStore 封装文件操作"),
                        create_xmind_node("统一的 CRUD 接口"),
                        create_xmind_node("路径安全和事务保证")
                    ]
                ),
                create_xmind_node(
                    "拦截器模式",
                    [
                        create_xmind_node("MemorySession 实现 TurnLifecycle"),
                        create_xmind_node("回合前选择记忆"),
                        create_xmind_node("回合后提取记忆")
                    ]
                ),
                create_xmind_node(
                    "事务模式",
                    [
                        create_xmind_node("临时目录写入所有文件"),
                        create_xmind_node("原子 rename 到目标位置"),
                        create_xmind_node("manifest 最后更新")
                    ]
                ),
                create_xmind_node(
                    "值对象模式",
                    [
                        create_xmind_node("MemoryRecord 不可变"),
                        create_xmind_node("frozen dataclass"),
                        create_xmind_node("__post_init__ 校验")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("三个模型查询函数"),
                        create_xmind_node("可独立测试和替换"),
                        create_xmind_node("无工具 side-query")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "记忆生命周期",
                    [
                        create_xmind_node("begin_turn 选择相关记忆"),
                        create_xmind_node("before_model 临时注入上下文"),
                        create_xmind_node("Agent Loop 正常执行"),
                        create_xmind_node("complete 提取新记忆"),
                        create_xmind_node("达到阈值时整理合并")
                    ]
                ),
                create_xmind_node(
                    "三文件协议",
                    [
                        create_xmind_node("manifest.json 是权威指针"),
                        create_xmind_node("MEMORY.md 是可重建目录"),
                        create_xmind_node("<name>-<id>.md 是记忆正文"),
                        create_xmind_node("三者必须保持一致")
                    ]
                ),
                create_xmind_node(
                    "文件事务原子性",
                    [
                        create_xmind_node("先写临时目录"),
                        create_xmind_node("原子 rename 所有文件"),
                        create_xmind_node("manifest 最后更新"),
                        create_xmind_node("失败时临时目录被丢弃")
                    ]
                ),
                create_xmind_node(
                    "无工具 side-query",
                    [
                        create_xmind_node("selector 选择相关记忆名称"),
                        create_xmind_node("extractor 从对话提取新记忆"),
                        create_xmind_node("consolidator 整理合并重复"),
                        create_xmind_node("模型只提供决策，不直接操作文件")
                    ]
                ),
                create_xmind_node(
                    "记忆注入方式",
                    [
                        create_xmind_node("临时 system 消息"),
                        create_xmind_node("只影响当前请求"),
                        create_xmind_node("不追加到 canonical history"),
                        create_xmind_node("下次回合自动消失")
                    ]
                ),
                create_xmind_node(
                    "整理触发时机",
                    [
                        create_xmind_node("累积 5 条待处理记忆"),
                        create_xmind_node("调用 consolidator 合并"),
                        create_xmind_node("删除旧记忆文件"),
                        create_xmind_node("原子保存新记忆")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 第 9 章的记忆和第 8 章的压缩有什么区别？",
                    [
                        create_xmind_node("A: 压缩在当前会话内减少 token"),
                        create_xmind_node("记忆是跨会话保留知识"),
                        create_xmind_node("压缩丢失细节但保留脉络"),
                        create_xmind_node("记忆保留核心事实但不是完整对话")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么 manifest.json 和 MEMORY.md 要分离？",
                    [
                        create_xmind_node("A: manifest 是事务权威（JSON 易解析）"),
                        create_xmind_node("MEMORY.md 是轻量目录（模型友好）"),
                        create_xmind_node("MEMORY.md 可以从 manifest 重建"),
                        create_xmind_node("选择器不需要解析完整 JSON")
                    ]
                ),
                create_xmind_node(
                    "Q3: 记忆的文件事务如何保证原子性？",
                    [
                        create_xmind_node("A: 先写临时目录（所有 .md 文件）"),
                        create_xmind_node("最后原子 rename 到目标路径"),
                        create_xmind_node("中途失败则临时目录被丢弃"),
                        create_xmind_node("manifest.json 最后更新保证一致性")
                    ]
                ),
                create_xmind_node(
                    "Q4: 为什么记忆不是模型可直接调用的普通工具？",
                    [
                        create_xmind_node("A: 普通工具调用可能被拒绝或重试"),
                        create_xmind_node("会破坏事务一致性"),
                        create_xmind_node("用无工具 side-query + 受控 Store"),
                        create_xmind_node("保证逻辑由系统控制，模型只提供决策")
                    ]
                ),
                create_xmind_node(
                    "Q5: 记忆注入为什么用临时 system 消息？",
                    [
                        create_xmind_node("A: 记忆是辅助上下文，不应污染 history"),
                        create_xmind_node("临时注入只影响当前模型请求"),
                        create_xmind_node("下次回合自动消失"),
                        create_xmind_node("history 保持对话真相")
                    ]
                ),
                create_xmind_node(
                    "Q6: 整理（consolidate）的触发时机和作用？",
                    [
                        create_xmind_node("A: 累积 5 条待处理记忆时触发"),
                        create_xmind_node("合并重复记忆、解决冲突、压缩冗余"),
                        create_xmind_node("输出 source_names（要替换的旧记忆）"),
                        create_xmind_node("输出 records（整理后的新记忆）")
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
    "title": "第 9 章学习导航",
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
output_path = Path(__file__).parent / "ch09_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"XMind file generated: {output_path}")
print(f"File size: {output_path.stat().st_size} bytes")
print(f"Can be opened with XMind 8/2020/2023")
