"""第 16 章结构化协作协议：计划审批与优雅关机。

Java 类比：``ProtocolStore`` 是协议 Repository，``ProtocolRuntime`` 是领域 Service。
请求先保存为 pending，再投递 typed Mailbox；审批或关机完成后保存唯一 resolution。
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from ..core.permissions import PermissionRequest, PermissionRule
from ..core.tools import ToolContext, ToolDefinition, ToolResult, tool_error, tool_success
from .mailbox import (
    LEAD_NAME,
    MailboxStore,
    ProtocolMailboxMessage,
    ProtocolMessageKind,
    canonical_agent_name,
    canonical_message_id,
)

ProtocolRequestKind = Literal["shutdown", "plan_approval"]
ProtocolRequestStatus = Literal["pending", "approved", "rejected"]


class ProtocolError(Exception):
    """协议领域异常，携带稳定 error_code。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ProtocolNotFoundError(ProtocolError):
    """请求不存在。"""

    def __init__(self, message: str) -> None:
        super().__init__("protocol_not_found", message)


class ProtocolStateError(ProtocolError):
    """请求状态或队友状态不允许当前操作。"""

    def __init__(self, message: str) -> None:
        super().__init__("protocol_state_error", message)


class ProtocolMismatchError(ProtocolError):
    """请求与传输消息字段不匹配。"""

    def __init__(self, message: str) -> None:
        super().__init__("protocol_mismatch", message)


class ProtocolExpiredError(ProtocolError):
    """pending 请求已超过有效期。"""

    def __init__(self, message: str) -> None:
        super().__init__("protocol_expired", message)


class ProtocolDeliveryError(ProtocolError):
    """请求已保存但 typed 消息投递失败。"""

    def __init__(self, message: str) -> None:
        super().__init__("protocol_delivery_error", message)


@dataclass(frozen=True, slots=True)
class ProtocolResolution:
    """终态 resolution，记录唯一响应消息和结构化结论。"""

    message_id: str  # 完成审批的响应消息 UUID。
    approved: bool  # 唯一机器可读审批结论。
    content: str  # 审批反馈或关闭确认正文。
    resolved_at_utc: dt.datetime  # 状态迁移到终态的时间。


@dataclass(frozen=True, slots=True)
class ProtocolRequest:
    """持久协议请求快照。"""

    id: str  # 请求主键，同时写入对应 typed Mailbox 消息的 request_id。
    kind: ProtocolRequestKind  # shutdown 或 plan_approval。
    sender: str  # 发起方；shutdown 为 lead，plan 为队友。
    target: str  # 接收方。
    status: ProtocolRequestStatus  # pending/approved/rejected。
    content: str  # 必须和请求消息正文一致。
    created_at_utc: dt.datetime  # 创建顺序。
    expires_at_utc: dt.datetime  # pending 有效截止时间。
    resolution: ProtocolResolution | None = None  # 终态唯一 resolution。


class ProtocolStore(Protocol):
    """协议 Repository 接口。"""

    def create_request(
        self, kind: ProtocolRequestKind, sender: str, target: str, content: str
    ) -> ProtocolRequest: ...
    def get_request(self, request_id: str) -> ProtocolRequest: ...
    def get_pending_request(self, request_id: str) -> ProtocolRequest: ...
    def list_requests(self) -> tuple[ProtocolRequest, ...]: ...
    def latest_plan_request(self, sender: str) -> ProtocolRequest | None: ...
    def validate_message(
        self, message: ProtocolMailboxMessage, response: bool
    ) -> ProtocolRequest: ...
    def consume_response(self, message: ProtocolMailboxMessage) -> ProtocolRequest: ...


