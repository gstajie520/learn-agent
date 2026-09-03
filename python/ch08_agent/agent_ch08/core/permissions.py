“””权限策略领域模型。

这是什么：实现工具调用权限控制的核心模块
Java 类比：类似 PolicyService + PermissionRule + ApprovalProvider 的组合
为什么需要：在工具执行前进行权限检查，支持规则、审批和审计的可插拔策略

Java 对照：这里相当于一个独立的 Policy Service 模块，包含不可变 DTO、
规则对象以及可注入的审批/审计接口。它不直接执行工具，只负责回答”能不能执行”。
“””

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from .filesystem import WorkspaceWriteBoundary
from .tools import PreparedToolCall, ToolContext, ToolResult, tool_error

PermissionBehavior = Literal["allow", "deny", "ask", "passthrough"]
PERMISSION_BEHAVIORS: tuple[PermissionBehavior, ...] = ("allow", "deny", "ask", "passthrough")


class PermissionContractError(Exception):
    """权限请求、规则或决策违反领域契约。

    这是什么：表示权限协议违反的异常
    Java 类比：类似 PermissionValidationException
    为什么需要：区分权限逻辑错误和其他运行时错误，确保权限系统的健壮性
    """


def _is_behavior(value: object) -> bool:
    """检查值是否是有效的权限行为。

    这是什么：权限行为枚举值的验证函数
    Java 类比：类似 EnumValidator.isValid(value, PermissionBehavior.class)
    为什么需要：运行时验证权限行为的合法性，防止非法值进入系统
    """
    return value in PERMISSION_BEHAVIORS


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """一次权限结论：行为、解释原因和决策来源。

    这是什么：封装权限决策结果的值对象
    Java 类比：类似 record PermissionDecision(Behavior behavior, String reason, String source)
    为什么需要：提供类型安全的权限决策表示，记录决策依据便于审计
    """

    behavior: PermissionBehavior  # 四态行为；最终只有 allow/deny 可执行或回填。
    reason: str  # 给用户、模型和审计记录看的非空解释。
    source: str  # 规则、审批器、工作区边界或默认策略的来源名。

    def __post_init__(self) -> None:
        """验证决策字段的合法性。

        这是什么：构造后的字段校验
        Java 类比：类似 compact constructor 中的参数验证
        为什么需要：确保每个决策都有明确的行为、原因和来源
        """
        if not _is_behavior(self.behavior):
            raise PermissionContractError("behavior 必须是受支持的权限行为")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise PermissionContractError("权限决策原因不能为空")
        if not isinstance(self.source, str) or not self.source.strip():
            raise PermissionContractError("权限决策来源不能为空")

    @property
    def is_allowed(self) -> bool:
        """只有最终 allow 才允许工具进入 invoke。

        这是什么：判断是否允许执行的属性方法
        Java 类比：类似 boolean isAllowed() { return behavior == ALLOW; }
        为什么需要：提供便捷的判断接口，避免调用方直接比较字符串
        """
        return self.behavior == "allow"

    def to_tool_result(self) -> ToolResult:
        """把最终 deny 转成模型可见错误；ask/passthrough 不能直接转换。

        这是什么：将拒绝决策转换为工具错误结果
        Java 类比：类似 ToolResult toToolError() 转换方法
        为什么需要：让权限拒绝能以工具错误的形式返回给模型
        """
        if self.behavior != "deny":
            raise PermissionContractError("只有最终 deny 决策才能转换成工具结果")
        return tool_error("permission_denied", self.reason)


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    """权限策略输入快照，必须包含已经通过工具参数校验的调用。

    这是什么：封装权限检查所需上下文的请求对象
    Java 类比：类似 record PermissionRequest(PreparedToolCall, ToolContext, List<Decision>)
    为什么需要：将工具调用、上下文和推荐决策打包，便于权限策略评估
    """

    prepared: PreparedToolCall  # prepare 成功的工具调用，权限层不修复坏参数。
    context: ToolContext  # 工作区和调用身份边界。
    recommendations: tuple[PermissionDecision, ...] = ()  # 上游 hook 提供的候选建议。
    proposed_decision: PermissionDecision | None = None  # 交给审批器确认的 ask 决策。

    def __post_init__(self) -> None:
        """验证请求包含有效的工具调用和推荐列表。

        这是什么：构造后的完整性校验
        Java 类比：类似 compact constructor 验证必需字段
        为什么需要：确保权限检查不会收到未准备好的工具调用
        """
        if (
            self.prepared.error is not None
            or self.prepared.definition is None
            or self.prepared.arguments is None
        ):
            raise PermissionContractError("权限请求必须包含准备完成的工具调用")
        if not isinstance(self.recommendations, tuple) or not all(
            isinstance(item, PermissionDecision) for item in self.recommendations
        ):
            raise PermissionContractError("recommendations 必须全部是 PermissionDecision")
        if self.proposed_decision is not None and (
            not isinstance(self.proposed_decision, PermissionDecision)
            or self.proposed_decision.behavior != "ask"
        ):
            raise PermissionContractError("proposed_decision 必须是 ask 决策")


