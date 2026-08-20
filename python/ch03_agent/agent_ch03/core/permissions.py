"""权限策略领域模型。

Java 对照：这里相当于一个独立的 Policy Service 模块，包含不可变 DTO、
规则对象以及可注入的审批/审计接口。它不直接执行工具，只负责回答“能不能执行”。
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from .filesystem import WorkspaceWriteBoundary
from .tools import PreparedToolCall, ToolContext, ToolResult, tool_error

PermissionBehavior = Literal["allow", "deny", "ask", "passthrough"]
PERMISSION_BEHAVIORS: tuple[PermissionBehavior, ...] = ("allow", "deny", "ask", "passthrough")


class PermissionContractError(Exception):
    """权限请求、规则或决策违反领域契约。"""


def _is_behavior(value: object) -> bool:
    return value in PERMISSION_BEHAVIORS


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """一次权限结论：行为、解释原因和决策来源。"""

    behavior: PermissionBehavior  # 四态行为；最终只有 allow/deny 可执行或回填。
    reason: str  # 给用户、模型和审计记录看的非空解释。
    source: str  # 规则、审批器、工作区边界或默认策略的来源名。

    def __post_init__(self) -> None:
        if not _is_behavior(self.behavior):
            raise PermissionContractError("behavior 必须是受支持的权限行为")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise PermissionContractError("权限决策原因不能为空")
        if not isinstance(self.source, str) or not self.source.strip():
            raise PermissionContractError("权限决策来源不能为空")

    @property
    def is_allowed(self) -> bool:
        """只有最终 allow 才允许工具进入 invoke。"""
        return self.behavior == "allow"

    def to_tool_result(self) -> ToolResult:
        """把最终 deny 转成模型可见错误；ask/passthrough 不能直接转换。"""
        if self.behavior != "deny":
            raise PermissionContractError("只有最终 deny 决策才能转换成工具结果")
        return tool_error("permission_denied", self.reason)


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    """权限策略输入快照，必须包含已经通过工具参数校验的调用。"""

    prepared: PreparedToolCall  # prepare 成功的工具调用，权限层不修复坏参数。
    context: ToolContext  # 工作区和调用身份边界。
    recommendations: tuple[PermissionDecision, ...] = ()  # 上游 hook 提供的候选建议。
    proposed_decision: PermissionDecision | None = None  # 交给审批器确认的 ask 决策。

    def __post_init__(self) -> None:
        if self.prepared.error is not None or self.prepared.definition is None or self.prepared.arguments is None:
            raise PermissionContractError("权限请求必须包含准备完成的工具调用")
        if not isinstance(self.recommendations, tuple) or not all(isinstance(item, PermissionDecision) for item in self.recommendations):
            raise PermissionContractError("recommendations 必须全部是 PermissionDecision")
        if self.proposed_decision is not None and (not isinstance(self.proposed_decision, PermissionDecision) or self.proposed_decision.behavior != "ask"):
            raise PermissionContractError("proposed_decision 必须是 ask 决策")


PermissionMatcher = Callable[[PermissionRequest], bool]


@dataclass(frozen=True, slots=True)
class PermissionRule:
    """把匹配条件、行为和解释原因绑定在一起的不可变规则。"""

    name: str  # 审计和决策 source 使用的稳定规则名。
    behavior: PermissionBehavior  # 匹配成功时提出的候选行为。
    reason: str  # 规则为什么提出这个行为。
    matches: PermissionMatcher  # 类似 Java Predicate<PermissionRequest>。

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.reason.strip() or not callable(self.matches) or not _is_behavior(self.behavior):
            raise PermissionContractError("权限规则字段不合法")

    def evaluate(self, request: PermissionRequest) -> PermissionDecision | None:
        """匹配成功返回带来源的候选决策，不匹配返回 None。"""
        if not self.matches(request):
            return None
        return PermissionDecision(self.behavior, self.reason, self.name)


class ApprovalProvider(Protocol):
    """审批边界，类似 Java 的 ApprovalProvider interface。"""

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """把 ask 收敛成明确 allow 或 deny。"""


class AuditSink(Protocol):
    """审计边界，最终决策记录失败时阻止工具执行。"""

    def record(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        """记录一次最终权限决定。"""


def _strongest(decisions: Sequence[PermissionDecision]) -> PermissionDecision:
    """冲突时按 deny > ask > allow 选择最保守候选。"""
    for behavior in ("deny", "ask", "allow"):
        for decision in decisions:
            if decision.behavior == behavior:
                return decision
    return PermissionDecision("passthrough", "没有权限参与方阻止请求", "default")


def _approval_denial(proposed: PermissionDecision) -> PermissionDecision:
    return PermissionDecision("deny", f"审批没有明确同意: {proposed.reason}", "approval")


class PermissionPolicy:
    """在工具 handler 之前合并工作区边界、默认策略、规则、审批和审计。"""

    def __init__(
        self,
        rules: Sequence[PermissionRule] = (),
        approval: ApprovalProvider | None = None,
        audit: AuditSink | None = None,
        write_boundary: WorkspaceWriteBoundary | None = None,
    ) -> None:
        if not all(isinstance(rule, PermissionRule) for rule in rules):
            raise PermissionContractError("rules 必须全部是 PermissionRule")
        self._rules = tuple(rules)  # 不可变规则快照，类似 Java List.copyOf。
        self._approval = approval  # ask 的外部审批器。
        self._audit = audit  # 最终决定的审计接收器。
        self._write_boundary = write_boundary  # 写路径真实边界检查。

    def decide(self, request: PermissionRequest) -> PermissionDecision:
        """计算唯一最终决定；审计失败会抛出并阻止副作用。"""
        candidates: list[PermissionDecision] = []
        boundary = self._workspace_boundary_decision(request)
        if boundary is not None:
            candidates.append(boundary)
        definition = request.prepared.definition
        if definition is None:
            raise PermissionContractError("权限请求丢失工具定义")
        if definition.effect == "execute":
            candidates.append(PermissionDecision("ask", "执行 PowerShell 命令需要审批", "shell-default"))
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

    def _resolve_approval(self, request: PermissionRequest, proposed: PermissionDecision) -> PermissionDecision:
        """审批缺失、异常、无效或返回中间态时统一拒绝。"""
        if self._approval is None:
            return _approval_denial(proposed)
        approval_request = PermissionRequest(request.prepared, request.context, request.recommendations, proposed)
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
        raw_path = arguments.get("path") if isinstance(arguments, dict) else None
        if raw_path is None or self._write_boundary is None:
            return None
        if not isinstance(raw_path, str):
            return PermissionDecision("deny", "写入路径无效", "workspace-boundary")
        try:
            allowed = self._write_boundary.is_path_within_workspace(request.context.workspace, raw_path)
            if not isinstance(allowed, bool):
                raise PermissionContractError("写路径边界必须返回 bool")
        except Exception:  # noqa: BLE001
            return PermissionDecision("deny", "无法安全解析写入路径", "workspace-boundary")
        if not allowed:
            return PermissionDecision("deny", "禁止写入工作区之外", "workspace-boundary")
        return None
