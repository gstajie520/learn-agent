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
    """动态 Prompt context 不是可稳定序列化的严格 JSON object。

    这是什么：context 参数校验失败时抛出的异常
    Java 类比：类似 ValidationException，表示输入不符合契约
    为什么需要：拒绝循环引用、NaN、非字符串键等不可序列化的值，保证缓存键稳定
    """


class SystemPromptProvider(Protocol):
    """零参数提示词提供者，类似 Java 的 ``Supplier<String>``。

    这是什么：定义 system prompt 提供者的契约接口
    Java 类比：Protocol = interface，类似 Supplier<String> 函数式接口
    为什么需要：AgentRunner 只依赖接口，不知道 Prompt 如何组装，测试时可替换 Fake
    """

    def render(self) -> str:
        """根据当前运行态返回本轮 system prompt。

        返回：完整的 system prompt 字符串（多 section 拼接后的结果）
        """


class DynamicPromptRenderer:
    """按固定顺序渲染 identity、tools、workspace、skills、memory。

    这是什么：无状态的 Prompt 渲染器，从运行态对象生成固定格式的 system prompt
    Java 类比：类似 View Renderer 或模板引擎，接收 DTO 返回字符串
    为什么需要：
        1. 感知运行态变化（工具/记忆/Skill 动态变化）
        2. 固定 section 顺序（identity 最高优先级）
        3. 实例级缓存（避免重复序列化）

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
        """返回此 Renderer 实例累计命中缓存的次数。

        用途：观测和测试，判断缓存是否生效
        Java 类比：getter 方法，@property 装饰器使其可以像字段一样访问
        """
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
        """读取当前运行态，生成固定顺序且可预测的 system prompt。

        这是什么：核心渲染方法，从运行态对象生成多 section Prompt
        Java 类比：类似模板方法，固定流程但部分内容可选
        为什么需要：每轮请求前重新读取最新状态，确保 Prompt 反映当前运行态

        固定顺序：identity → tools → workspace → skills（可选）→ memory（可选）

        参数：
            identity: Agent 身份说明（必需，放在最前）
            tools: 工具注册表（读取 tools.names 获取当前工具列表）
            workspace: 工作目录路径（会被 resolve 为绝对路径）
            context: 额外上下文（必须是严格 JSON object）
            skills: Skill 注册表（可选，读取 skills.render_catalog()）
            memory: 记忆会话（可选，读取 memory.render_selected()）

        返回：
            完整的 system prompt 字符串（各 section 用 \n\n 连接）

        缓存逻辑：
            基于所有输入生成稳定 JSON 键，与上次比对，相同则复用结果
        """
        normalized_identity = _normalize_identity(identity)
        if not isinstance(tools, ToolRegistry):
            raise TypeError("tools 必须是 ToolRegistry")
        if not isinstance(workspace, str) or not workspace.strip():
            raise TypeError("workspace 必须是非空字符串")
        if skills is not None and not isinstance(skills, SkillRegistry):
            raise TypeError("skills 必须是 SkillRegistry 或 None")
        if memory is not None and not isinstance(memory, MemorySession):
            raise TypeError("memory 必须是 MemorySession 或 None")

        # 标准化 context 为严格 JSON object（拒绝循环引用、NaN、非字符串键）
        normalized_context = _normalize_context(context)
        context_json = _stable_json(normalized_context)
        # 读取运行态对象的当前状态（不是快照，每次都重新读取）
        tool_names = tools.names
        resolved_workspace = str(Path(workspace).resolve())
        skill_catalog = "" if skills is None else skills.render_catalog()
        memory_body = (
            "" if memory is None or not memory.selected else memory.render_selected()
        )
        # 生成稳定缓存键：包含所有影响输出的输入（排序键保证稳定）
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
        # 缓存命中：相同输入复用上次结果
        if key == self._last_key and self._last_prompt is not None:
            self._cache_hits += 1
            return self._last_prompt

        # 缓存未命中：重新生成 Prompt
        tool_catalog = "(none)" if not tool_names else "\n".join(
            f"- {name}" for name in tool_names
        )
        # 固定顺序组装 section：identity → tools → workspace → skills → memory
        sections = [
            f"## identity\n{normalized_identity}\ncontext: {context_json}",
            f"## tools\n{tool_catalog}",
            f"## workspace\n{resolved_workspace}",
        ]
        if skill_catalog:  # 有 Skill 才添加此 section
            sections.append(f"## skills\n{skill_catalog}")
        if memory_body:  # 有选中记忆才添加此 section
            sections.append(f"## memory\n{memory_body}")
        prompt = "\n\n".join(sections)
        # 更新缓存
        self._last_key = key
        self._last_prompt = prompt
        return prompt


class DynamicPromptProvider:
    """把 Renderer 与本 Agent 的运行态对象绑定成零参数 Provider。

    这是什么：依赖注入容器，绑定 Renderer + 运行态对象后提供零参数接口
    Java 类比：构造器注入所有依赖后，``render()`` 类似一个无参数 Service 方法
    为什么需要：
        1. AgentRunner 只需要零参数接口（类似 Supplier<String>）
        2. 保存对象引用而非快照，每次读取最新状态
        3. 解耦 Renderer（无状态）和依赖绑定（有状态）

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
        """构造器注入所有依赖。

        这是什么：依赖注入，类似 Spring 的 @Autowired
        Java 类比：构造器接收所有依赖并保存为私有 final 字段
        为什么需要：一次性绑定，后续调用 render() 无需传参

        参数：
            renderer: 无状态 Renderer（可复用，多个 Provider 共享）
            identity: Agent 身份（字符串快照）
            tools: 工具注册表（引用传递，读取最新状态）
            workspace: 工作目录（字符串快照）
            context: 上下文对象（引用传递）
            skills: Skill 注册表（引用传递，可选）
            memory: 记忆会话（引用传递，可选）
        """
        if not isinstance(renderer, DynamicPromptRenderer):
            raise TypeError("renderer 必须是 DynamicPromptRenderer")
        self._renderer = renderer
        self._identity = identity
        self._tools = tools  # 引用传递：下一轮能读取新注册的工具
        self._workspace = workspace
        self._context = context
        self._skills = skills  # 引用传递：下一轮能读取新加载的 Skill
        self._memory = memory  # 引用传递：下一轮能读取新选中的记忆

    def render(self) -> str:
        """转发给 Renderer；每次调用都会重新读取工具和选中记忆。

        这是什么：零参数接口实现，符合 SystemPromptProvider 契约
        Java 类比：类似 Supplier<String>.get()，无参数返回字符串
        为什么需要：封装所有依赖，调用方无需知道 Prompt 如何组装

        返回：完整的 system prompt 字符串
        """
        return self._renderer.render(
            identity=self._identity,
            tools=self._tools,
            workspace=self._workspace,
            context=self._context,
            skills=self._skills,
            memory=self._memory,
        )


