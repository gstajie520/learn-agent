#!/usr/bin/env python3
"""生成第 3 章 XMind 8/2020+ 格式的脑图文件。

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
    "第 3 章：权限策略系统",
    [
        # 学习路线分支
        create_xmind_node(
            "学习路线（推荐顺序）",
            [
                create_xmind_node(
                    "第一步：理解权限需求（10 分钟）",
                    [
                        create_xmind_node("tests/test_permissions.py"),
                        create_xmind_node("tests/test_ch03_integration.py"),
                        create_xmind_node("理解权限决策过程"),
                        create_xmind_node("工作区边界保护")
                    ]
                ),
                create_xmind_node(
                    "第二步：读权限核心（20 分钟）",
                    [
                        create_xmind_node("core/permissions.py"),
                        create_xmind_node("PermissionPolicy.decide() 方法"),
                        create_xmind_node("规则、审批、审计流程"),
                        create_xmind_node("理解 fail-closed 原则")
                    ]
                ),
                create_xmind_node(
                    "第三步：理解集成点（15 分钟）",
                    [
                        create_xmind_node("core/loop.py - 权限检查点"),
                        create_xmind_node("cli.py - 终端审批适配器"),
                        create_xmind_node("bootstrap.py - 策略装配")
                    ]
                )
            ]
        ),

        # 核心文件清单分支
        create_xmind_node(
            "核心文件清单",
            [
                create_xmind_node(
                    "core/permissions.py（权限策略核心）",
                    [
                        create_xmind_node(
                            "PermissionPolicy 类",
                            [
                                create_xmind_node("decide() 主决策方法"),
                                create_xmind_node("规则评估与合并"),
                                create_xmind_node("工作区边界检查"),
                                create_xmind_node("审批流程收敛")
                            ]
                        ),
                        create_xmind_node(
                            "领域模型",
                            [
                                create_xmind_node("PermissionDecision（决策结果）"),
                                create_xmind_node("PermissionRequest（请求快照）"),
                                create_xmind_node("PermissionRule（不可变规则）"),
                                create_xmind_node("PermissionBehavior（四态行为）")
                            ]
                        ),
                        create_xmind_node(
                            "外部边界",
                            [
                                create_xmind_node("ApprovalProvider（审批接口）"),
                                create_xmind_node("AuditSink（审计接口）"),
                                create_xmind_node("WorkspaceWriteBoundary（边界检查）")
                            ]
                        )
                    ]
                ),
                create_xmind_node(
                    "core/loop.py（集成权限）",
                    [
                        create_xmind_node("AgentRunner 添加 permission_policy"),
                        create_xmind_node("run() 方法中权限检查点"),
                        create_xmind_node("权限评估失败时 fail-closed"),
                        create_xmind_node("保证每个 tool_call 都有配对结果")
                    ]
                ),
                create_xmind_node(
                    "core/filesystem.py（工作区边界）",
                    [
                        create_xmind_node("WorkspaceWriteBoundary 接口"),
                        create_xmind_node("is_path_within_workspace()"),
                        create_xmind_node("路径逃逸检查")
                    ]
                ),
                create_xmind_node(
                    "adapters/filesystem.py（边界实现）",
                    [
                        create_xmind_node("LocalWorkspaceFileSystem"),
                        create_xmind_node("safe_path() 函数"),
                        create_xmind_node("符号链接和绝对路径拒绝"),
                        create_xmind_node("Windows 保留名检查")
                    ]
                ),
                create_xmind_node(
                    "cli.py（终端适配器）",
                    [
                        create_xmind_node("TerminalApprovalProvider"),
                        create_xmind_node("TerminalAuditSink"),
                        create_xmind_node("交互式 y/N 确认"),
                        create_xmind_node("stderr 审计日志")
                    ]
                ),
                create_xmind_node(
                    "bootstrap.py（策略装配）",
                    [
                        create_xmind_node("P03 章节配置"),
                        create_xmind_node("confirm-file-write 规则"),
                        create_xmind_node("必需审批器和审计器"),
                        create_xmind_node("PermissionPolicy 构造")
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
                        create_xmind_node("PermissionPolicy = 策略模式 + 责任链"),
                        create_xmind_node("ApprovalProvider = 策略接口"),
                        create_xmind_node("AuditSink = 观察者接口"),
                        create_xmind_node("PermissionRule = 不可变规则对象")
                    ]
                ),
                create_xmind_node(
                    "类型系统对照",
                    [
                        create_xmind_node("Literal['allow', 'deny', ...] = 枚举"),
                        create_xmind_node("Callable[[Request], bool] = Predicate<Request>"),
                        create_xmind_node("Protocol = interface"),
                        create_xmind_node("frozenset = Collections.unmodifiableSet")
                    ]
                ),
                create_xmind_node(
                    "异常处理对照",
                    [
                        create_xmind_node("PermissionContractError = 契约异常"),
                        create_xmind_node("except Exception: 默认拒绝 = fail-closed"),
                        create_xmind_node("审批器异常时统一处理")
                    ]
                ),
                create_xmind_node(
                    "依赖注入对照",
                    [
                        create_xmind_node("构造器注入规则列表"),
                        create_xmind_node("可选依赖：approval/audit"),
                        create_xmind_node("接口隔离：只依赖 Protocol")
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
                        create_xmind_node("PermissionPolicy 可替换"),
                        create_xmind_node("ApprovalProvider 策略接口"),
                        create_xmind_node("AuditSink 可选注入")
                    ]
                ),
                create_xmind_node(
                    "责任链模式",
                    [
                        create_xmind_node("边界检查 → 默认策略 → 规则评估 → 审批"),
                        create_xmind_node("每个环节产生候选决策"),
                        create_xmind_node("_strongest() 合并冲突")
                    ]
                ),
                create_xmind_node(
                    "适配器模式",
                    [
                        create_xmind_node("TerminalApprovalProvider 适配终端"),
                        create_xmind_node("TerminalAuditSink 适配 stderr"),
                        create_xmind_node("未来可替换为 Web/RPC 实现")
                    ]
                ),
                create_xmind_node(
                    "不可变对象",
                    [
                        create_xmind_node("PermissionDecision frozen=True"),
                        create_xmind_node("PermissionRequest 快照"),
                        create_xmind_node("PermissionRule 不可变")
                    ]
                )
            ]
        ),

        # 关键概念理解分支
        create_xmind_node(
            "关键概念理解",
            [
                create_xmind_node(
                    "四态权限行为",
                    [
                        create_xmind_node("allow：明确允许执行"),
                        create_xmind_node("deny：明确拒绝执行"),
                        create_xmind_node("ask：需要审批收敛"),
                        create_xmind_node("passthrough：没有规则参与")
                    ]
                ),
                create_xmind_node(
                    "fail-closed 原则",
                    [
                        create_xmind_node("审批器异常时默认拒绝"),
                        create_xmind_node("权限评估异常时默认拒绝"),
                        create_xmind_node("安全优先于可用性")
                    ]
                ),
                create_xmind_node(
                    "工作区边界保护",
                    [
                        create_xmind_node("拒绝绝对路径和父目录片段"),
                        create_xmind_node("拒绝符号链接逃逸"),
                        create_xmind_node("拒绝 Windows 保留名"),
                        create_xmind_node("边界 deny 不能被 allow 覆盖")
                    ]
                ),
                create_xmind_node(
                    "决策合并策略",
                    [
                        create_xmind_node("deny > ask > allow 优先级"),
                        create_xmind_node("取最保守候选"),
                        create_xmind_node("passthrough 变 allow")
                    ]
                ),
                create_xmind_node(
                    "审计不可绕过",
                    [
                        create_xmind_node("审计失败时向上抛出"),
                        create_xmind_node("阻止工具执行"),
                        create_xmind_node("保证所有决定都记录")
                    ]
                )
            ]
        ),

        # 面试题速查分支
        create_xmind_node(
            "面试题速查",
            [
                create_xmind_node(
                    "Q1: 为什么需要权限策略？",
                    [
                        create_xmind_node("A: shell 和文件工具可能破坏系统"),
                        create_xmind_node("需要人工审批高风险操作"),
                        create_xmind_node("审计记录用于事后追溯")
                    ]
                ),
                create_xmind_node(
                    "Q2: 四态权限行为如何收敛？",
                    [
                        create_xmind_node("A: ask 交给 ApprovalProvider 收敛"),
                        create_xmind_node("passthrough 变为 allow（默认放行）"),
                        create_xmind_node("allow/deny 是最终决定")
                    ]
                ),
                create_xmind_node(
                    "Q3: 什么是 fail-closed 原则？",
                    [
                        create_xmind_node("A: 权限系统故障时默认拒绝"),
                        create_xmind_node("审批器抛异常返回 deny"),
                        create_xmind_node("安全优先于可用性")
                    ]
                ),
                create_xmind_node(
                    "Q4: 工作区边界如何保护？",
                    [
                        create_xmind_node("A: 拒绝绝对路径和 .. 片段"),
                        create_xmind_node("解析真实路径检查是否逃逸"),
                        create_xmind_node("符号链接也不能指向工作区外")
                    ]
                ),
                create_xmind_node(
                    "Q5: 决策冲突时如何合并？",
                    [
                        create_xmind_node("A: _strongest() 选最保守候选"),
                        create_xmind_node("优先级: deny > ask > allow"),
                        create_xmind_node("边界 deny 不能被覆盖")
                    ]
                ),
                create_xmind_node(
                    "Q6: 审计失败会怎样？",
                    [
                        create_xmind_node("A: 向上抛异常，阻止工具执行"),
                        create_xmind_node("不能让决定未记录就执行"),
                        create_xmind_node("保证审计日志完整性")
                    ]
                ),
                create_xmind_node(
                    "Q7: 为什么 PermissionRequest 要快照？",
                    [
                        create_xmind_node("A: 规则和审批器是外部代码"),
                        create_xmind_node("防止修改影响后续评估"),
                        create_xmind_node("frozen=True 保证不可变")
                    ]
                ),
                create_xmind_node(
                    "Q8: 权限层在 Agent Loop 哪个位置？",
                    [
                        create_xmind_node("A: prepare() 之后、invoke() 之前"),
                        create_xmind_node("工具参数已校验，但未执行"),
                        create_xmind_node("拒绝时仍要生成配对 tool 消息")
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
    "title": "第 3 章学习导航",
    "rootTopic": root_node
}]

# 构建 metadata.json
metadata = {
    "creator": {
        "name": "Agent Learning System",
        "version": "3.0"
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
output_path = Path(__file__).parent / "ch03_learning_roadmap.xmind"

with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as xmind_file:
    xmind_file.writestr('content.json', json.dumps(content, ensure_ascii=False, indent=2))
    xmind_file.writestr('metadata.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    xmind_file.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))

print(f"[OK] XMind 文件已生成: {output_path}")
print(f"   文件大小: {output_path.stat().st_size} 字节")
print(f"   可直接用 XMind 8/2020/2023 打开")
