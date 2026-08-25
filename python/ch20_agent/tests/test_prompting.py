from pathlib import Path

import pytest

from agent_ch20.core.tools import ToolDefinition, ToolRegistry, tool_success
from agent_ch20.features.memory import MemoryRecord, MemorySession, MemoryStore
from agent_ch20.features.prompting import (
    DynamicPromptProvider,
    DynamicPromptRenderer,
    PromptContextError,
)
from agent_ch20.features.skills import SkillRegistry


def register_read_tool(tools: ToolRegistry, name: str) -> None:
    """注册最小只读工具，类似测试中的 Stub Handler。"""
    tools.register(
        ToolDefinition(
            name,
            f"执行 {name}",
            {"type": "object", "properties": {}, "additionalProperties": False},
            "read",
            lambda _arguments, _context: tool_success(name),
        )
    )


def write_skill(workspace: Path, name: str, description: str) -> None:
    directory = workspace / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# 私有正文\n",
        encoding="utf-8",
    )


class FixedSelector:
    def __init__(self, name: str) -> None:
        self.name = name

    def select(self, _query: str, _catalog: str) -> str:
        return f'["{self.name}"]'


def test_zero_argument_provider_reads_live_tool_state(tmp_path: Path) -> None:
    tools = ToolRegistry()
    renderer = DynamicPromptRenderer()
    provider = DynamicPromptProvider(
        renderer,
        identity="agent",
        tools=tools,
        workspace=str(tmp_path),
        context={"chapter": 10},
    )

    first = provider.render()
    register_read_tool(tools, "inspect")
    second = provider.render()

    assert "## tools\n(none)" in first
    assert "## tools\n- inspect" in second
    assert renderer.cache_hits == 0


def test_live_status_factory_is_reread_and_appended_after_memory(tmp_path: Path) -> None:
    """P20：status_provider 每轮重新读取，且状态段永远排在最后。"""
    tools = ToolRegistry()
    renderer = DynamicPromptRenderer()
    # connected 是被闭包捕获的可变局部变量，模拟运行态在两轮之间发生变化。
    # Java 对照：类似传入一个读取字段的 lambda，而不是传入字段当时的值。
    connected = False

    provider = DynamicPromptProvider(
        renderer,
        identity="agent",
        tools=tools,
        workspace=str(tmp_path),
        context={"chapter": 20},
        status_provider=lambda: {"mcp_connections": ["fake"] if connected else []},
    )

    first = provider.render()
    connected = True
    second = provider.render()

    assert '## runtime_status\n{"mcp_connections":[]}' in first
    assert '## runtime_status\n{"mcp_connections":["fake"]}' in second
    # 状态段必须在 tools 之后，且是整个 Prompt 的结尾，前面的稳定段落不因状态变化而重排。
    assert first.index("## runtime_status") > first.index("## tools")
    assert second.endswith('## runtime_status\n{"mcp_connections":["fake"]}')
    # 两次状态不同，因此都不能命中缓存；第三次状态未变才允许命中。
    assert renderer.cache_hits == 0
    assert provider.render() == second
    assert renderer.cache_hits == 1


def test_rejects_non_callable_status_provider(tmp_path: Path) -> None:
    """status_provider 必须是可调用对象，否则在构造阶段就失败。"""
    with pytest.raises(TypeError, match="status_provider"):
        DynamicPromptProvider(
            DynamicPromptRenderer(),
            identity="agent",
            tools=ToolRegistry(),
            workspace=str(tmp_path),
            context={},
            status_provider="not callable",  # type: ignore[arg-type]
        )


def test_renderer_outputs_fixed_sections_without_private_bodies(tmp_path: Path) -> None:
    tools = ToolRegistry()
    register_read_tool(tools, "read_file")
    register_read_tool(tools, "todo_write")
    write_skill(tmp_path, "sql-style", "SQL 编写规范")
    skills = SkillRegistry.scan(str(tmp_path))
    store = MemoryStore(str(tmp_path), id_generator=lambda: "one")
    store.extend(
        (
            MemoryRecord("database", "生产数据库约束", "project", "始终使用真实数据库。"),
            MemoryRecord("keyboard", "未选择的键盘说明", "project", "PRIVATE UNSELECTED MEMORY"),
        )
    )
    memory = MemorySession(store, selector=FixedSelector("database"))
    memory.begin_turn("检查数据库")

    prompt = DynamicPromptRenderer().render(
        identity="主智能体",
        tools=tools,
        workspace=str(tmp_path),
        skills=skills,
        memory=memory,
        context={"mode": "编码", "nested": {"b": 2, "a": 1}, "flags": [True, None, 1.5]},
    )

    assert prompt == (
        '## identity\n主智能体\ncontext: {"flags":[true,null,1.5],'
        '"mode":"编码","nested":{"a":1,"b":2}}\n\n'
        "## tools\n- read_file\n- todo_write\n\n"
        f"## workspace\n{tmp_path.resolve()}\n\n"
        "## skills\n- **sql-style**: SQL 编写规范\n\n"
        "## memory\n<relevant_memories>\n\n## database (project)\n\n"
        "生产数据库约束\n\n始终使用真实数据库。\n\n</relevant_memories>"
    )
    assert "私有正文" not in prompt
    assert "PRIVATE UNSELECTED MEMORY" not in prompt