PermissionMatcher = Callable[[PermissionRequest], bool]


@dataclass(frozen=True, slots=True)
class PermissionRule:
    """把匹配条件、行为和解释原因绑定在一起的不可变规则。

    这是什么：封装权限规则的值对象
    Java 类比：类似 record PermissionRule(String name, Behavior, String reason, Predicate<Request>)
    为什么需要：将匹配逻辑和决策行为组合成可配置的规则单元
    """

    name: str  # 审计和决策 source 使用的稳定规则名。
    behavior: PermissionBehavior  # 匹配成功时提出的候选行为。
    reason: str  # 规则为什么提出这个行为。
    matches: PermissionMatcher  # 类似 Java Predicate<PermissionRequest>。

    def __post_init__(self) -> None:
        """验证规则的所有字段都有效。

        这是什么：构造后的字段完整性校验
        Java 类比：类似 compact constructor 验证非空和可调用性
        为什么需要：确保每条规则都能正确执行匹配和提供决策
        """
        if (
            not self.name.strip()
            or not self.reason.strip()
            or not callable(self.matches)
            or not _is_behavior(self.behavior)
        ):
            raise PermissionContractError("权限规则字段不合法")

    def evaluate(self, request: PermissionRequest) -> PermissionDecision | None:
        """匹配成功返回带来源的候选决策，不匹配返回 None。

        这是什么：执行规则匹配并返回决策
        Java 类比：类似 Optional<PermissionDecision> evaluate(PermissionRequest)
        为什么需要：让规则能够根据请求判断是否适用并提供决策
        """
        if not self.matches(request):
            return None
        return PermissionDecision(self.behavior, self.reason, self.name)


class ApprovalProvider(Protocol):
    """审批边界，类似 Java 的 ApprovalProvider interface。

    这是什么：定义审批接口的协议
    Java 类比：类似 interface ApprovalProvider { Decision decide(Request); }
    为什么需要：抽象审批实现，支持替换为人工审批、自动审批或测试桩
    """

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """把 ask 收敛成明确 allow 或 deny。

        这是什么：将待审批请求转换为最终决策
        Java 类比：类似 PermissionDecision decide(PermissionRequest)
        为什么需要：将中间态 ask 解析为可执行的 allow 或 deny
        """


class AuditSink(Protocol):
    """审计边界，最终决策记录失败时阻止工具执行。

    这是什么：定义审计接口的协议
    Java 类比：类似 interface AuditSink { void record(Request, Decision); }
    为什么需要：抽象审计实现，支持记录到日志、数据库或测试桩
    """

    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        """记录一次最终权限决定。

        这是什么：记录权限决策的方法
        Java 类比：类似 void record(PermissionRequest, PermissionDecision)
        为什么需要：为合规和审计提供权限决策的完整记录
        """


def _strongest(decisions: Sequence[PermissionDecision]) -> PermissionDecision:
    """冲突时按 deny > ask > allow 选择最保守候选。

    这是什么：从多个决策中选择优先级最高的
    Java 类比：类似 PermissionDecision strongest(List<PermissionDecision>)
    为什么需要：当多条规则匹配时，选择最严格的决策确保安全
    """
    for behavior in ("deny", "ask", "allow"):
        for decision in decisions:
            if decision.behavior == behavior:
                return decision
    return PermissionDecision("passthrough", "没有权限参与方阻止请求", "default")


def _approval_denial(proposed: PermissionDecision) -> PermissionDecision:
    """创建审批拒绝的决策。

    这是什么：生成审批未通过的拒绝决策
    Java 类比：类似 PermissionDecision createApprovalDenial(PermissionDecision)
    为什么需要：统一处理审批失败或未配置的情况
    """
    return PermissionDecision("deny", f"审批没有明确同意: {proposed.reason}", "approval")


