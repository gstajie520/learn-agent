"""第九章：上下文压缩与大工具结果归档。

Java 对照：
    - ``CompactionManager`` 类似一个 Spring Service，负责把完整会话转换成
      “本次请求要发送给模型的历史”。它不会修改真正的 canonical history。
    - ``ToolResult`` 类似 Service 的返回 DTO；大 DTO 先写入磁盘，消息里只保留引用。
    - ``MessageGroup`` 类似一个不可拆分的事务边界：assistant 的 tool call 和对应的
      tool result 必须一起保留，否则 OpenAI 消息协议会失配。

这一章故意使用 UTF-8 字节数，而不是“Python 字符串长度”。中文一个字符通常占 3 个
字节，直接使用 ``len(text)`` 会低估上下文大小。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..core.messages import (
    AssistantMessage,
    ChatMessage,
    ToolMessage,
    system_message,
    tool_message,
    validate_tool_pairing,
)
from ..core.model import ModelClient, ModelRequest
from ..core.tools import ToolResult, copy_tool_result, tool_error

DEFAULT_PERSIST_THRESHOLD_BYTES = 30_000
DEFAULT_BATCH_BUDGET_BYTES = 200_000
DEFAULT_PREVIEW_HEAD_BYTES = 2_000
DEFAULT_PREVIEW_TAIL_BYTES = 2_000
DEFAULT_KEEP_RECENT_TOOL_GROUPS = 3
DEFAULT_REACTIVE_TAIL_GROUPS = 5
DEFAULT_PROACTIVE_THRESHOLD_BYTES = 50_000
DEFAULT_SNIP_MAX_GROUPS = 50
DEFAULT_SNIP_KEEP_HEAD_GROUPS = 3
COMPACTED_TOOL_RESULT = "[Earlier tool result compacted. Re-run if needed.]"
_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CompactionError(Exception):
    """压缩流程的公共异常基类。"""


class ArtifactPathError(CompactionError):
    """归档目录或归档 ID 不安全。"""


class ArtifactConflictError(CompactionError):
    """归档文件已经存在，拒绝覆盖旧数据。"""


class PromptTooLongRetryError(CompactionError):
    """同一轮 prompt-too-long 恢复窗口内不允许重复压缩。"""


@dataclass(frozen=True, slots=True)
class CompactionSummary:
    """模型生成的结构化摘要。

    Java 对照：这就是一个不可变 record。五个字段分别对应当前目标、关键发现、
    读写文件、剩余工作和用户约束，方便压缩后继续工作。
    """

    current_goal: str
    key_findings: tuple[str, ...]
    files_read_or_changed: tuple[str, ...]
    remaining_work: tuple[str, ...]
    user_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.current_goal.strip():
            raise ValueError("current_goal 不能为空")
        for field_name in ("key_findings", "files_read_or_changed", "remaining_work", "user_constraints"):
            values = getattr(self, field_name)
            if not all(isinstance(value, str) and value.strip() for value in values):
                raise ValueError(f"{field_name} 只能包含非空字符串")


class HistorySummarizer(Protocol):
    """摘要器接口，类似 Java 的 ``HistorySummarizer`` interface。"""

    def summarize(self, history: tuple[ChatMessage, ...]) -> CompactionSummary: ...


class ModelHistorySummarizer:
    """调用模型生成严格五字段 JSON 摘要。"""

    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def summarize(self, history: tuple[ChatMessage, ...]) -> CompactionSummary:
        prompt = (
            "请把当前 Agent 历史压缩成一个 JSON 对象。只能返回 JSON，且只能包含："
            "current_goal、key_findings、files_read_or_changed、remaining_work、user_constraints。"
        )
        request = ModelRequest((system_message(prompt), *history), ())
        reply = self._model.complete(request)
        if reply.finish_reason != "stop" or reply.message.tool_calls:
            raise CompactionError("摘要模型必须 stop 返回，且不能调用工具")
        content = reply.message.content
        if content is None or not content.strip():
            raise CompactionError("摘要模型必须返回非空 JSON")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as error:
            raise CompactionError("摘要模型返回的不是合法 JSON") from error
        expected = {
            "current_goal", "key_findings", "files_read_or_changed", "remaining_work", "user_constraints"
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise CompactionError("摘要 JSON 必须恰好包含五个字段")
        if not isinstance(data["current_goal"], str) or not all(
            isinstance(data[key], list) and all(isinstance(item, str) for item in data[key])
            for key in expected - {"current_goal"}
        ):
            raise CompactionError("摘要 JSON 字段类型不正确")
        return CompactionSummary(
            data["current_goal"],
            tuple(data["key_findings"]),
            tuple(data["files_read_or_changed"]),
            tuple(data["remaining_work"]),
            tuple(data["user_constraints"]),
        )


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """完整归档文件的绝对路径、工作区相对路径和原始字节数。"""

    path: str
    relative_path: str
    original_bytes: int


@dataclass(frozen=True, slots=True)
class ToolResultArtifact:
    """某个工具结果对应的归档引用。"""

    result_index: int
    reference: ArtifactReference


@dataclass(frozen=True, slots=True)
class ToolResultBudgetOutcome:
    """一整轮工具结果压缩后的结果和归档列表。"""

    results: tuple[ToolResult, ...]
    artifacts: tuple[ToolResultArtifact, ...]


@dataclass(frozen=True, slots=True)
class HistoryCompactionOutcome:
    """完整历史被摘要替换后的请求历史和 transcript 引用。"""

    history: tuple[ChatMessage, ...]
    transcript: ArtifactReference


@dataclass(frozen=True, slots=True)
class _MessageGroup:
    messages: tuple[ChatMessage, ...]
    is_tool_exchange: bool


class CompactionManager:
    """上下文压缩总协调器。

    字段说明：
        ``_workspace``：所有 artifact 必须落在这个工作区内。
        ``_summarizer``：生成结构化摘要的模型边界。
        ``_prepared_source/_prepared_history``：上一次压缩缓存，用来避免重复摘要。
        其余字段都是可注入的预算参数，测试时可传入很小的值。
    """

    def __init__(
        self,
        workspace: str,
        summarizer: HistorySummarizer,
        *,
        id_generator: Any | None = None,
        persist_threshold_bytes: int = DEFAULT_PERSIST_THRESHOLD_BYTES,
        batch_budget_bytes: int = DEFAULT_BATCH_BUDGET_BYTES,
        preview_head_bytes: int = DEFAULT_PREVIEW_HEAD_BYTES,
        preview_tail_bytes: int = DEFAULT_PREVIEW_TAIL_BYTES,
        reactive_tail_groups: int = DEFAULT_REACTIVE_TAIL_GROUPS,
        proactive_threshold_bytes: int = DEFAULT_PROACTIVE_THRESHOLD_BYTES,
        snip_max_groups: int = DEFAULT_SNIP_MAX_GROUPS,
        snip_keep_head_groups: int = DEFAULT_SNIP_KEEP_HEAD_GROUPS,
        keep_recent_tool_groups: int = DEFAULT_KEEP_RECENT_TOOL_GROUPS,
    ) -> None:
        if persist_threshold_bytes <= 0 or batch_budget_bytes <= 0:
            raise ValueError("字节预算必须是正整数")
        if preview_head_bytes < 0 or preview_tail_bytes < 0 or preview_head_bytes + preview_tail_bytes == 0:
            raise ValueError("预览至少需要保留头部或尾部字节")
        if reactive_tail_groups <= 0 or proactive_threshold_bytes <= 0:
            raise ValueError("压缩窗口参数必须是正整数")
        if snip_max_groups < 3 or not 0 < snip_keep_head_groups < snip_max_groups:
            raise ValueError("snip 参数不合法")
        if keep_recent_tool_groups < 0:
            raise ValueError("keep_recent_tool_groups 不能为负数")
        raw_workspace = Path(workspace)
        if not raw_workspace.exists() or not raw_workspace.is_dir():
            raise ArtifactPathError("workspace 必须是已经存在的目录")
        self._workspace = raw_workspace.resolve(strict=True)
        self._summarizer = summarizer
        self._id_generator = id_generator or (lambda: uuid.uuid4().hex)
        self._persist_threshold_bytes = persist_threshold_bytes
        self._batch_budget_bytes = batch_budget_bytes
        self._preview_head_bytes = preview_head_bytes
        self._preview_tail_bytes = preview_tail_bytes
        self._reactive_tail_groups = reactive_tail_groups
        self._proactive_threshold_bytes = proactive_threshold_bytes
        self._snip_max_groups = snip_max_groups
        self._snip_keep_head_groups = snip_keep_head_groups
        self._keep_recent_tool_groups = keep_recent_tool_groups
        self._prepared_source: tuple[ChatMessage, ...] | None = None
        self._prepared_history: tuple[ChatMessage, ...] | None = None

    def compact_tool_results(self, results: tuple[ToolResult, ...]) -> ToolResultBudgetOutcome:
        """按单项阈值和整批预算把大结果写入 artifact。"""
        copied = [copy_tool_result(result) for result in results]
        sizes = [len(result.content.encode("utf-8")) for result in copied]
        ranked = sorted(range(len(copied)), key=lambda index: (-sizes[index], index))
        selected = {
            index for index, size in enumerate(sizes) if size > self._persist_threshold_bytes
        }
        retained_bytes = sum(
            size for index, size in enumerate(sizes) if index not in selected
        )
        for index in ranked:
            if retained_bytes <= self._batch_budget_bytes:
                break
            if index in selected:
                continue
            selected.add(index)
            retained_bytes -= sizes[index]
        artifacts: list[ToolResultArtifact] = []
        created: list[Path] = []
        try:
            for index in ranked:
                if index not in selected:
                    continue
                result = copied[index]
                reference = self._write_artifact("tool-result", result.content, ".txt")
                created.append(Path(reference.path))
                copied[index] = tool_error(
                    result.error_code or "tool_error",
                    self._artifact_preview(reference, result),
                ) if result.is_error else _success_preview(
                    reference, result, self._preview_head_bytes, self._preview_tail_bytes
                )
                artifacts.append(ToolResultArtifact(index, reference))
        except Exception:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return ToolResultBudgetOutcome(tuple(copied), tuple(artifacts))

    def prepare(self, history: tuple[ChatMessage, ...]) -> tuple[ChatMessage, ...]:
        """请求前按 snip -> micro -> 摘要的顺序生成临时历史。"""
        validate_tool_pairing(list(history))
        if self._prepared_source == history and self._prepared_history is not None:
            return self._prepared_history
        prepared = history
        if self._prepared_source and self._prepared_history and history[: len(self._prepared_source)] == self._prepared_source:
            prepared = self._prepared_history + history[len(self._prepared_source) :]
        prepared = snip_compact_history(prepared, self._snip_max_groups, self._snip_keep_head_groups)
        prepared = micro_compact_history(prepared, self._keep_recent_tool_groups)
        if history_utf8_bytes(prepared) > self._proactive_threshold_bytes:
            prepared = self.compact_proactively(history, summary_history=prepared).history
        self._prepared_source, self._prepared_history = history, prepared
        return prepared

    def compact_proactively(
        self, history: tuple[ChatMessage, ...], *, summary_history: tuple[ChatMessage, ...] | None = None
    ) -> HistoryCompactionOutcome:
        """先完整落盘 transcript，再用结构化摘要替换请求历史。"""
        validate_tool_pairing(list(history))
        transcript = self._write_artifact("transcript", serialize_transcript(history), ".jsonl")
        try:
            summary = self._summarizer.summarize(summary_history or history)
        except Exception:
            Path(transcript.path).unlink(missing_ok=True)
            raise
        content = json.dumps(
            {
                "kind": "compacted_history",
                "transcript_path": transcript.relative_path,
                "current_goal": summary.current_goal,
                "key_findings": list(summary.key_findings),
                "files_read_or_changed": list(summary.files_read_or_changed),
                "remaining_work": list(summary.remaining_work),
                "user_constraints": list(summary.user_constraints),
            }, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        )
        return HistoryCompactionOutcome((system_message(content),), transcript)

    def compact_on_prompt_too_long(self, history: tuple[ChatMessage, ...], retry_count: int = 0) -> HistoryCompactionOutcome:
        """响应式压缩：同一恢复窗口只允许一次，并保留最近完整消息组。"""
        if retry_count > 0:
            raise PromptTooLongRetryError("同一 prompt-too-long 恢复窗口不能重复压缩")
        outcome = self.compact_proactively(history)
        groups = _groups(history)
        tail = flatten_groups(groups[-self._reactive_tail_groups :])
        return HistoryCompactionOutcome((outcome.history[0], *tail), outcome.transcript)

    def _artifact_preview(self, reference: ArtifactReference, result: ToolResult) -> str:
        return _preview_content(reference, result.content, self._preview_head_bytes, self._preview_tail_bytes)

    def _write_artifact(self, kind: str, content: str, extension: str) -> ArtifactReference:
        artifact_id = self._id_generator()
        if not isinstance(artifact_id, str) or len(artifact_id) > 96 or not _ID_PATTERN.fullmatch(artifact_id):
            raise ArtifactPathError("artifact ID 必须是小写短横线 slug")
        state = self._workspace / ".agent_tutorial"
        root = state / "artifacts"
        self._ensure_safe_directory(state)
        self._ensure_safe_directory(root)
        path = root / f"{kind}-{artifact_id}{extension}"
        try:
            self._write_exclusive_atomic(path, content)
        except FileExistsError as error:
            raise ArtifactConflictError(
                f"artifact 已存在: {path.relative_to(self._workspace)}"
            ) from error
        return ArtifactReference(str(path), str(path.relative_to(self._workspace)).replace("\\", "/"), len(content.encode("utf-8")))

    def _ensure_safe_directory(self, path: Path) -> None:
        """创建目录后重新检查真实路径，拒绝符号链接或 workspace 逃逸。"""
        try:
            path.mkdir(exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise ArtifactPathError(f"artifact 路径不是普通目录: {path}")
            resolved = path.resolve(strict=True)
            if resolved != path.absolute() or not resolved.is_relative_to(self._workspace):
                raise ArtifactPathError(f"artifact 目录逃出工作区: {path}")
        except ArtifactPathError:
            raise
        except OSError as error:
            raise ArtifactPathError(f"无法创建或验证 artifact 目录: {path}") from error

    @staticmethod
    def _write_exclusive_atomic(path: Path, content: str) -> None:
        """临时文件先刷盘，再用硬链接独占发布最终文件。"""
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _success_preview(
    reference: ArtifactReference,
    result: ToolResult,
    head: int,
    tail: int,
) -> ToolResult:
    return ToolResult(_preview_content(reference, result.content, head, tail), False, None)


def _preview_content(reference: ArtifactReference, content: str, head: int, tail: int) -> str:
    data = content.encode("utf-8")
    head_bytes = data[:head].decode("utf-8", errors="ignore")
    tail_bytes = data[-tail:].decode("utf-8", errors="ignore") if tail else ""
    return f"<persisted-tool-result>\npath: {reference.relative_path}\nbytes: {reference.original_bytes}\nhead_preview:\n{head_bytes}\ntail_preview:\n{tail_bytes}\n</persisted-tool-result>"


def _groups(history: tuple[ChatMessage, ...]) -> list[_MessageGroup]:
    result: list[_MessageGroup] = []
    index = 0
    while index < len(history):
        message = history[index]
        if isinstance(message, AssistantMessage) and message.tool_calls:
            end = index + 1 + len(message.tool_calls)
            result.append(_MessageGroup(tuple(history[index:end]), True))
            index = end
        else:
            result.append(_MessageGroup((message,), False))
            index += 1
    return result


def flatten_groups(groups: list[_MessageGroup]) -> tuple[ChatMessage, ...]:
    return tuple(message for group in groups for message in group.messages)


def micro_compact_history(history: tuple[ChatMessage, ...], keep_recent_tool_groups: int = 3) -> tuple[ChatMessage, ...]:
    groups = _groups(history)
    tool_indices = [index for index, group in enumerate(groups) if group.is_tool_exchange]
    compact_indices = set(tool_indices[:-keep_recent_tool_groups] if keep_recent_tool_groups else tool_indices)
    updated: list[_MessageGroup] = []
    for index, group in enumerate(groups):
        if index not in compact_indices:
            updated.append(group)
            continue
        assistant = group.messages[0]
        if not isinstance(assistant, AssistantMessage):
            updated.append(group)
            continue
        replacement = tuple(
            tool_message(COMPACTED_TOOL_RESULT, message.tool_call_id)
            if isinstance(message, ToolMessage) else message
            for message in group.messages
        )
        updated.append(_MessageGroup(replacement, True))
    compacted = flatten_groups(updated)
    validate_tool_pairing(list(compacted))
    return compacted


def snip_compact_history(history: tuple[ChatMessage, ...], max_groups: int = 50, keep_head_groups: int = 3) -> tuple[ChatMessage, ...]:
    groups = _groups(history)
    if len(groups) <= max_groups:
        return history
    tail_count = max_groups - keep_head_groups - 1
    omitted = len(groups) - keep_head_groups - tail_count
    compacted = [*groups[:keep_head_groups], _MessageGroup((system_message(f"[Compacted: {omitted} message groups omitted]"),), False), *groups[-tail_count:]]
    result = flatten_groups(compacted)
    validate_tool_pairing(list(result))
    return result


def serialize_transcript(history: tuple[ChatMessage, ...]) -> str:
    """将内部消息转换成稳定 JSONL，便于人工检查和故障恢复。"""
    lines: list[str] = []
    for message in history:
        if message.role == "system" or message.role == "user":
            lines.append(json.dumps({"content": message.content, "role": message.role}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        elif message.role == "assistant":
            lines.append(json.dumps({"content": message.content, "role": "assistant", "tool_calls": [{"function": {"arguments": call.arguments, "name": call.name}, "id": call.id, "type": "function"} for call in message.tool_calls]}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        else:
            lines.append(json.dumps({"content": message.content, "role": "tool", "tool_call_id": message.tool_call_id}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return "\n".join(lines) + "\n"


def history_utf8_bytes(history: tuple[ChatMessage, ...]) -> int:
    return len(serialize_transcript(history).encode("utf-8"))
