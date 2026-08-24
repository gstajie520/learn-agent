"""第十章：从运行态对象动态组装模块化 system prompt。

Java 开发者可以这样理解：

* ``DynamicPromptRenderer`` 类似无副作用的 View Renderer；
* ``DynamicPromptProvider`` 类似绑定好依赖的 Adapter；
* ``AgentRunner`` 只依赖 Provider 接口，不知道 Skill、Memory 等具体数据源。

本章最重要的约束是：Prompt 只负责展示已有状态，不能重新实现工具发现、Skill 扫描
或记忆选择。每个 section 都必须从真正参与运行的对象读取。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, TypeAlias, cast

from ..core.tools import ToolRegistry
from .memory import MemorySession
from .skills import SkillRegistry

JsonScalar: TypeAlias = bool | int | float | str | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | dict[str, "JsonValue"]


class PromptContextError(Exception):
    """动态 Prompt context 不是可稳定序列化的严格 JSON object。"""


class SystemPromptProvider(Protocol):
    """零参数提示词提供者，类似 Java 的 ``Supplier<String>``。"""

    def render(self) -> str:
        """根据当前运行态返回本轮 system prompt。"""


class DynamicPromptRenderer:
    """按固定顺序渲染 identity、tools、workspace、skills、memory。

    字段说明：
        _last_key: 上一次所有模型可见输入的稳定 JSON 快照。
        _last_prompt: 与 ``_last_key`` 对应的最终字符串。
        _cache_hits: 相同输入复用实例缓存的次数，仅用于观测和测试。

    缓存放在实例字段而不是模块全局，因此两个 Agent 不会互相复用 Prompt。
    """

    def __init__(self) -> None:
        self._last_key: str | None = None
        self._last_prompt: str | None = None
        self._cache_hits = 0

    @property
    def cache_hits(self) -> int:
        """返回此 Renderer 实例累计命中缓存的次数。"""
        return self._cache_hits

    def render(
        self,
        *,
        identity: str,
        tools: ToolRegistry,
        workspace: str,
        context: Mapping[str, object],
        skills: SkillRegistry | None = None,
        memory: MemorySession | None = None,
    ) -> str:
        """读取当前运行态，生成固定顺序且可预测的 system prompt。"""
        normalized_identity = _normalize_identity(identity)
        if not isinstance(tools, ToolRegistry):
            raise TypeError("tools 必须是 ToolRegistry")
        if not isinstance(workspace, str) or not workspace.strip():
            raise TypeError("workspace 必须是非空字符串")
        if skills is not None and not isinstance(skills, SkillRegistry):
            raise TypeError("skills 必须是 SkillRegistry 或 None")
        if memory is not None and not isinstance(memory, MemorySession):
            raise TypeError("memory 必须是 MemorySession 或 None")

        normalized_context = _normalize_context(context)
        context_json = _stable_json(normalized_context)
        tool_names = tools.names
        resolved_workspace = str(Path(workspace).resolve())
        skill_catalog = "" if skills is None else skills.render_catalog()
        memory_body = (
            "" if memory is None or not memory.selected else memory.render_selected()
        )
        key = _stable_json(
            {
                "context": normalized_context,
                "identity": normalized_identity,
                "memory": memory_body,
                "skills": skill_catalog,
                "tools": tool_names,
                "workspace": resolved_workspace,
            }
        )
        if key == self._last_key and self._last_prompt is not None:
            self._cache_hits += 1
            return self._last_prompt

        tool_catalog = "(none)" if not tool_names else "\n".join(
            f"- {name}" for name in tool_names
        )
        sections = [
            f"## identity\n{normalized_identity}\ncontext: {context_json}",
            f"## tools\n{tool_catalog}",
            f"## workspace\n{resolved_workspace}",
        ]
        if skill_catalog:
            sections.append(f"## skills\n{skill_catalog}")
        if memory_body:
            sections.append(f"## memory\n{memory_body}")
        prompt = "\n\n".join(sections)
        self._last_key = key
        self._last_prompt = prompt
        return prompt


class DynamicPromptProvider:
    """把 Renderer 与本 Agent 的运行态对象绑定成零参数 Provider。

    Java 对照：构造器注入所有依赖后，``render()`` 类似一个无参数 Service 方法。
    ToolRegistry 和 MemorySession 保存的是对象引用，因此下一轮能读取它们的新状态。
    """

    def __init__(
        self,
        renderer: DynamicPromptRenderer,
        *,
        identity: str,
        tools: ToolRegistry,
        workspace: str,
        context: Mapping[str, object],
        skills: SkillRegistry | None = None,
        memory: MemorySession | None = None,
    ) -> None:
        if not isinstance(renderer, DynamicPromptRenderer):
            raise TypeError("renderer 必须是 DynamicPromptRenderer")
        self._renderer = renderer
        self._identity = identity
        self._tools = tools
        self._workspace = workspace
        self._context = context
        self._skills = skills
        self._memory = memory

    def render(self) -> str:
        """转发给 Renderer；每次调用都会重新读取工具和选中记忆。"""
        return self._renderer.render(
            identity=self._identity,
            tools=self._tools,
            workspace=self._workspace,
            context=self._context,
            skills=self._skills,
            memory=self._memory,
        )


def _normalize_identity(identity: str) -> str:
    if not isinstance(identity, str):
        raise TypeError("identity 必须是字符串")
    normalized = identity.strip()
    if not normalized:
        raise ValueError("identity 不能为空")
    return normalized


def _normalize_context(context: object) -> dict[str, JsonValue]:
    """只接受普通 dict 作为根对象，并递归复制成规范 JSON 值。"""
    if type(context) is not dict:
        raise PromptContextError("context 必须是 JSON object")
    normalized = _normalize_json_value(context, set())
    if not isinstance(normalized, dict):
        raise PromptContextError("context 必须是 JSON object")
    return normalized


def _normalize_json_value(value: object, active: set[int]) -> JsonValue:
    """递归拒绝非 JSON 值、非有限数字、非字符串键和循环引用。"""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PromptContextError("context 包含非有限 JSON 数字")
        return value
    if type(value) in (list, tuple):
        identity = id(value)
        if identity in active:
            raise PromptContextError("context 包含循环 JSON array")
        active.add(identity)
        try:
            sequence = cast(list[object] | tuple[object, ...], value)
            return tuple(_normalize_json_value(item, active) for item in sequence)
        finally:
            active.remove(identity)
    if type(value) is dict:
        identity = id(value)
        if identity in active:
            raise PromptContextError("context 包含循环 JSON object")
        mapping = cast(dict[object, object], value)
        if not all(isinstance(key, str) for key in mapping):
            raise PromptContextError("context JSON object 的 key 必须是字符串")
        active.add(identity)
        try:
            return {
                cast(str, key): _normalize_json_value(mapping[key], active)
                for key in sorted(mapping, key=str)
            }
        finally:
            active.remove(identity)
    raise PromptContextError("context 包含 JSON 不支持的值")


def _json_compatible(value: JsonValue) -> object:
    """把内部不可变 tuple 转回 json.dumps 可识别的 list。"""
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    return value


def _stable_json(value: JsonValue) -> str:
    return json.dumps(
        _json_compatible(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