def test_cache_uses_semantic_context_and_is_invalidated_by_live_state(tmp_path: Path) -> None:
    second_workspace = tmp_path / "second"
    second_workspace.mkdir()
    tools = ToolRegistry()
    register_read_tool(tools, "inspect")
    renderer = DynamicPromptRenderer()
    first = renderer.render(
        identity="agent",
        tools=tools,
        workspace=str(tmp_path),
        context={"b": [True, None, "中文"], "a": {"y": 2, "x": 1}},
    )
    same = renderer.render(
        identity="agent",
        tools=tools,
        workspace=str(tmp_path),
        context={"a": {"x": 1, "y": 2}, "b": [True, None, "中文"]},
    )
    register_read_tool(tools, "write_file")
    tools_changed = renderer.render(
        identity="agent", tools=tools, workspace=str(tmp_path), context={"a": 1}
    )
    workspace_changed = renderer.render(
        identity="agent", tools=tools, workspace=str(second_workspace), context={"a": 1}
    )

    assert same == first
    assert renderer.cache_hits == 1
    assert "- write_file" in tools_changed
    assert tools_changed != first
    assert str(second_workspace.resolve()) in workspace_changed


def test_cache_is_invalidated_when_skill_catalog_or_selected_memory_changes(
    tmp_path: Path,
) -> None:
    write_skill(tmp_path, "alpha", "Alpha 目录项")
    store = MemoryStore(str(tmp_path), id_generator=iter(("one", "two")).__next__)
    store.extend(
        (
            MemoryRecord("first-memory", "第一条记忆", "project", "first body"),
            MemoryRecord("second-memory", "第二条记忆", "project", "second body"),
        )
    )
    selector = FixedSelector("first-memory")
    memory = MemorySession(store, selector=selector)
    memory.begin_turn("第一次")
    renderer = DynamicPromptRenderer()
    tools = ToolRegistry()
    first = renderer.render(
        identity="agent",
        tools=tools,
        workspace=str(tmp_path),
        context={},
        skills=SkillRegistry.scan(str(tmp_path)),
        memory=memory,
    )
    write_skill(tmp_path, "beta", "Beta 目录项")
    skills_changed = renderer.render(
        identity="agent",
        tools=tools,
        workspace=str(tmp_path),
        context={},
        skills=SkillRegistry.scan(str(tmp_path)),
        memory=memory,
    )
    selector.name = "second-memory"
    memory.begin_turn("第二次")
    memory_changed = renderer.render(
        identity="agent",
        tools=tools,
        workspace=str(tmp_path),
        context={},
        skills=SkillRegistry.scan(str(tmp_path)),
        memory=memory,
    )

    assert "first body" in first
    assert "- **beta**: Beta 目录项" in skills_changed
    assert "second body" in memory_changed
    assert "first body" not in memory_changed
    assert renderer.cache_hits == 0


@pytest.mark.parametrize(
    "context",
    [
        ["根节点不能是数组"],
        {"value": object()},
        {"value": float("nan")},
        {1: "key 不是字符串"},
    ],
)
def test_invalid_context_does_not_poison_previous_cache(tmp_path: Path, context: object) -> None:
    renderer = DynamicPromptRenderer()
    tools = ToolRegistry()
    valid = renderer.render(identity="agent", tools=tools, workspace=str(tmp_path), context={})

    with pytest.raises(PromptContextError):
        renderer.render(
            identity="agent",
            tools=tools,
            workspace=str(tmp_path),
            context=context,  # type: ignore[arg-type]
        )

    assert (
        renderer.render(identity="agent", tools=tools, workspace=str(tmp_path), context={}) == valid
    )
    assert renderer.cache_hits == 1


def test_rejects_cyclic_context(tmp_path: Path) -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(PromptContextError, match="循环"):
        DynamicPromptRenderer().render(
            identity="agent",
            tools=ToolRegistry(),
            workspace=str(tmp_path),
            context=cyclic,
        )
