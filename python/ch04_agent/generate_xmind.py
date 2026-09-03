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
    "第 4 章：Agent Hook 生命周期",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：读测试了解 Hook 契约",
                    [
                        create_xmind_node("tests/test_hooks.py"),
                        create_xmind_node("理解四个生命周期事件"),
                        create_xmind_node("HookContext 和 HookResult 的结构")
                    ]
                ),
                create_xmind_node(
                    "第二步：理解 Hook 系统设计",
                    [
                        create_xmind_node("core/hooks.py"),
                        create_xmind_node("HookRegistry 注册机制"),
                        create_xmind_node("事件触发点和回调执行")
                    ]
                ),
                create_xmind_node(
                    "第三步：看 Hook 如何接入循环",
                    [
                        create_xmind_node("tests/test_ch04_integration.py"),
                        create_xmind_node("core/loop.py（带 Hook 的 AgentRunner）"),
                        create_xmind_node("tool_call_id 配对保证")
                    ]
                ),
                create_xmind_node(
                    "第四步：理解权限与 Hook 协作",
                    [
                        create_xmind_node("core/permissions.py"),
                        create_xmind_node("系统 deny 高于 Hook allow"),
                        create_xmind_node("审批和审计流程")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "core/hooks.py（Hook 生命周期）",
                    [
                        create_xmind_node(
                            "HookContext",
                            [
                                create_xmind_node("event: 四种事件类型"),
                                create_xmind_node("message: UserPromptSubmit 的用户消息"),
                                create_xmind_node("prepared: PreToolUse/PostToolUse 的工具调用"),
                                create_xmind_node("result: PostToolUse 的工具结果"),
                                create_xmind_node("history: Stop 的完整历史")
                            ]
                        ),
                        create_xmind_node(
                            "HookResult",
                            [
                                create_xmind_node("deny: 阻止工具执行"),
                                create_xmind_node("stop: 主动结束 Agent"),
                                create_xmind_node("append_messages: 注入上下文"),
                                create_xmind_node("replace_prepared: 修改工具调用"),
                                create_xmind_node("replace_result: 修改工具结果")
                            ]
                        ),
                        create_xmind_node(
                            "HookRegistry",
                            [
                                create_xmind_node("register: 注册回调"),
                                create_xmind_node("run_user_prompt: UserPromptSubmit"),
                                create_xmind_node("run_pre_tool: PreToolUse"),
                                create_xmind_node("run_post_tool: PostToolUse"),
                                create_xmind_node("run_stop: Stop")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（带 Hook 的循环）",
                    [
                        create_xmind_node("AgentRunner 构造器接受 HookRegistry"),
                        create_xmind_node("四个 Hook 触发点"),
                        create_xmind_node("tool_call_id 强配对保证"),
                        create_xmind_node("_execute_tool 工具执行链路")
                    ]
                ),
                create_xmind_node(
                    "core/permissions.py（权限策略）",
                    [
                        create_xmind_node("PermissionPolicy（策略引擎）"),
                        create_xmind_node("PermissionRule（规则对象）"),
                        create_xmind_node("PermissionDecision（四态决策）"),
                        create_xmind_node("ApprovalProvider（审批接口）"),
                        create_xmind_node("AuditSink（审计接口）")
                    ]
                ),
                create_xmind_node(
                    "bootstrap.py（组合根）",
                    [
                        create_xmind_node("build_agent 工厂方法"),
                        create_xmind_node("P04 才允许注入 HookRegistry"),
                        create_xmind_node("能力越级检查")
                    ]
                )
            ]
        ),

        # Java 对照关系分支
        create_xmind_node(
            "Java 对照关系",
            [
                create_xmind_node(
                    "Hook 设计模式",
                    [
                        create_xmind_node("HookRegistry = 观察者注册表"),
                        create_xmind_node("HookContext = 不可变 DTO"),
                        create_xmind_node("HookResult = 影响声明对象"),
                        create_xmind_node("回调 = BiConsumer<Context, Result>")
                    ]
                ),
                create_xmind_node(
                    "异步处理对照",
                    [
                        create_xmind_node("async/await = CompletableFuture"),
                        create_xmind_node("asyncio.run = future.join()"),
                        create_xmind_node("Awaitable = CompletionStage"),
                        create_xmind_node("异步回调 = async 函数")
                    ]
                ),
                create_xmind_node(
                    "数据不可变性",
                    [
                        create_xmind_node("@dataclass(frozen=True) = record"),
                        create_xmind_node("replace() = record.with(...)"),
                        create_xmind_node("tuple = List.copyOf()"),
                        create_xmind_node("MappingProxyType = Collections.unmodifiableMap")
                    ]
                ),
                create_xmind_node(
                    "契约校验",
                    [
                        create_xmind_node("__post_init__ = 构造器校验"),
                        create_xmind_node("HookContractError = 领域异常"),
                        create_xmind_node("isinstance 类型检查 = instanceof"),
                        create_xmind_node("Literal 类型 = enum")
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
                        create_xmind_node("HookRegistry 是事件总线"),
                        create_xmind_node("回调按事件类型分组"),
                        create_xmind_node("回调按注册顺序执行")
                    ]
                ),
                create_xmind_node(
                    "责任链模式",
                    [
                        create_xmind_node("Hook 回调链式执行"),
                        create_xmind_node("每个回调可修改上下文"),
                        create_xmind_node("stop=True 中断链路")
                    ]
                ),
                create_xmind_node(
                    "策略模式",
                    [
                        create_xmind_node("PermissionPolicy 可替换"),
                        create_xmind_node("ApprovalProvider 可注入"),
                        create_xmind_node("AuditSink 可注入")
                    ]
                ),
                create_xmind_node(
                    "模板方法",
                    [
                        create_xmind_node("AgentRunner.run 固定流程"),
                        create_xmind_node("四个 Hook 点可扩展"),
                        create_xmind_node("工具执行链路固定")
                    ]
                ),
                create_xmind_node(
                    "工厂模式",
                    [
                        create_xmind_node("build_agent 工厂方法"),
                        create_xmind_node("按 Profile 组装依赖"),
                        create_xmind_node("能力越级检查")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "四个生命周期事件",
                    [
                        create_xmind_node("UserPromptSubmit: 用户问题提交后"),
                        create_xmind_node("PreToolUse: 工具执行前（可阻断）"),
                        create_xmind_node("PostToolUse: 工具执行后（可修改结果）"),
                        create_xmind_node("Stop: Agent 停止前（可追加总结）")
                    ]
                ),
                create_xmind_node(
                    "tool_call_id 强配对",
                    [
                        create_xmind_node("每个 tool_call 必须有且仅有一条 tool 消息"),
                        create_xmind_node("Hook deny 时回填拒绝消息"),
                        create_xmind_node("异常时回填错误消息"),
                        create_xmind_node("OpenAI API 协议要求")
                    ]
                ),
                create_xmind_node(
                    "权限与 Hook 协作",
                    [
                        create_xmind_node("系统 deny 高于 Hook allow"),
                        create_xmind_node("Hook deny 会被尊重"),
                        create_xmind_node("审批在权限层，Hook 在生命周期层")
                    ]
                ),
                create_xmind_node(
                    "Hook 回调契约",
                    [
                        create_xmind_node("只能访问事件对应字段"),
                        create_xmind_node("返回 HookResult 声明影响"),
                        create_xmind_node("不能直接修改 Agent 状态"),
                        create_xmind_node("支持同步和异步回调")
                    ]
                ),
                create_xmind_node(
                    "不可变数据流",
                    [
                        create_xmind_node("HookContext 不可变输入"),
                        create_xmind_node("HookResult 不可变输出"),
                        create_xmind_node("replace() 创建新对象"),
                        create_xmind_node("防止回调间相互影响")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: Hook 和普通回调有什么区别？",
                    [
                        create_xmind_node("A: Hook 有严格的生命周期事件定义"),
                        create_xmind_node("每个事件对应特定的上下文字段"),
                        create_xmind_node("通过返回值声明影响，不直接修改状态"),
                        create_xmind_node("支持同步和异步回调")
                    ]
                ),
                create_xmind_node(
                    "Q2: 为什么需要 tool_call_id 强配对？",
                    [
                        create_xmind_node("A: OpenAI API 协议要求"),
                        create_xmind_node("每个 assistant.tool_calls[i] 必须有对应 tool 消息"),
                        create_xmind_node("Hook deny/异常时也要回填消息"),
                        create_xmind_node("否则 API 400 拒绝请求")
                    ]
                ),
                create_xmind_node(
                    "Q3: Hook 如何阻止工具执行？",
                    [
                        create_xmind_node("A: PreToolUse 回调返回 HookResult(deny=True)"),
                        create_xmind_node("循环会跳过 invoke，直接回填拒绝消息"),
                        create_xmind_node("deny_reason 会进入 tool 消息给模型看")
                    ]
                ),
                create_xmind_node(
                    "Q4: 权限 deny 和 Hook deny 有什么区别？",
                    [
                        create_xmind_node("A: 权限 deny 是系统级决策，优先级最高"),
                        create_xmind_node("Hook deny 是业务逻辑扩展点"),
                        create_xmind_node("权限 deny 后不会触发 PreToolUse"),
                        create_xmind_node("Hook deny 后仍会触发 PostToolUse")
                    ]
                ),
                create_xmind_node(
                    "Q5: 为什么 Hook 要用不可变对象？",
                    [
                        create_xmind_node("A: 防止回调间相互影响"),
                        create_xmind_node("确保每个回调看到一致的上下文"),
                        create_xmind_node("通过 replace() 声明式修改"),
                        create_xmind_node("符合函数式编程原则")
                    ]
                ),
                create_xmind_node(
                    "Q6: Stop Hook 有什么用？",
                    [
                        create_xmind_node("A: 在 Agent 结束前追加总结"),
                        create_xmind_node("可以注入最终上下文消息"),
                        create_xmind_node("用于审计、日志、清理工作"),
                        create_xmind_node("看到完整对话历史")
                    ]
                ),
                create_xmind_node(
                    "Q7: 如何区分同步和异步 Hook？",
                    [
                        create_xmind_node("A: 回调签名决定：def 同步，async def 异步"),
                        create_xmind_node("HookRegistry 自动识别"),
                        create_xmind_node("同步回调直接调用，异步回调用 await"),
                        create_xmind_node("inspect.iscoroutinefunction 判断")
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
    "title": "第 4 章学习导航",
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
output_path = Path(__file__).parent / "ch04_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"✅ XMind 文件已生成: {output_path}")
print(f"   文件大小: {output_path.stat().st_size} 字节")
print(f"   可直接用 XMind 8/2020/2023 打开")
