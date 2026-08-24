import json
import threading
from pathlib import Path

import pytest

from agent_ch12.core.messages import assistant_message, tool_call, user_message
from agent_ch12.core.model import ModelReply, ModelRequest
from agent_ch12.features.memory import (
    MAX_MEMORY_BYTES,
    MemoryRecord,
    MemorySession,
    MemoryStore,
    MemoryStoreError,
    ModelMemoryQueries,
    parse_memory,
    serialize_memory,
)


def record(
    name: str,
    description: str = "项目约束",
    body: str = "使用真实数据库。",
    kind: str = "project",
) -> MemoryRecord:
    """减少测试样板；Java 中相当于 Test Data Builder。"""
    return MemoryRecord(name, description, kind, body)


def ids(*values: str):
    """返回可预测的 ID 生成器，便于断言文件名。"""
    iterator = iter(values)
    return lambda: next(iterator)


class ScriptedModel:
    def __init__(self, replies: list[ModelReply]) -> None:
        self._replies = replies
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelReply:
        self.requests.append(request)
        return self._replies.pop(0)


def test_memory_record_validates_slug_type_and_windows_reserved_name() -> None:
    with pytest.raises(MemoryStoreError):
        record("../outside")
    with pytest.raises(MemoryStoreError):
        record("COM1")
    with pytest.raises(MemoryStoreError):
        record("valid-name", kind="other")


def test_memory_record_enforces_line_and_utf8_byte_budgets() -> None:
    with pytest.raises(MemoryStoreError, match="200 行"):
        record("too-many-lines", body="\n".join("x" for _ in range(201)))
    with pytest.raises(MemoryStoreError, match="4096"):
        record("too-many-bytes", body="中" * MAX_MEMORY_BYTES)


def test_memory_round_trip_uses_yaml_frontmatter() -> None:
    original = record("database-rule", "数据库规则", "第一行\r\n第二行")

    text = serialize_memory(original)

    assert text.startswith("---\nname: database-rule\n")
    assert parse_memory(text) == record("database-rule", "数据库规则", "第一行\n第二行")


def test_parse_memory_rejects_non_string_frontmatter_fields() -> None:
    text = "---\nname: 123\ndescription: test\ntype: project\n---\n\nbody\n"
    with pytest.raises(MemoryStoreError, match="字段必须是字符串"):
        parse_memory(text)


def test_model_memory_queries_are_always_tool_free() -> None:
    model = ScriptedModel(
        [
            ModelReply(assistant_message("[]"), "stop"),
            ModelReply(assistant_message("[]"), "stop"),
            ModelReply(
                assistant_message(
                    '{"source_names":["fact"],"records":['
                    '{"name":"merged","type":"project",'
                    '"description":"整理后","body":"正文"}]}'
                ),
                "stop",
            ),
        ]
    )
    queries = ModelMemoryQueries(model)

    queries.select("数据库", "catalog")
    queries.extract((user_message("记住规则"), assistant_message("好")), "catalog")
    queries.consolidate((record("fact"),))

    assert len(model.requests) == 3
    assert all(request.tools == () for request in model.requests)


@pytest.mark.parametrize(
    "reply",
    [
        ModelReply(assistant_message(None, (tool_call("1", "shell", "{}"),)), "tool_calls"),
        ModelReply(assistant_message("[]"), "length"),
        ModelReply(assistant_message("  "), "stop"),
    ],
)
def test_model_memory_queries_reject_tools_incomplete_or_empty_replies(reply: ModelReply) -> None:
    queries = ModelMemoryQueries(ScriptedModel([reply]))
    with pytest.raises(MemoryStoreError):
        queries.select("query", "catalog")