class JsonProtocolStore:
    """将协议请求保存到 `.agent_tutorial/protocol/state.json`。"""

    def __init__(
        self, workspace: str, *, id_generator=None, clock=None, ttl_ms: int = 300_000
    ) -> None:  # type: ignore[no-untyped-def]
        self.path = (
            Path(workspace).resolve() / ".agent_tutorial" / "protocol" / "state.json"
        )  # 单一快照文件。
        self._id_generator = id_generator or (lambda: str(uuid.uuid4()))
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._ttl = dt.timedelta(milliseconds=ttl_ms)

    def _load(self) -> list[ProtocolRequest]:
        """严格读取快照；不存在时返回空列表。"""
        if not self.path.exists():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (
                not isinstance(value, dict)
                or set(value) != {"version", "requests"}
                or value["version"] != 1
            ):
                raise ValueError("state version invalid")
            return [self._parse(item) for item in value["requests"]]
        except Exception as error:
            raise ProtocolError("protocol_storage_error", "协议状态文件无效") from error

    def _save(self, requests: list[ProtocolRequest]) -> None:
        """临时文件 + fsync + replace 持久化完整快照。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "requests": [self._json(item) for item in requests]}
        temporary = self.path.with_suffix(f".{uuid.uuid4()}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
        temporary.replace(self.path)

    def create_request(
        self, kind: ProtocolRequestKind, sender: str, target: str, content: str
    ) -> ProtocolRequest:
        """先写 pending 请求，再由 Runtime 负责发送消息。"""
        requests = self._load()
        now = self._now()
        request = ProtocolRequest(
            canonical_message_id(self._id_generator()),
            kind,
            canonical_agent_name(sender),
            canonical_agent_name(target),
            "pending",
            content,
            now,
            now + self._ttl,
        )
        if any(item.id == request.id for item in requests):
            raise ProtocolError("protocol_storage_error", "协议请求 ID 已存在")
        requests.append(request)
        self._save(requests)
        return request

    def get_request(self, request_id: str) -> ProtocolRequest:
        """读取任意状态请求。"""
        return self._find(request_id)

    def get_pending_request(self, request_id: str) -> ProtocolRequest:
        """读取仍可审批的 pending 请求。"""
        request = self._find(request_id)
        self._require_current(request)
        return request

    def list_requests(self) -> tuple[ProtocolRequest, ...]:
        """返回创建顺序快照。"""
        return tuple(self._load())

    def latest_plan_request(self, sender: str) -> ProtocolRequest | None:
        """返回指定队友最后一次计划请求。"""
        name = canonical_agent_name(sender)
        items = [
            item for item in self._load() if item.kind == "plan_approval" and item.sender == name
        ]
        return items[-1] if items else None

    def validate_message(self, message: ProtocolMailboxMessage, response: bool) -> ProtocolRequest:
        """只读验证 typed 消息和请求的一致性。"""
        request = self._find(message.request_id)
        self._validate_message(request, message, response)
        return request

    def consume_response(self, message: ProtocolMailboxMessage) -> ProtocolRequest:
        """原子把 pending 迁移到 approved/rejected；同一响应重试幂等。"""
        requests = self._load()
        request = next((item for item in requests if item.id == message.request_id), None)
        if request is None:
            raise ProtocolNotFoundError(f"找不到协议请求: {message.request_id}")
        if request.status != "pending":
            if request.resolution is not None and request.resolution.message_id == message.id:
                return request
            raise ProtocolStateError(f"协议请求已经完成: {request.id}")
        self._require_current(request)
        self._validate_message(request, message, True)
        assert isinstance(message.approved, bool)
        updated = ProtocolRequest(
            request.id,
            request.kind,
            request.sender,
            request.target,
            "approved" if message.approved else "rejected",
            request.content,
            request.created_at_utc,
            request.expires_at_utc,
            ProtocolResolution(message.id, message.approved, message.content, self._now()),
        )
        self._save([updated if item.id == request.id else item for item in requests])
        return updated

    def _find(self, request_id: str) -> ProtocolRequest:
        normalized = canonical_message_id(request_id)
        for item in self._load():
            if item.id == normalized:
                return item
        raise ProtocolNotFoundError(f"找不到协议请求: {normalized}")

    def _now(self) -> dt.datetime:
        value = self._clock().astimezone(dt.UTC)
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)

    def _require_current(self, request: ProtocolRequest) -> None:
        if request.status != "pending":
            raise ProtocolStateError(f"协议请求已经完成: {request.id}")
        if self._now() >= request.expires_at_utc:
            raise ProtocolExpiredError(f"协议请求已过期: {request.id}")

    @staticmethod
    def _validate_message(
        request: ProtocolRequest, message: ProtocolMailboxMessage, response: bool
    ) -> None:
        expected_kind = (
            ("shutdown_response" if request.kind == "shutdown" else "plan_approval_response")
            if response
            else ("shutdown_request" if request.kind == "shutdown" else "plan_approval_request")
        )
        expected_sender = request.target if response else request.sender
        expected_recipient = request.sender if response else request.target
        if (
            message.kind != expected_kind
            or message.sender != expected_sender
            or message.recipient != expected_recipient
            or message.content == ""
        ):
            raise ProtocolMismatchError("协议消息与请求不匹配")
        if not response and message.content != request.content:
            raise ProtocolMismatchError("协议请求正文不匹配")

    @staticmethod
    def _json(request: ProtocolRequest) -> dict[str, object]:
        return {
            "id": request.id,
            "kind": request.kind,
            "sender": request.sender,
            "target": request.target,
            "status": request.status,
            "content": request.content,
            "created_at_utc": request.created_at_utc.isoformat().replace("+00:00", "Z"),
            "expires_at_utc": request.expires_at_utc.isoformat().replace("+00:00", "Z"),
            "resolution": None
            if request.resolution is None
            else {
                "message_id": request.resolution.message_id,
                "approved": request.resolution.approved,
                "content": request.resolution.content,
                "resolved_at_utc": request.resolution.resolved_at_utc.isoformat().replace(
                    "+00:00", "Z"
                ),
            },
        }

    @staticmethod
    def _parse(value: object) -> ProtocolRequest:
        if not isinstance(value, dict):
            raise TypeError("request must be object")
        parse_time = lambda raw: dt.datetime.fromisoformat(str(raw))
        resolution = value["resolution"]
        parsed_resolution = (
            None
            if resolution is None
            else ProtocolResolution(
                str(resolution["message_id"]),
                bool(resolution["approved"]),
                str(resolution["content"]),
                parse_time(resolution["resolved_at_utc"]),
            )
        )
        return ProtocolRequest(
            str(value["id"]),
            value["kind"],
            str(value["sender"]),
            str(value["target"]),
            value["status"],
            str(value["content"]),
            parse_time(value["created_at_utc"]),
            parse_time(value["expires_at_utc"]),
            parsed_resolution,
        )


class ProtocolTeamHost(Protocol):
    """协议运行时所需的最小队友宿主接口。"""

    @property
    def mailbox_store(self) -> MailboxStore: ...

    def state(self, name: str): ...
    def begin_shutdown(self, name: str) -> None: ...
    def deliver_protocol(
        self,
        sender: str,
        recipient: str,
        content: str,
        kind: ProtocolMessageKind,
        *,
        request_id: str,
        approved: bool | None,
    ) -> ProtocolMailboxMessage: ...


class ProtocolRuntime:
    """编排计划审批、优雅关机和队友副作用门禁。"""

    def __init__(
        self, store: ProtocolStore, team: ProtocolTeamHost, *, lead_name: str = LEAD_NAME
    ) -> None:
        self.store = store  # 协议状态 Repository。
        self.team = team  # 共享 TeammateRuntime。
        self.lead_name = canonical_agent_name(lead_name)
        self.plan_gate_rule = PermissionRule(
            "plan-approval-gate", "deny", "副作用工具需要最新计划通过审批", self._requires_plan
        )

    def plan_allows_effectful(self, sender: str) -> bool:
        """没有计划时放行；最新计划只有 approved 才放行。"""
        latest = self.store.latest_plan_request(canonical_agent_name(sender))
        return latest is None or latest.status == "approved"

    def request_shutdown(self, teammate: str) -> ProtocolRequest:
        """Lead 发起优雅关机请求。"""
        name = canonical_agent_name(teammate)
        request = self.store.create_request(
            "shutdown", self.lead_name, name, "Graceful shutdown requested."
        )
        self._deliver(self.lead_name, name, request.content, "shutdown_request", request.id, None)
        return request

    def submit_plan(self, sender: str, plan: str) -> ProtocolRequest:
        """队友提交待审批计划。"""
        sender = canonical_agent_name(sender)
        request = self.store.create_request("plan_approval", sender, self.lead_name, plan)
        self._deliver(sender, self.lead_name, plan, "plan_approval_request", request.id, None)
        return request

    def review_plan(
        self, request_id: str, approve: bool, feedback: str = ""
    ) -> ProtocolMailboxMessage:
        """Lead 使用 request_id 做结构化审批，并发送响应。"""
        request = self.store.get_pending_request(request_id)
        if request.kind != "plan_approval" or request.target != self.lead_name:
            raise ProtocolMismatchError("请求不是 Lead 计划审批")
        return self._deliver(
            self.lead_name,
            request.sender,
            feedback.strip() or ("Approved" if approve else "Rejected"),
            "plan_approval_response",
            request.id,
            approve,
        )

    def route_teammate_message(
        self, teammate: str, message: ProtocolMailboxMessage
    ) -> tuple[str | None, bool]:
        """队友处理协议消息；shutdown 不调用模型，plan response 生成恢复提示。"""
        if message.kind == "shutdown_request":
            request = self.store.validate_message(message, False)
            self.team.begin_shutdown(teammate)
            self._deliver(
                teammate,
                self.lead_name,
                "Ready to shut down.",
                "shutdown_response",
                request.id,
                True,
            )
            return None, True
        if message.kind == "plan_approval_response":
            request = self.store.consume_response(message)
            prompt = f"Plan {'approved' if request.status == 'approved' else 'rejected'} ({request.id}). {message.content}"
            return prompt, False
        raise ProtocolMismatchError("协议消息不能路由给队友")

    def validate_lead_message(self, message: ProtocolMailboxMessage) -> ProtocolRequest:
        """Lead 事件进入历史前只读校验。"""
        return self.store.validate_message(message, message.kind == "shutdown_response")

    def acknowledge_lead_message(self, message: ProtocolMailboxMessage) -> ProtocolRequest:
        """Lead ack 阶段消费响应，保证状态迁移只发生一次。"""
        if message.kind == "shutdown_response":
            return self.store.consume_response(message)
        return self.store.validate_message(message, False)

    def _deliver(
        self,
        sender: str,
        recipient: str,
        content: str,
        kind: ProtocolMessageKind,
        request_id: str,
        approved: bool | None,
    ) -> ProtocolMailboxMessage:
        try:
            return self.team.deliver_protocol(
                sender, recipient, content, kind, request_id=request_id, approved=approved
            )
        except ProtocolError:
            raise
        except Exception as error:
            raise ProtocolDeliveryError("协议消息投递失败") from error

    def _requires_plan(self, request: PermissionRequest) -> bool:
        """只拦截 effectful 工具；读、send_message、submit_plan 永远可用。"""
        definition = request.prepared.definition
        if definition is None:
            raise ProtocolStateError("计划门禁丢失工具定义")
        if definition.effect == "read" or definition.name in {"send_message", "submit_plan"}:
            return False
        return not self.plan_allows_effectful(request.context.identity)

    def lead_tool_definitions(self) -> tuple[ToolDefinition, ToolDefinition]:
        """返回 Lead 的 request_shutdown/review_plan 工具。"""

        def shutdown(arguments, _context: ToolContext) -> ToolResult:  # type: ignore[no-untyped-def]
            try:
                return tool_success(
                    json.dumps(
                        asdict(self.request_shutdown(str(arguments["teammate"]))),
                        ensure_ascii=False,
                        default=str,
                    )
                )
            except ProtocolError as error:
                return tool_error(error.error_code, str(error))

        def review(arguments, _context: ToolContext) -> ToolResult:  # type: ignore[no-untyped-def]
            try:
                response = self.review_plan(
                    str(arguments["request_id"]),
                    bool(arguments["approve"]),
                    str(arguments.get("feedback", "")),
                )
                return tool_success(json.dumps(response.to_payload(), ensure_ascii=False))
            except ProtocolError as error:
                return tool_error(error.error_code, str(error))

        return (
            ToolDefinition(
                "request_shutdown",
                "请求队友优雅关闭",
                {
                    "type": "object",
                    "properties": {"teammate": {"type": "string"}},
                    "required": ["teammate"],
                    "additionalProperties": False,
                },
                "external",
                shutdown,
            ),
            ToolDefinition(
                "review_plan",
                "审批队友提交的计划",
                {
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "approve": {"type": "boolean"},
                        "feedback": {"type": "string"},
                    },
                    "required": ["request_id", "approve"],
                    "additionalProperties": False,
                },
                "external",
                review,
            ),
        )

    @property
    def submit_plan_tool_definition(self) -> ToolDefinition:
        """返回仅供队友使用的 submit_plan 工具。"""

        def submit(arguments, context: ToolContext) -> ToolResult:  # type: ignore[no-untyped-def]
            try:
                return tool_success(
                    json.dumps(
                        asdict(self.submit_plan(context.identity, str(arguments["plan"]))),
                        ensure_ascii=False,
                        default=str,
                    )
                )
            except ProtocolError as error:
                return tool_error(error.error_code, str(error))

        return ToolDefinition(
            "submit_plan",
            "向 Lead 提交待审批计划",
            {
                "type": "object",
                "properties": {"plan": {"type": "string"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            "external",
            submit,
        )