class PermissionPolicy:
    """在工具 handler 之前合并工作区边界、默认策略、规则、审批和审计。

    这是什么：权限策略的核心协调类
    Java 类比：类似 PermissionPolicyService 组合多个策略源
    为什么需要：整合边界检查、规则、审批和审计，提供统一的权限决策接口
    """

    def __init__(
        self,
        rules: Sequence[PermissionRule] = (),
        approval: ApprovalProvider | None = None,
        audit: AuditSink | None = None,
        write_boundary: WorkspaceWriteBoundary | None = None,
    ) -> None:
        """初始化权限策略及其依赖。

        这是什么：构造器，注入所有策略组件
        Java 类比：类似 @Autowired 构造器注入依赖
        为什么需要：通过构造器注入保证策略的不可变性和依赖完整性
        """
        if not all(isinstance(rule, PermissionRule) for rule in rules):
            raise PermissionContractError("rules 必须全部是 PermissionRule")
        self._rules = tuple(rules)  # 不可变规则快照，类似 Java List.copyOf。
        self._approval = approval  # ask 的外部审批器。
        self._audit = audit  # 最终决定的审计接收器。
        self._write_boundary = write_boundary  # 写路径真实边界检查。

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """计算唯一最终决定；审计失败会抛出并阻止副作用。

        这是什么：执行完整的权限决策流程
        Java 类比：类似 PermissionDecision decide(PermissionRequest)
        为什么需要：协调边界、规则、审批和审计，返回最终的可执行决策
        """
        candidates: list[PermissionDecision] = []
        boundary = self._workspace_boundary_decision(request)
        if boundary is not None:
            candidates.append(boundary)
        definition = request.prepared.definition
        if definition is None:
            raise PermissionContractError("权限请求丢失工具定义")
        if definition.effect == "execute":
            candidates.append(
                PermissionDecision("ask", "执行 PowerShell 命令需要审批", "shell-default")
            )
        candidates.extend(request.recommendations)
        for rule in self._rules:
            try:
                decision = rule.evaluate(request)
            except Exception:  # noqa: BLE001
                decision = PermissionDecision("deny", f"权限规则执行失败: {rule.name}", rule.name)
            if decision is not None:
                candidates.append(decision)
        proposed = _strongest(candidates)
        if proposed.behavior == "ask":
            final = self._resolve_approval(request, proposed)
        elif proposed.behavior == "passthrough":
            final = PermissionDecision("allow", "没有权限规则阻止请求", "default")
        else:
            final = proposed
        if self._audit is not None:
            self._audit.record(request, final)
        return final

    def _resolve_approval(
        self, request: PermissionRequest, proposed: PermissionDecision
    ) -> PermissionDecision:
        """审批缺失、异常、无效或返回中间态时统一拒绝。"""
        if self._approval is None:
            return _approval_denial(proposed)
        approval_request = PermissionRequest(
            request.prepared, request.context, request.recommendations, proposed
        )
        try:
            decision = self._approval.decide(approval_request)
        except Exception:  # noqa: BLE001
            return PermissionDecision("deny", "审批器发生异常，已拒绝请求", "approval")
        if not isinstance(decision, PermissionDecision):
            return PermissionDecision("deny", "审批器返回了无效决定", "approval")
        if decision.behavior in {"allow", "deny"}:
            return decision
        return _approval_denial(proposed)

    def _workspace_boundary_decision(self, request: PermissionRequest) -> PermissionDecision | None:
        """写工具先检查相对路径；该 deny 不能被 allow、ask 或审批覆盖。"""
        definition = request.prepared.definition
        arguments = request.prepared.arguments
        if definition is None or arguments is None or definition.effect != "write":
            return None
        raw_path = arguments.get("path") if isinstance(arguments, Mapping) else None
        if raw_path is None or self._write_boundary is None:
            return None
        if not isinstance(raw_path, str):
            return PermissionDecision("deny", "写入路径无效", "workspace-boundary")
        try:
            allowed = self._write_boundary.is_path_within_workspace(
                request.context.workspace, raw_path
            )
            if not isinstance(allowed, bool):
                raise PermissionContractError("写路径边界必须返回 bool")
        except Exception:  # noqa: BLE001
            return PermissionDecision("deny", "无法安全解析写入路径", "workspace-boundary")
        if not allowed:
            return PermissionDecision("deny", "禁止写入工作区之外", "workspace-boundary")
        return None
