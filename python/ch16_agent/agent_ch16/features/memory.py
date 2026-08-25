"""第九章：跨会话的文件级长期记忆。

Java 开发者可以把本模块拆成三层理解：

* :class:`MemoryRecord` 类似 Java ``record``，只表达“一条合法记忆”；
* :class:`MemoryStore` 类似 Repository，负责文件事务和路径安全；
* :class:`MemorySession` 类似 Spring 拦截器，在回合前后执行记忆逻辑。

记忆不是模型可直接调用的普通工具。模型只能通过三个“无工具 side-query”帮助选择、
提取和整理，真正的文件读写仍由受控的 ``MemoryStore`` 完成。
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import yaml

from ..core.messages import ChatMessage, system_message, user_message, validate_tool_pairing
from ..core.model import ModelClient, ModelRequest

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MEMORY_FILENAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[a-z0-9]+\.md$")
CJK_RUN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
MEMORY_TYPES = frozenset({"user", "feedback", "project", "reference"})
MAX_MEMORY_LINES = 200
MAX_MEMORY_BYTES = 4_096
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 4_096

# Windows 不允许这些名称作为文件名。带数字的设备名需要单独用正则判断。
WINDOWS_RESERVED_NAMES = frozenset({"con", "prn", "aux", "nul"})
WINDOWS_RESERVED_PATTERN = re.compile(r"^(?:com|lpt)[1-9]$")

# Python 的 RLock 只负责同一进程内互斥。第九章的同步 Agent 不会并行写同一 Store，
# 但测试和宿主程序可能创建多个 Store 实例，因此按 .memory 绝对路径共享锁。
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

SELECTOR_SYSTEM_PROMPT = """从目录中选择与查询直接相关的记忆名称。
只能返回 JSON 字符串数组，不得调用工具；没有相关项时返回 []。"""
EXTRACTOR_SYSTEM_PROMPT = """从会话中提取值得跨会话保留的新记忆。
只能返回 JSON 数组，不得调用工具。每项必须且只能包含 name、type、description、body；
type 只能是 user、feedback、project、reference，没有新记忆时返回 []。"""
CONSOLIDATOR_SYSTEM_PROMPT = """整理给定记忆，合并重复或冲突内容，不得调用工具。
只能返回 JSON object，必须且只能包含 source_names 和 records；
source_names 是被替换的原记忆名称，records 是非空的新记忆数组。"""


class MemoryStoreError(Exception):
    """记忆内容、模型输出或持久化文件违反第九章契约。"""


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """一条不可变的长期记忆，类似 Java ``record MemoryRecord(...)``。

    字段说明：
        name: 稳定的逻辑名称，也参与文件名生成，只允许安全的小写 slug。
        description: 展示在 ``MEMORY.md`` 中的一行摘要，供选择器低成本检索。
        kind: 记忆分类，只能是 user、feedback、project、reference。
        body: 记忆完整正文，真正注入模型的是这里的内容。
    """

    name: str
    description: str
    kind: str
    body: str

    def __post_init__(self) -> None:
        """像 Java 构造器参数校验一样，保证非法对象根本无法被创建。"""
        if not isinstance(self.name, str) or not _is_safe_slug(self.name):
            raise MemoryStoreError("记忆名称必须是安全的小写 slug")
        if not isinstance(self.description, str) or not self.description.strip():
            raise MemoryStoreError("记忆摘要必须是非空字符串")
        if "\n" in self.description or "\r" in self.description:
            raise MemoryStoreError("记忆摘要必须放在一行内")
        if self.kind not in MEMORY_TYPES:
            raise MemoryStoreError("记忆类型必须是 user、feedback、project 或 reference")
        if not isinstance(self.body, str) or not self.body.strip():
            raise MemoryStoreError("记忆正文不能为空")

        # 统一换行符，避免同一正文因 Windows/Linux 换行不同而产生不同文件。
        normalized = self.body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        object.__setattr__(self, "body", normalized)
        _enforce_memory_budget(serialize_memory(self).encode("utf-8"))


class MemorySelector(Protocol):
    """选择相关记忆的接口，类似 Java Strategy interface。"""

    def select(self, query: str, catalog: str) -> str:
        """返回 JSON 字符串数组，例如 ``[\"database-rule\"]``。"""


class MemoryExtractor(Protocol):
    """从完整会话中提取新记忆的接口。"""

    def extract(self, history: tuple[ChatMessage, ...], catalog: str) -> str:
        """返回由记忆对象组成的 JSON 数组。"""


class MemoryConsolidator(Protocol):
    """整理重复或冲突记忆的接口。"""

    def consolidate(self, records: tuple[MemoryRecord, ...]) -> str:
        """返回 source_names 与 records 组成的 JSON object。"""


class ModelMemoryQueries:
    """使用同一个模型实现选择、提取和整理三个无工具 side-query。

    字段 ``_model`` 相当于注入进来的 Java ``ModelClient``。三个方法都把 ``tools``
    固定为空元组，因此模型无法借记忆流程调用 shell 或文件工具。
    """

    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def select(self, query: str, catalog: str) -> str:
        """只把轻量目录和本轮问题交给模型，选择相关记忆名称。"""
        return self._complete(
            SELECTOR_SYSTEM_PROMPT,
            (user_message(_stable_json({"catalog": catalog, "query": query})),),
        )

    def extract(self, history: tuple[ChatMessage, ...], catalog: str) -> str:
        """从 canonical history 的深拷贝中提取值得跨会话保存的事实。"""
        snapshot = _copy_history(history)
        validate_tool_pairing(snapshot)
        return self._complete(
            EXTRACTOR_SYSTEM_PROMPT,
            (*snapshot, user_message(_stable_json({"existing_catalog": catalog}))),
        )

    def consolidate(self, records: tuple[MemoryRecord, ...]) -> str:
        """让模型给出整理计划，但不允许模型直接修改文件。"""
        snapshot = _validate_records(records, allow_empty=False)
        return self._complete(
            CONSOLIDATOR_SYSTEM_PROMPT,
            (user_message(_stable_json([record_payload(record) for record in snapshot])),),
        )

    def _complete(self, instruction: str, messages: tuple[ChatMessage, ...]) -> str:
        """执行一次无工具模型请求，并严格要求完整的 stop 文本响应。"""
        reply = self._model.complete(
            ModelRequest(messages=(system_message(instruction), *messages), tools=())
        )
        if reply.message.tool_calls:
            raise MemoryStoreError("记忆 side-query 不允许调用工具")
        if reply.finish_reason != "stop":
            raise MemoryStoreError(
                f"记忆 side-query 必须以 stop 结束，实际为 {reply.finish_reason}"
            )
        if reply.message.content is None or not reply.message.content.strip():
            raise MemoryStoreError("记忆 side-query 必须返回非空文本")
        return reply.message.content


@dataclass(frozen=True, slots=True)
class _StoredMemory:
    """Repository 内部对象：把物理文件名和领域记录绑定在一起。"""

    filename: str
    record: MemoryRecord


@dataclass(frozen=True, slots=True)
class _ConsolidationPlan:
    """已通过严格校验的整理计划。"""

    source_names: tuple[str, ...]
    records: tuple[MemoryRecord, ...]


class MemoryStore:
    """以 ``manifest.json`` 为权威集合的文件 Repository。

    字段说明：
        _workspace: 已 ``resolve`` 的真实工作区根目录。
        _id_generator: 文件唯一后缀生成器；测试中可注入固定值。
        _max_index_lines/_max_index_bytes: MEMORY.md 的行数和字节预算。

    提交顺序是“新正文 -> MEMORY.md -> manifest.json”。manifest 最后替换，意味着只有
    manifest 成功更新后，新集合才正式生效；中途失败会清理新正文并恢复旧目录。
    """

    def __init__(
        self,
        workspace: str,
        *,
        id_generator: Callable[[], str] | None = None,
        max_index_lines: int = MAX_INDEX_LINES,
        max_index_bytes: int = MAX_INDEX_BYTES,
    ) -> None:
        if not isinstance(workspace, str) or not workspace.strip():
            raise TypeError("workspace 必须是非空字符串")
        root = Path(workspace).resolve(strict=True)
        if not root.is_dir():
            raise TypeError("workspace 必须是目录")
        if max_index_lines <= 0 or max_index_bytes <= 0:
            raise ValueError("索引预算必须是正整数")
        self._workspace = root
        self._id_generator = id_generator or (lambda: uuid.uuid4().hex)
        self._max_index_lines = max_index_lines
        self._max_index_bytes = max_index_bytes

    @property
    def root(self) -> Path:
        """返回本工作区的记忆目录，不会自动创建它。"""
        return self._workspace / ".memory"

    def records(self) -> tuple[MemoryRecord, ...]:
        """严格按照 manifest 顺序读取当前有效记忆，忽略未登记的散落文件。"""
        if not self.root.exists():
            return ()
        self._validate_root()
        with self._lock():
            return tuple(item.record for item in self._load())

    def render_catalog(self) -> str:
        """生成轻量目录；目录只含名称、文件名和摘要，不含完整正文。"""
        if not self.root.exists():
            return ""
        self._validate_root()
        with self._lock():
            return self._render_index(self._load())

    def add(self, record: MemoryRecord) -> None:
        """追加一条记忆，是 ``extend`` 的便捷入口。"""
        self.extend((record,))

    def extend(self, records: Sequence[MemoryRecord]) -> None:
        """原子追加一批新记忆；任一条非法或重名时整批不写入。"""
        validated = _validate_records(tuple(records), allow_empty=True)
        if not validated:
            return
        self._prepare_root()
        with self._lock():
            current = list(self._load())
            current_names = {item.record.name for item in current}
            duplicates = sorted(record.name for record in validated if record.name in current_names)
            if duplicates:
                raise MemoryStoreError(f"记忆名称已存在: {', '.join(duplicates)}")
            added = [_StoredMemory(self._new_filename(record.name), record) for record in validated]
            self._commit([*current, *added], created=added)

    def apply_consolidation(
        self,
        base_records: Sequence[MemoryRecord],
        additions: Sequence[MemoryRecord],
        source_names: Sequence[str],
        replacements: Sequence[MemoryRecord],
    ) -> None:
        """按整理计划替换指定来源，同时保留模型等待期间并发加入的其他记忆。

        ``base_records`` 是调用模型前看到的旧快照。真正提交时会重新读取 manifest，只校验
        参与整理的旧记录没有变化；未被列入 ``source_names`` 的并发新记录会被保留。
        """
        base = _validate_records(tuple(base_records), allow_empty=True)
        pending_additions = _validate_records(tuple(additions), allow_empty=True)
        new_records = _validate_records(tuple(replacements), allow_empty=False)
        candidates = _validate_records((*base, *pending_additions), allow_empty=True)
        sources = _validate_source_names(tuple(source_names), candidates)

        self._prepare_root()
        with self._lock():
            current = list(self._load())
            current_by_name = {item.record.name: item.record for item in current}
            if any(current_by_name.get(record.name) != record for record in base):
                raise MemoryStoreError("整理期间记忆集合发生变化")

            source_set = set(sources)
            retained = [item for item in current if item.record.name not in source_set]
            pending = [record for record in pending_additions if record.name not in source_set]
            pending.extend(new_records)
            _validate_records(
                tuple(item.record for item in retained) + tuple(pending), allow_empty=False
            )
            stored_additions = [
                _StoredMemory(self._new_filename(record.name), record) for record in pending
            ]
            self._commit(
                [*retained, *stored_additions],
                created=stored_additions,
                remove_after=[item for item in current if item.record.name in source_set],
            )

    def _prepare_root(self) -> None:
        """创建 .memory 后立即校验它仍位于 workspace 内。"""
        self.root.mkdir(parents=True, exist_ok=True)
        self._validate_root()

    def _validate_root(self) -> None:
        """拒绝把 .memory 做成指向工作区外部的符号链接。"""
        try:
            resolved = self.root.resolve(strict=True)
        except OSError as error:
            raise MemoryStoreError("无法解析 .memory 目录") from error
        if resolved != self.root or not resolved.is_relative_to(self._workspace):
            raise MemoryStoreError(".memory 目录逃出了 workspace")
        if not resolved.is_dir():
            raise MemoryStoreError(".memory 不是目录")

    def _lock(self) -> threading.RLock:
        """取得此 .memory 目录在当前进程中共享的可重入锁。"""
        key = str(self.root)
        with _LOCKS_GUARD:
            return _LOCKS.setdefault(key, threading.RLock())

    def _new_filename(self, name: str) -> str:
        """生成不覆盖旧文件的新文件名。"""
        identifier = self._id_generator()
        if not isinstance(identifier, str) or not _is_safe_slug(identifier):
            raise MemoryStoreError("生成的记忆 ID 不是安全 slug")
        return f"{name}-{identifier}.md"

    def _commit(
        self,
        records: list[_StoredMemory],
        *,
        created: list[_StoredMemory],
        remove_after: list[_StoredMemory] | None = None,
    ) -> None:
        """提交完整集合；manifest 替换成功后才删除被整理掉的旧正文。"""
        index = self._render_index(records)
        manifest = _stable_json({"version": 1, "files": [item.filename for item in records]})
        index_path = self.root / "MEMORY.md"
        manifest_path = self.root / "manifest.json"
        previous_index = index_path.read_bytes() if index_path.exists() else None
        written: list[Path] = []
        try:
            for item in created:
                path = self.root / item.filename
                _exclusive_write(path, serialize_memory(item.record))
                # 文件已经创建成功，从这一刻起就必须纳入失败清理列表。
                written.append(path)
                # 写后再读回领域对象，相当于数据库提交前做一次反序列化校验。
                if parse_memory(path.read_text(encoding="utf-8")) != item.record:
                    raise MemoryStoreError(f"记忆文件写后校验失败: {item.filename}")
            _atomic_replace(index_path, index.encode("utf-8"))
            try:
                _atomic_replace(manifest_path, manifest.encode("utf-8"))
            except Exception:
                if previous_index is None:
                    index_path.unlink(missing_ok=True)
                else:
                    _atomic_replace(index_path, previous_index)
                raise
        except Exception:
            for path in written:
                path.unlink(missing_ok=True)
            raise

        for item in remove_after or []:
            (self.root / item.filename).unlink(missing_ok=True)

    def _load(self) -> list[_StoredMemory]:
        """读取权威 manifest，并逐个校验登记文件的路径、编码和正文。"""
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            return []
        try:
            value: object = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise MemoryStoreError("记忆 manifest 不是合法 UTF-8 JSON") from error
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "files"}
            or value.get("version") != 1
            or not isinstance(value.get("files"), list)
        ):
            raise MemoryStoreError("记忆 manifest 结构无效")
        raw_files = cast(list[object], value["files"])
        if not all(isinstance(filename, str) for filename in raw_files):
            raise MemoryStoreError("记忆 manifest 文件名必须是字符串")
        files = cast(list[str], raw_files)
        if len(files) != len(set(files)):
            raise MemoryStoreError("记忆 manifest 文件名不能重复")
        if len(files) > self._max_index_lines:
            raise MemoryStoreError("记忆 manifest 超过索引行数限制")

        result: list[_StoredMemory] = []
        for filename in files:
            if not MEMORY_FILENAME_PATTERN.fullmatch(filename) or _is_windows_reserved(filename):
                raise MemoryStoreError(f"记忆 manifest 包含不安全文件名: {filename}")
            unresolved = self.root / filename
            try:
                path = unresolved.resolve(strict=True)
            except OSError as error:
                raise MemoryStoreError(f"无法读取记忆文件: {filename}") from error
            if not path.is_relative_to(self.root):
                raise MemoryStoreError(f"记忆文件逃出了 .memory: {filename}")
            try:
                record = parse_memory(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as error:
                raise MemoryStoreError(f"无法读取记忆文件: {filename}") from error
            result.append(_StoredMemory(filename, record))
        return result

    def _render_index(self, records: Sequence[_StoredMemory]) -> str:
        """构建可重建的 MEMORY.md，并执行行数与 UTF-8 字节预算。"""
        if len(records) > self._max_index_lines:
            raise MemoryStoreError("记忆目录超过行数限制")
        rendered = "".join(
            f"- [{item.record.name}]({item.filename}) - {item.record.description}\n"
            for item in records
        )
        if len(rendered.encode("utf-8")) > self._max_index_bytes:
            raise MemoryStoreError("记忆目录超过 UTF-8 字节限制")
        return rendered


class MemorySession:
    """把 MemoryStore 接到 AgentRunner 的一轮生命周期。

    字段说明：
        _store: 唯一允许碰文件的 Repository。
        _selector/_extractor/_consolidator: 可替换策略，生产环境由模型实现。
        _selected: 当前回合选中的不可变快照。
        _last_error: 最近一次记忆辅助流程错误；错误不会中断主 Agent。
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        selector: MemorySelector | None = None,
        extractor: MemoryExtractor | None = None,
        consolidator: MemoryConsolidator | None = None,
        max_selected: int = 5,
        consolidate_threshold: int = 10,
        emit_context_messages: bool = True,
    ) -> None:
        if max_selected <= 0 or consolidate_threshold <= 0:
            raise ValueError("记忆选择数量和整理阈值必须是正整数")
        self._store = store
        self._selector = selector
        self._extractor = extractor
        self._consolidator = consolidator
        self._max_selected = max_selected
        self._consolidate_threshold = consolidate_threshold
        self._emit_context_messages = emit_context_messages
        self._selected: tuple[MemoryRecord, ...] = ()
        self._last_error: str | None = None

    @property
    def selected(self) -> tuple[MemoryRecord, ...]:
        """返回当前回合选中的只读记忆快照。"""
        return self._selected

    @property
    def last_error(self) -> str | None:
        """返回最近的记忆错误；None 表示本回合辅助流程正常。"""
        return self._last_error

    def begin_turn(self, query: str) -> None:
        """回合开始选择相关记忆；模型失败时退回确定性关键词匹配。"""
        self._selected = ()
        self._last_error = None
        try:
            records = self._store.records()
            if not records:
                return
            if self._selector is not None:
                try:
                    output = self._selector.select(query, self._store.render_catalog())
                    names = _parse_names(output)
                    by_name = {record.name: record for record in records}
                    if any(name not in by_name for name in names):
                        raise MemoryStoreError("selector 返回了未知记忆名称")
                    self._selected = tuple(by_name[name] for name in names[: self._max_selected])
                    return
                except Exception:  # noqa: BLE001 - side-query 必须与主任务隔离。
                    self._last_error = "记忆选择失败，已使用确定性关键词回退"
            self._selected = _keyword_select(query, records, self._max_selected)
        except Exception:  # noqa: BLE001 - 记忆损坏也不能阻断主回答。
            self._last_error = "读取长期记忆失败，本轮未注入记忆"

    def before_model(self) -> tuple[ChatMessage, ...]:
        """把选中记忆临时附加到模型请求，不写入 canonical history。"""
        if not self._emit_context_messages or not self._selected:
            return ()
        return (system_message(self.render_selected()),)

    def render_selected(self) -> str:
        """渲染带边界标签的记忆上下文，方便模型区分规则和用户输入。"""
        if not self._selected:
            return ""
        sections = ["<relevant_memories>"]
        for record in self._selected:
            sections.extend([f"## {record.name} ({record.kind})", record.description, record.body])
        sections.append("</relevant_memories>")
        return "\n\n".join(sections)

    def complete(self, history: tuple[ChatMessage, ...]) -> None:
        """主回答完成后提取新记忆，必要时将候选集合交给模型整理。"""
        try:
            current = self._store.records()
            candidate = current
            extracted: tuple[MemoryRecord, ...] = ()
            if self._extractor is not None:
                try:
                    snapshot = _copy_history(history)
                    output = self._extractor.extract(snapshot, self._store.render_catalog())
                    extracted = _parse_records(output, allow_empty=True)
                    candidate = _validate_records((*current, *extracted), allow_empty=True)
                except Exception:  # noqa: BLE001
                    self._last_error = "记忆提取失败，旧记忆保持不变"
                    return

            if self._consolidator is None or len(candidate) < self._consolidate_threshold:
                if extracted:
                    try:
                        self._store.extend(extracted)
                    except Exception:  # noqa: BLE001
                        self._last_error = "记忆提取结果写入失败，旧记忆保持不变"
                return

            try:
                plan = _parse_consolidation_plan(
                    self._consolidator.consolidate(candidate), candidate
                )
                self._store.apply_consolidation(current, extracted, plan.source_names, plan.records)
            except Exception:  # noqa: BLE001
                self._last_error = "记忆整理失败，旧记忆保持不变"
        except Exception:  # noqa: BLE001
            self._last_error = "长期记忆流程失败，但主任务已正常完成"


def serialize_memory(record: MemoryRecord) -> str:
    """把领域对象序列化为 YAML frontmatter 加 Markdown 正文。"""
    metadata = yaml.safe_dump(
        {"name": record.name, "description": record.description, "type": record.kind},
        allow_unicode=True,
        sort_keys=False,
    ).strip()
    return f"---\n{metadata}\n---\n\n{record.body}\n"


def parse_memory(text: str) -> MemoryRecord:
    """从不可信文件内容恢复 MemoryRecord，并严格检查 schema 和字段类型。"""
    if not isinstance(text, str):
        raise MemoryStoreError("记忆文件内容必须是字符串")
    _enforce_memory_budget(text.encode("utf-8"))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise MemoryStoreError("记忆文件缺少 YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise MemoryStoreError("记忆文件的 YAML frontmatter 没有闭合") from error
    try:
        metadata: object = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as error:
        raise MemoryStoreError("记忆 frontmatter 不是合法 YAML") from error
    if not isinstance(metadata, dict) or set(metadata) != {"name", "description", "type"}:
        raise MemoryStoreError("记忆 frontmatter 结构无效")
    if not all(isinstance(metadata[field], str) for field in ("name", "description", "type")):
        raise MemoryStoreError("记忆 frontmatter 字段必须是字符串")
    return MemoryRecord(
        cast(str, metadata["name"]),
        cast(str, metadata["description"]),
        cast(str, metadata["type"]),
        "\n".join(lines[end + 1 :]).strip("\n"),
    )


def record_payload(record: MemoryRecord) -> dict[str, str]:
    """生成交给整理模型的稳定 JSON 字段。"""
    return {
        "name": record.name,
        "type": record.kind,
        "description": record.description,
        "body": record.body,
    }


def _is_safe_slug(value: str) -> bool:
    return bool(SLUG_PATTERN.fullmatch(value)) and not _is_windows_reserved(value)


def _is_windows_reserved(value: str) -> bool:
    component = value.split(".", 1)[0].lower()
    return component in WINDOWS_RESERVED_NAMES or bool(
        WINDOWS_RESERVED_PATTERN.fullmatch(component)
    )


def _enforce_memory_budget(raw: bytes) -> None:
    """限制单条记忆的物理文件大小，避免长期记忆反过来撑爆上下文。"""
    line_count = len(raw.splitlines())
    if line_count > MAX_MEMORY_LINES:
        raise MemoryStoreError(f"记忆文件不能超过 {MAX_MEMORY_LINES} 行")
    if len(raw) > MAX_MEMORY_BYTES:
        raise MemoryStoreError(f"记忆文件不能超过 {MAX_MEMORY_BYTES} UTF-8 bytes")


def _validate_records(
    records: tuple[MemoryRecord, ...], allow_empty: bool
) -> tuple[MemoryRecord, ...]:
    if not all(isinstance(record, MemoryRecord) for record in records):
        raise MemoryStoreError("记忆集合只能包含 MemoryRecord")
    if not allow_empty and not records:
        raise MemoryStoreError("记忆集合不能为空")
    if len({record.name for record in records}) != len(records):
        raise MemoryStoreError("记忆名称不能重复")
    return records


def _parse_records(output: str, allow_empty: bool) -> tuple[MemoryRecord, ...]:
    """整体解析模型 JSON；不会从解释文字或代码围栏中截取“看起来合法”的片段。"""
    if not isinstance(output, str):
        raise MemoryStoreError("记忆模型输出必须是 JSON 字符串")
    try:
        value: object = json.loads(output)
    except json.JSONDecodeError as error:
        raise MemoryStoreError("记忆模型输出不是合法 JSON") from error
    if not isinstance(value, list):
        raise MemoryStoreError("记忆模型输出必须是 JSON 数组")
    records: list[MemoryRecord] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict) or set(item) != {"name", "type", "description", "body"}:
            raise MemoryStoreError("记忆模型数组项结构无效")
        if not all(
            isinstance(item[field], str) for field in ("name", "type", "description", "body")
        ):
            raise MemoryStoreError("记忆模型数组项字段必须是字符串")
        records.append(
            MemoryRecord(
                cast(str, item["name"]),
                cast(str, item["description"]),
                cast(str, item["type"]),
                cast(str, item["body"]),
            )
        )
    return _validate_records(tuple(records), allow_empty)


def _parse_names(output: str) -> tuple[str, ...]:
    try:
        value: object = json.loads(output)
    except json.JSONDecodeError as error:
        raise MemoryStoreError("selector 输出不是合法 JSON") from error
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise MemoryStoreError("selector 输出必须是字符串数组")
    names = cast(list[str], value)
    if len(names) != len(set(names)):
        raise MemoryStoreError("selector 返回了重复记忆名称")
    return tuple(names)


def _parse_consolidation_plan(
    output: str, candidates: tuple[MemoryRecord, ...]
) -> _ConsolidationPlan:
    try:
        value: object = json.loads(output)
    except json.JSONDecodeError as error:
        raise MemoryStoreError("整理模型输出不是合法 JSON") from error
    if not isinstance(value, dict) or set(value) != {"source_names", "records"}:
        raise MemoryStoreError("整理模型输出结构无效")
    raw_sources = value["source_names"]
    raw_records = value["records"]
    if not isinstance(raw_sources, list) or not all(isinstance(name, str) for name in raw_sources):
        raise MemoryStoreError("source_names 必须是字符串数组")
    sources = _validate_source_names(tuple(cast(list[str], raw_sources)), candidates)
    records = _parse_records(json.dumps(raw_records, ensure_ascii=False), allow_empty=False)
    return _ConsolidationPlan(sources, records)


def _validate_source_names(
    source_names: tuple[str, ...], candidates: tuple[MemoryRecord, ...]
) -> tuple[str, ...]:
    if not source_names:
        raise MemoryStoreError("source_names 不能为空")
    if len(source_names) != len(set(source_names)):
        raise MemoryStoreError("source_names 不能重复")
    candidate_names = {record.name for record in candidates}
    if any(name not in candidate_names for name in source_names):
        raise MemoryStoreError("source_names 包含候选集合之外的名称")
    return source_names


def _keyword_select(
    query: str, records: tuple[MemoryRecord, ...], limit: int
) -> tuple[MemoryRecord, ...]:
    """确定性回退：英文取长度至少 3 的词，中文取连续双字 bigram。"""
    tokens = {token for token in re.findall(r"[a-z0-9]+", query.lower()) if len(token) >= 3}
    for run in CJK_RUN_PATTERN.findall(query):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    ranked = sorted(
        (
            (
                sum(token in f"{record.name} {record.description}".lower() for token in tokens),
                record,
            )
            for record in records
        ),
        key=lambda item: (-item[0], item[1].name),
    )
    return tuple(record for score, record in ranked[:limit] if score > 0)


def _copy_history(history: Sequence[ChatMessage]) -> tuple[ChatMessage, ...]:
    """深拷贝调用方历史，side-query 无法意外修改 AgentRunner 内部消息。"""
    return tuple(copy.deepcopy(message) for message in history)


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _exclusive_write(path: Path, content: str) -> None:
    """使用操作系统 O_EXCL 原子创建，消除 exists-then-write 竞态。"""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise MemoryStoreError(f"记忆文件已存在: {path.name}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _atomic_replace(path: Path, content: bytes) -> None:
    """同目录写临时文件、fsync，再用 os.replace 原子替换目标文件。"""
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