def _normalize_identity(identity: str) -> str:
    """校验并标准化 identity 字符串。

    这是什么：输入校验和清理
    Java 类比：类似 StringUtils.trimToNull() 后的非空检查
    为什么需要：identity 是最高优先级指令，不能为空或纯空白

    返回：去除首尾空白后的字符串
    抛出：TypeError 或 ValueError（不符合契约）
    """
    if not isinstance(identity, str):
        raise TypeError("identity 必须是字符串")
    normalized = identity.strip()
    if not normalized:
        raise ValueError("identity 不能为空")
    return normalized


def _normalize_context(context: object) -> dict[str, JsonValue]:
    """只接受普通 dict 作为根对象，并递归复制成规范 JSON 值。

    这是什么：严格 JSON 校验器，拒绝不可序列化的值
    Java 类比：类似深拷贝 + 类型校验，确保对象可以被 Jackson 序列化
    为什么需要：
        1. context 会被序列化作为缓存键，必须保证稳定性
        2. 拒绝循环引用、NaN/Infinity、非字符串键、自定义类实例

    返回：规范化的 JSON object（所有键已排序）
    抛出：PromptContextError（不符合严格 JSON）
    """
    if type(context) is not dict:
        raise PromptContextError("context 必须是 JSON object")
    normalized = _normalize_json_value(context, set())
    if not isinstance(normalized, dict):
        raise PromptContextError("context 必须是 JSON object")
    return normalized