def test_store_writes_manifest_index_and_record_files(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one", "two"))

    store.extend((record("database"), record("powershell", "命令约束", "只用 PowerShell。")))

    memory_root = tmp_path / ".memory"
    assert json.loads((memory_root / "manifest.json").read_text(encoding="utf-8")) == {
        "version": 1,
        "files": ["database-one.md", "powershell-two.md"],
    }
    assert (memory_root / "MEMORY.md").read_text(encoding="utf-8") == (
        "- [database](database-one.md) - 项目约束\n"
        "- [powershell](powershell-two.md) - 命令约束\n"
    )
    assert store.records() == (
        record("database"),
        record("powershell", "命令约束", "只用 PowerShell。"),
    )


def test_store_only_loads_files_registered_by_manifest(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one"))
    store.add(record("registered"))
    (store.root / "unregistered-two.md").write_text(
        serialize_memory(record("unregistered")), encoding="utf-8"
    )

    assert store.records() == (record("registered"),)


@pytest.mark.parametrize(
    "manifest",
    [
        '{"version":1,"files":"bad"}',
        '{"version":1,"files":[1]}',
        '{"version":1,"files":["same-one.md","same-one.md"]}',
        '{"version":1,"files":["../outside.md"]}',
    ],
)
def test_store_rejects_invalid_manifest(tmp_path: Path, manifest: str) -> None:
    root = tmp_path / ".memory"
    root.mkdir()
    (root / "manifest.json").write_text(manifest, encoding="utf-8")

    with pytest.raises(MemoryStoreError):
        MemoryStore(str(tmp_path)).records()


def test_store_rejects_memory_root_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        try:
            (tmp_path / ".memory").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("当前 Windows 环境不允许创建符号链接")
        with pytest.raises(MemoryStoreError, match="逃出了 workspace"):
            MemoryStore(str(tmp_path)).records()
    finally:
        outside.rmdir()


def test_store_does_not_leave_partial_batch_when_filename_conflicts(tmp_path: Path) -> None:
    root = tmp_path / ".memory"
    root.mkdir()
    (root / "second-conflict.md").write_text("占位", encoding="utf-8")
    store = MemoryStore(str(tmp_path), id_generator=ids("new", "conflict"))

    with pytest.raises(MemoryStoreError, match="已存在"):
        store.extend((record("first"), record("second")))

    assert not (root / "first-new.md").exists()
    assert not (root / "manifest.json").exists()


def test_store_keeps_old_collection_when_new_index_exceeds_budget(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one", "two"), max_index_bytes=60)
    store.add(record("first", "短摘要"))
    old_manifest = (store.root / "manifest.json").read_text(encoding="utf-8")

    with pytest.raises(MemoryStoreError, match="字节限制"):
        store.add(record("second", "会让目录明显超过预算的很长摘要"))

    assert (store.root / "manifest.json").read_text(encoding="utf-8") == old_manifest
    assert store.records() == (record("first", "短摘要"),)


def test_concurrent_store_instances_serialize_writers(tmp_path: Path) -> None:
    stores = [MemoryStore(str(tmp_path), id_generator=ids(f"id-{index}")) for index in range(8)]
    errors: list[Exception] = []

    def write(index: int) -> None:
        try:
            stores[index].add(record(f"memory-{index}"))
        except Exception as error:  # noqa: BLE001 - 测试线程要把异常带回主线程。
            errors.append(error)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(item.name for item in stores[0].records()) == [
        f"memory-{index}" for index in range(8)
    ]


class FixedSelector:
    def __init__(self, output: str | Exception) -> None:
        self.output = output

    def select(self, _query: str, _catalog: str) -> str:
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class FixedExtractor:
    def __init__(self, output: str | Exception) -> None:
        self.output = output
        self.histories: list[tuple[object, ...]] = []

    def extract(self, history, _catalog: str) -> str:
        self.histories.append(history)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class FixedConsolidator:
    def __init__(self, output: str | Exception) -> None:
        self.output = output
        self.calls = 0

    def consolidate(self, _records) -> str:
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


def test_session_injects_only_selected_memory(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one", "two"))
    store.extend(
        (
            record("tabs", "缩进偏好", "始终使用 Tab。", "user"),
            record("database", "数据库集成约束", "使用真实数据库。"),
        )
    )
    session = MemorySession(store, selector=FixedSelector('["database"]'))

    session.begin_turn("数据库测试怎么运行？")

    context = session.before_model()
    assert session.selected == (record("database", "数据库集成约束", "使用真实数据库。"),)
    assert len(context) == 1
    assert "使用真实数据库" in context[0].content
    assert "始终使用 Tab" not in context[0].content


def test_session_uses_chinese_bigram_fallback_after_selector_failure(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one", "two"))
    database = record("database", "生产数据库约束", "使用真实数据库。")
    interaction = record("interaction", "前端交互约束", "保持键盘可用。")
    store.extend((database, interaction))
    session = MemorySession(store, selector=FixedSelector(RuntimeError("离线")))

    session.begin_turn("检查数据库集成")

    assert session.selected == (database,)
    assert session.last_error == "记忆选择失败，已使用确定性关键词回退"


def test_session_extracts_from_a_history_copy(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("extracted"))
    extractor = FixedExtractor(
        '[{"name":"windows-only","type":"project",'
        '"description":"项目运行在 Windows", "body":"使用 PowerShell 命令。"}]'
    )
    session = MemorySession(store, extractor=extractor)
    history = (user_message("项目只用 Windows"), assistant_message("知道了"))

    session.complete(history)

    assert extractor.histories[0] is not history
    assert extractor.histories[0][0] is not history[0]
    assert store.records() == (
        record("windows-only", "项目运行在 Windows", "使用 PowerShell 命令。"),
    )
    assert session.last_error is None


def test_invalid_extraction_batch_does_not_commit_valid_prefix(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("unused"))
    extractor = FixedExtractor(
        '[{"name":"valid","type":"project","description":"有效", "body":"正文"},'
        '{"name":"../invalid","type":"project","description":"非法", "body":"正文"}]'
    )
    session = MemorySession(store, extractor=extractor)

    session.complete((user_message("记住"), assistant_message("完成")))

    assert store.records() == ()
    assert session.last_error == "记忆提取失败，旧记忆保持不变"


def test_consolidation_failure_keeps_old_collection(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one", "unused"))
    first = record("first")
    store.add(first)
    extractor = FixedExtractor(
        '[{"name":"second","type":"project","description":"第二条", "body":"第二条正文"}]'
    )
    consolidator = FixedConsolidator(RuntimeError("模型离线"))
    session = MemorySession(
        store, extractor=extractor, consolidator=consolidator, consolidate_threshold=2
    )

    session.complete((user_message("完成"), assistant_message("完成")))

    assert store.records() == (first,)
    assert session.last_error == "记忆整理失败，旧记忆保持不变"


def test_consolidation_replaces_only_named_sources(tmp_path: Path) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one", "two", "three", "merged"))
    first = record("first", "第一条", "一")
    second = record("second", "第二条", "二")
    unrelated = record("unrelated", "无关参考", "三", "reference")
    store.extend((first, second, unrelated))
    consolidator = FixedConsolidator(
        '{"source_names":["first","second"],"records":['
        '{"name":"merged","type":"project","description":"合并结果","body":"合并正文"}]}'
    )
    session = MemorySession(store, consolidator=consolidator, consolidate_threshold=2)

    session.complete((user_message("完成"), assistant_message("完成")))

    assert store.records() == (
        unrelated,
        record("merged", "合并结果", "合并正文"),
    )
    assert sorted(path.name for path in store.root.glob("*.md")) == [
        "MEMORY.md",
        "merged-merged.md",
        "unrelated-three.md",
    ]


@pytest.mark.parametrize(
    "output",
    [
        (
            '{"source_names":[],"records":[{"name":"merged","type":"project",'
            '"description":"合并","body":"正文"}]}'
        ),
        (
            '{"source_names":["unknown"],"records":[{"name":"merged","type":"project",'
            '"description":"合并","body":"正文"}]}'
        ),
        '{"source_names":["first"],"records":[]}',
    ],
)
def test_invalid_consolidation_plan_keeps_old_collection(tmp_path: Path, output: str) -> None:
    store = MemoryStore(str(tmp_path), id_generator=ids("one"))
    first = record("first")
    store.add(first)
    session = MemorySession(
        store, consolidator=FixedConsolidator(output), consolidate_threshold=1
    )

    session.complete((user_message("完成"), assistant_message("完成")))

    assert store.records() == (first,)
    assert session.last_error == "记忆整理失败，旧记忆保持不变"
