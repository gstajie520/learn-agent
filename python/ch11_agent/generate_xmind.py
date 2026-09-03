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
    "第 11 章：模型 API 恢复策略",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：读测试了解故障场景",
                    [
                        create_xmind_node("tests/test_recovery.py"),
                        create_xmind_node("理解三种故障类型"),
                        create_xmind_node("观察每种故障的恢复策略")
                    ]
                ),
                create_xmind_node(
                    "第二步：读恢复管理器",
                    [
                        create_xmind_node("features/recovery.py"),
                        create_xmind_node("RecoveryManager.complete() 方法"),
                        create_xmind_node("理解升级→续写→压缩→退避流程")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解异常映射",
                    [
                        create_xmind_node("adapters/openai_chat.py"),
                        create_xmind_node("core/model.py"),
                        create_xmind_node("供应商错误如何归一化")
                    ]
                ),
                create_xmind_node(
                    "第四步：理解接入点",
                    [
                        create_xmind_node("core/loop.py"),
                        create_xmind_node("bootstrap.py"),
                        create_xmind_node("哪些请求使用恢复层")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "features/recovery.py（恢复层）",
                    [
                        create_xmind_node(
                            "RecoveryManager 类",
                            [
                                create_xmind_node("begin_turn() 重置状态"),
                                create_xmind_node("complete() 主恢复循环"),
                                create_xmind_node("_retry_transient() 退避逻辑")
                            ]
                        ),
                        create_xmind_node(
                            "RecoveryConfig",
                            [
                                create_xmind_node("primary_model / fallback_model"),
                                create_xmind_node("initial_max_tokens / escalated_max_tokens"),
                                create_xmind_node("max_continuations / max_transient_attempts")
                            ]
                        ),
                        create_xmind_node(
                            "RecoveryState",
                            [
                                create_xmind_node("current_model / current_max_tokens"),
                                create_xmind_node("has_escalated / recovery_count"),
                                create_xmind_node("consecutive_529")
                            ]
                        ),
                        create_xmind_node(
                            "CancellationToken",
                            [
                                create_xmind_node("is_cancelled 属性"),
                                create_xmind_node("cancel() 方法"),
                                create_xmind_node("subscribe() 监听器")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/model.py（异常定义）",
                    [
                        create_xmind_node("ModelClient 接口"),
                        create_xmind_node("ModelRateLimitError（429）"),
                        create_xmind_node("ModelOverloadedError（529）"),
                        create_xmind_node("ModelPromptTooLongError（输入过长）")
                    ]
                ),
                create_xmind_node(
                    "adapters/openai_chat.py（适配器）",
                    [
                        create_xmind_node("_map_api_status_error()"),
                        create_xmind_node("把 OpenAI/DeepSeek 错误转换为内部异常"),
                        create_xmind_node("读取 Retry-After 头")
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（接入点）",
                    [
                        create_xmind_node("ModelRequestExecutor 接口"),
                        create_xmind_node("AgentRunner 使用 executor"),
                        create_xmind_node("begin_turn() / complete() 调用")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "核心概念对照",
                    [
                        create_xmind_node("RecoveryManager = Resilience Service"),
                        create_xmind_node("CancellationToken = AtomicBoolean + listeners"),
                        create_xmind_node("ModelRequestExecutor = Strategy 接口"),
                        create_xmind_node("异常映射 = Adapter 层职责")
                    ]
                ),
                create_xmind_node(
                    "设计模式对照",
                    [
                        create_xmind_node("适配器模式（供应商错误归一化）"),
                        create_xmind_node("策略模式（可插拔恢复层）"),
                        create_xmind_node("状态模式（RecoveryState）"),
                        create_xmind_node("装饰器模式（包装 ModelClient）")
                    ]
                ),
                create_xmind_node(
                    "技术对照",
                    [
                        create_xmind_node("指数退避 = Exponential Backoff"),
                        create_xmind_node("Retry-After = HTTP 标准头"),
                        create_xmind_node("Jitter = 随机抖动避免惊群"),
                        create_xmind_node("Deadline = 总超时时限")
                    ]
                ),
                create_xmind_node(
                    "异常处理对照",
                    [
                        create_xmind_node("RecoveryError = 恢复层基础异常"),
                        create_xmind_node("RecoveryCancelledError = 取消异常"),
                        create_xmind_node("RecoveryRetriesExhausted = 重试耗尽"),
                        create_xmind_node("RecoveryDeadlineExceeded = 超时异常")
                    ]
                )
            ]
        ),

        # 设计模式识别分支
        create_xmind_node(
            "设计模式识别",
            [
                create_xmind_node(
                    "适配器模式",
                    [
                        create_xmind_node("供应商异常 → 内部异常"),
                        create_xmind_node("_map_api_status_error() 映射函数"),
                        create_xmind_node("核心层不依赖 OpenAI SDK")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("ModelRequestExecutor 接口"),
                        create_xmind_node("raw model 或 RecoveryManager"),
                        create_xmind_node("Bootstrap 决定使用哪个策略")
                    ]
                ),
                create_xmind_node(
                    "状态模式",
                    [
                        create_xmind_node("RecoveryState 可变状态"),
                        create_xmind_node("has_escalated / recovery_count"),
                        create_xmind_node("每个 turn 重置状态")
                    ]
                ),
                create_xmind_node(
                    "装饰器模式",
                    [
                        create_xmind_node("RecoveryManager 包装 ModelClient"),
                        create_xmind_node("透明增加恢复能力"),
                        create_xmind_node("外层感知不到内部重试")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "三种故障类型",
                    [
                        create_xmind_node("输出截断：finish_reason == 'length'"),
                        create_xmind_node("输入过长：ModelPromptTooLongError"),
                        create_xmind_node("临时故障：429/529 错误")
                    ]
                ),
                create_xmind_node(
                    "输出截断恢复",
                    [
                        create_xmind_node("第一次：升级 max_tokens 到 64000"),
                        create_xmind_node("第二次：追加片段并续写"),
                        create_xmind_node("成功后合并所有片段")
                    ]
                ),
                create_xmind_node(
                    "输入过长恢复",
                    [
                        create_xmind_node("保留首条 system message"),
                        create_xmind_node("调用 CompactionManager 压缩"),
                        create_xmind_node("一次请求只压缩一次")
                    ]
                ),
                create_xmind_node(
                    "临时故障恢复",
                    [
                        create_xmind_node("429：优先遵守 Retry-After"),
                        create_xmind_node("529：连续 3 次切换 fallback"),
                        create_xmind_node("指数退避 + 随机抖动")
                    ]
                ),
                create_xmind_node(
                    "取消与超时",
                    [
                        create_xmind_node("CancellationToken 通知机制"),
                        create_xmind_node("每次边界检查取消状态"),
                        create_xmind_node("总 deadline 保护")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 为什么需要恢复层？",
                    [
                        create_xmind_node("A: 真实生产环境存在三类故障"),
                        create_xmind_node("输出截断、输入过长、临时 API 错误"),
                        create_xmind_node("恢复层统一处理，避免每个调用点重复实现")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么供应商错误要归一化？",
                    [
                        create_xmind_node("A: 核心层不应依赖 OpenAI SDK"),
                        create_xmind_node("适配器层负责转换为领域异常"),
                        create_xmind_node("切换供应商时只改适配器")
                    ]
                ),
                create_xmind_node(
                    "Q3: 输出截断为什么分两步处理？",
                    [
                        create_xmind_node("A: 第一次可能只是预算设小了"),
                        create_xmind_node("直接升级到 64000 更经济"),
                        create_xmind_node("仍截断才启动续写机制")
                    ]
                ),
                create_xmind_node(
                    "Q4: 为什么摘要请求不能套恢复层？",
                    [
                        create_xmind_node("A: 避免递归：输入过长→摘要→输入过长"),
                        create_xmind_node("摘要请求使用 raw ModelClient"),
                        create_xmind_node("摘要本身应该足够短")
                    ]
                ),
                create_xmind_node(
                    "Q5: 指数退避为什么要加 Jitter？",
                    [
                        create_xmind_node("A: 避免惊群效应"),
                        create_xmind_node("多个客户端同时重试会再次过载"),
                        create_xmind_node("随机抖动分散请求时间")
                    ]
                ),
                create_xmind_node(
                    "Q6: 为什么连续 3 次 529 才切 fallback？",
                    [
                        create_xmind_node("A: 偶发性过载应该重试"),
                        create_xmind_node("连续失败说明主模型持续不可用"),
                        create_xmind_node("3 次是经验值，可配置")
                    ]
                ),
                create_xmind_node(
                    "Q7: CancellationToken 和 Python 的区别？",
                    [
                        create_xmind_node("A: Python 同步 SDK 无法中断运行中调用"),
                        create_xmind_node("只能在调用边界和等待阶段检查"),
                        create_xmind_node("TypeScript AbortSignal 可强制中止")
                    ]
                ),
                create_xmind_node(
                    "Q8: 为什么外层历史不包含续写消息？",
                    [
                        create_xmind_node("A: 续写发生在局部 request_messages"),
                        create_xmind_node("成功后合并为一条完整回复"),
                        create_xmind_node("外层只看到最终结果，不知道内部重试")
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
    "title": "第 11 章学习导航",
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
output_path = Path(__file__).parent / "ch11_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"XMind file generated: {output_path}")
print(f"File size: {output_path.stat().st_size} bytes")
print(f"Compatible with XMind 8/2020/2023")