def _normalize_json_value(value: object, active: set[int]) -> JsonValue:
    """递归拒绝非 JSON 值、非有限数字、非字符串键和循环引用。

    这是什么：递归 JSON 校验器，深度优先遍历整个对象树
    Java 类比：类似递归序列化校验，active 集合用于检测循环引用
    为什么需要：保证所有嵌套值都是 JSON 支持的基础类型

    参数：
        value: 待校验的 Python 对象
        active: 正在遍历的对象身份集合（用于检测循环引用）

    返回：规范化的 JSON 值（list 转 tuple，dict 键已排序）
    抛出：PromptContextError（不符合 JSON 规范）
    """
    # 基础类型：直接返回
    if value is None or isinstance(value, (bool, str)):
        return value
    # 整数：排除 bool（Python 中 bool 是 int 的子类）
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    # 浮点数：拒绝 NaN 和 Infinity
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PromptContextError("context 包含非有限 JSON 数字")
        return value
    # 数组：递归校验所有元素，转为 tuple（不可变）
    if type(value) in (list, tuple):
        identity = id(value)  # 对象身份哈希，类似 System.identityHashCode()
        if identity in active:  # 检测循环引用
            raise PromptContextError("context 包含循环 JSON array")
        active.add(identity)  # 标记为正在遍历
        try:
            sequence = cast(list[object] | tuple[object, ...], value)
            return tuple(_normalize_json_value(item, active) for item in sequence)
        finally:
            active.remove(identity)  # 遍历完成，移除标记
    # 对象：校验键为字符串，递归校验所有值，键排序后返回
    if type(value) is dict:
        identity = id(value)
        if identity in active:  # 检测循环引用
            raise PromptContextError("context 包含循环 JSON object")
        mapping = cast(dict[object, object], value)
        if not all(isinstance(key, str) for key in mapping):
            raise PromptContextError("context JSON object 的 key 必须是字符串")
        active.add(identity)
        try:
            return {
                cast(str, key): _normalize_json_value(mapping[key], active)
                for key in sorted(mapping, key=str)  # 排序键保证稳定性
            }
        finally:
            active.remove(identity)
    # 其他类型：拒绝（自定义类、函数、模块等）
    raise PromptContextError("context 包含 JSON 不支持的值")


def _json_compatible(value: JsonValue) -> object:
    """把内部不可变 tuple 转回 json.dumps 可识别的 list。

    这是什么：类型适配器，为 json.dumps() 准备数据
    Java 类比：类似 DTO 转换器，把内部表示转为 Jackson 可序列化的形式
    为什么需要：内部用 tuple 保证不可变，但 json.dumps() 需要 list

    返回：json.dumps() 可识别的对象（tuple → list 递归转换）
    """
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    return value


def _stable_json(value: JsonValue) -> str:
    """生成稳定的 JSON 字符串，用作缓存键。

    这是什么：稳定序列化器，相同内容总是生成相同字符串
    Java 类比：类似 ObjectMapper 配置为固定格式（键排序、无空格）
    为什么需要：作为缓存键必须保证稳定性，不同构建路径不影响结果

    配置：
        ensure_ascii=False: 保留 Unicode 字符（不转义为 \\uXXXX）
        allow_nan=False: 拒绝 NaN/Infinity（已在 _normalize_json_value 阶段拒绝）
        separators=(",", ":"): 紧凑格式，无空格
        sort_keys=True: 键排序，保证稳定性

    返回：紧凑且稳定的 JSON 字符串
    """
    return json.dumps(
        _json_compatible(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
