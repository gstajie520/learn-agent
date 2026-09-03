"""第七章按需加载 Skill。

这是什么：
    Skill（技能）系统的核心实现，提供两级加载机制：启动时扫描元数据，使用时加载正文。

Java 类比：
    SkillRegistry 类似 Spring 的只读配置注册表或路由注册表。
    scan() 类似 @PostConstruct 初始化方法，load_skill() 类似延迟加载的服务方法。

为什么需要：
    - System Prompt 长度受限，可能有几十个 Skill，全部加载会超出限制
    - 启动时只扫描 frontmatter（name + description），模型根据描述判断是否需要
    - 模型真正调用 load_skill 时才加载完整正文，节省 token 并提升响应速度
    - 提供严格的路径安全边界，防止路径穿越和符号链接逃逸（TOCTOU 防御）

Java 对照：`SkillRegistry` 类似一个只读的配置/路由注册表。启动时只读取
每个 `SKILL.md` 的 frontmatter，得到名称和描述；模型真正调用 `load_skill`
时才读取正文。这样 System Prompt 不会在启动时塞入所有技能说明。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..adapters.filesystem import is_windows_reserved_component
from ..core.tools import ToolContext, ToolDefinition, ToolResult, tool_error, tool_success

LOAD_SKILL_TOOL_NAME = "load_skill"
DEFAULT_SKILLS_DIRECTORY = "skills"
DEFAULT_MAX_CATALOG_ENTRIES = 100
DEFAULT_MAX_CATALOG_BYTES = 8_000
MAX_SKILL_NAME_LENGTH = 64
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillError(Exception):
    """Skill 领域错误的共同父类。

    这是什么：
        Skill 相关业务异常的基类，所有 Skill 领域错误都继承自它。

    Java 类比：
        class SkillException extends BusinessException
        自定义业务异常基类。

    为什么需要：
        - 让上层能统一捕获所有 Skill 相关错误
        - 区分业务错误和系统错误（如 IOError）
        - 便于异常处理的分层和归类
    """


class SkillPathError(SkillError):
    """Skill 根目录、Skill 目录或 manifest 逃出了受控边界。

    这是什么：
        路径安全边界被突破时抛出的异常，包括路径穿越、符号链接逃逸等。

    Java 类比：
        class PathTraversalException extends SkillException
        路径穿越攻击防御异常。

    为什么需要：
        - 防止攻击者通过 ..、绝对路径、符号链接访问 workspace 外的文件
        - 明确标识路径安全问题，便于安全审计
        - 让调用方能针对性处理路径相关错误
    """


class SkillManifestError(SkillError):
    """SKILL.md 的 frontmatter 缺失、YAML 错误或字段不符合契约。

    这是什么：
        Skill manifest 文件（SKILL.md）格式或内容不符合要求时抛出的异常。

    Java 类比：
        class InvalidManifestException extends SkillException
        配置文件格式错误异常。

    为什么需要：
        - frontmatter 必须是合法 YAML 且包含 name 和 description
        - name 必须等于目录名，description 必须是单行
        - 明确区分路径错误和内容格式错误，便于诊断
    """


class DuplicateSkillError(SkillError):
    """多个目录声明了同一个 Skill 名称。

    这是什么：
        扫描时发现重复的 Skill 名称时抛出的异常。

    Java 类比：
        class DuplicateRegistrationException extends SkillException
        Bean 重复注册异常。

    为什么需要：
        - Skill 名称必须唯一，用于工具路由
        - 防止名称冲突导致的不确定行为
        - 启动时就失败，而非运行时才发现重复
    """


class SkillNameError(SkillError):
    """请求或 manifest 中的 Skill 名称不合法。

    这是什么：
        Skill 名称不符合命名规范时抛出的异常。

    Java 类比：
        class InvalidNameException extends SkillException
        Bean Validation 校验失败异常。

    为什么需要：
        - 名称只能是 [a-z0-9-]，长度 1-64
        - 拒绝路径穿越字符、绝对路径和 Windows 设备名
        - 启动时和加载时都会校验名称合法性
    """


class SkillNotFoundError(SkillError):
    """名称格式正确，但当前注册表没有该 Skill。

    这是什么：
        模型请求的 Skill 名称合法但不存在时抛出的异常。

    Java 类比：
        class ResourceNotFoundException extends SkillException
        资源未找到异常。

    为什么需要：
        - 区分名称非法（SkillNameError）和名称不存在（SkillNotFoundError）
        - 让模型看到明确的错误信息，可以换一个 Skill 尝试
        - 便于诊断是拼写错误还是 Skill 真的未部署
    """


@dataclass(frozen=True, slots=True)
class SkillSummary:
    """公开给模型的目录条目，只包含路由所需的两项元数据。

    这是什么：
        Skill 的摘要信息，用于在 System Prompt 中展示可用 Skill 列表。

    Java 类比：
        record SkillSummary(String name, String description)
        类似 DTO，只包含最小必要字段。

    为什么需要：
        - 启动时只把这些摘要放进 System Prompt，不包含完整正文
        - 模型根据 name 和 description 判断是否需要调用 load_skill
        - 不可变设计（frozen=True）保证线程安全
    """

    name: str  # 稳定的工具路由名称，也必须等于目录名
    description: str  # 一行路由说明，不包含 Skill 私有正文


@dataclass(frozen=True, slots=True)
class _SkillRecord:
    """注册表内部记录；路径保存逻辑入口，加载时会重新解析真实路径。

    这是什么：
        SkillRegistry 内部使用的完整记录，包含路径信息用于加载时重新校验。

    Java 类比：
        类似内部领域对象，只在 SkillRegistry 内部使用，不暴露给外部。

    为什么需要：
        - 保存逻辑路径（directory_path、manifest_path），加载时重新 realpath
        - 防止 TOCTOU 攻击：扫描后符号链接可能被替换，加载时重新校验真实路径
        - 记录 directory_name 用于验证 name 与目录名一致性
    """

    summary: SkillSummary  # 扫描阶段校验过的名称和描述
    directory_name: str  # workspace/skills 下的目录名
    directory_path: Path  # 逻辑目录入口，防止扫描后替换链接不被发现
    manifest_path: Path  # 逻辑 SKILL.md 入口，加载时重新做 realpath 校验


def _validate_skill_name(name: str) -> None:
    """校验名称到目录的映射，拒绝路径穿越和 Windows 设备名。

    这是什么：
        Skill 名称的严格校验函数，确保名称安全且符合命名规范。

    Java 类比：
        类似 Bean Validation 的自定义校验器，在数据进入系统前执行边界检查。

    为什么需要：
        - 只允许 [a-z0-9-]，防止 ../secret、绝对路径等路径穿越攻击
        - 拒绝 Windows 设备名（NUL、CON、PRN 等），避免系统异常
        - 长度限制（1-64 字符），防止超长名称导致的问题
    """
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= MAX_SKILL_NAME_LENGTH
        or SKILL_NAME_PATTERN.fullmatch(name) is None
        or is_windows_reserved_component(name)
    ):
        raise SkillNameError(f"Skill 名称不合法: {name}")


def _validate_skill_input(value: Mapping[str, Any]) -> bool:
    """`load_skill` 只允许一个非空、格式安全的 name 字段。"""
    if set(value) != {"name"} or not isinstance(value.get("name"), str):
        return False
    try:
        _validate_skill_name(value["name"])
    except SkillNameError:
        return False
    return True


def _workspace_root(workspace: str) -> Path:
    """取得 workspace 的真实目录，类似 Java 中的受控根目录解析器。"""
    try:
        root = Path(workspace).resolve(strict=True)
    except OSError as error:
        raise SkillPathError("工作区不存在或无法解析") from error
    if not root.is_dir():
        raise SkillPathError("工作区不是目录")
    return root


def _is_inside(root: Path, candidate: Path) -> bool:
    """用 Path.relative_to 判断包含关系，避免字符串前缀误判。"""
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _checked_real_directory(path: Path, root: Path, message: str) -> Path:
    """realpath 后确认目标仍是 root 内的真实目录。"""
    try:
        physical = path.resolve(strict=True)
    except OSError as error:
        raise SkillPathError(message) from error
    if not physical.is_dir() or not _is_inside(root, physical):
        raise SkillPathError(message)
    return physical


def _checked_real_file(path: Path, root: Path, message: str) -> Path:
    """realpath 后确认目标仍是 root 内的真实文件。"""
    try:
        physical = path.resolve(strict=True)
    except OSError as error:
        raise SkillPathError(message) from error
    if not physical.is_file() or not _is_inside(root, physical):
        raise SkillPathError(message)
    return physical


def _resolve_skill_root(workspace_root: Path, skills_directory: str) -> Path:
    """只允许 workspace 内的相对 skills 目录。"""
    if not isinstance(skills_directory, str) or not skills_directory or "\x00" in skills_directory:
        raise SkillPathError("Skills 目录必须是非空相对路径")
    normalized = skills_directory.replace("\\", "/")
    if normalized.startswith("/") or re.fullmatch(r"[A-Za-z]:.*", normalized):
        raise SkillPathError("Skills 目录必须是相对 workspace 的路径")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        raise SkillPathError("Skills 目录不能包含父目录片段 ..")
    if any(is_windows_reserved_component(part) for part in parts):
        raise SkillPathError("Skills 目录包含 Windows 保留路径组件")
    target = workspace_root.joinpath(*parts)
    if target.exists() and not _is_inside(workspace_root, target.resolve()):
        raise SkillPathError("Skills 目录逃逸 workspace")
    return target


def _read_frontmatter(path: Path) -> str:
    """只返回 frontmatter 字节对应的文本，不解码正文。

    这里先读 bytes，再在第二个独立的 `---` 行处截断；因此正文即使含有非法
    UTF-8，扫描阶段也不会失败，真正加载正文时才会严格解码。
    """
    selected: list[bytes] = []
    with path.open("rb") as manifest:
        for line in manifest:
            selected.append(line)
            if len(selected) > 1 and line.rstrip(b"\r\n") == b"---":
                break
    try:
        return b"".join(selected).decode("utf-8")
    except UnicodeDecodeError as error:
        raise SkillManifestError("Skill manifest 的 frontmatter 不是合法 UTF-8") from error


def _parse_document(text: str, source: Path) -> tuple[SkillSummary, str]:
    """解析完整 SKILL.md，返回元数据和 frontmatter 后的原始正文。"""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise SkillManifestError("SKILL.md 必须以 YAML frontmatter 开始")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing_index is None:
        raise SkillManifestError("SKILL.md 缺少 frontmatter 结束分隔符")
    try:
        metadata = yaml.safe_load("".join(lines[1:closing_index]))
    except yaml.YAMLError as error:
        raise SkillManifestError("Skill frontmatter 不是合法 YAML") from error
    if not isinstance(metadata, dict):
        raise SkillManifestError("Skill frontmatter 必须是对象")
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not isinstance(description, str):
        raise SkillManifestError("Skill frontmatter 必须包含字符串 name 和 description")
    try:
        _validate_skill_name(name)
    except SkillNameError as error:
        raise SkillManifestError("Skill frontmatter 中的 name 不合法") from error
    normalized_description = description.strip()
    if (
        not normalized_description
        or "\n" in normalized_description
        or "\r" in normalized_description
    ):
        raise SkillManifestError("Skill description 必须是非空单行文本")
    return SkillSummary(name, normalized_description), "".join(lines[closing_index + 1 :])


def _bounded_catalog(
    records: list[_SkillRecord], max_entries: int, max_bytes: int
) -> tuple[SkillSummary, ...]:
    """按条目数和 UTF-8 字节预算截断，但不截断半条目录行。"""
    result: list[SkillSummary] = []
    used = 0
    for record in sorted(records, key=lambda item: item.summary.name):
        if len(result) >= max_entries:
            break
        line = f"- **{record.summary.name}**: {record.summary.description}"
        entry_bytes = len(line.encode("utf-8")) + (1 if result else 0)
        if used + entry_bytes > max_bytes:
            break
        result.append(record.summary)
        used += entry_bytes
    return tuple(result)


class SkillRegistry:
    """绑定一个 workspace 的 Skill 元数据注册表和 `load_skill` 工具。

    这是什么：
        Skill 系统的核心注册表，管理 Skill 的扫描、目录生成和按需加载。

    Java 类比：
        类似 Spring 的 Configuration 注册表 + Bean 工厂，扫描配置并提供加载方法。

    为什么需要：
        - 集中管理所有 Skill 的元数据和加载逻辑
        - 提供 load_skill 工具定义，让模型能调用 Skill
        - 扫描和加载都检查路径安全，防止路径穿越和符号链接逃逸
        - 不可变设计（扫描后冻结），保证线程安全
    """

    def __init__(
        self,
        workspace_root: Path,
        skills_root: Path,
        records: dict[str, _SkillRecord],
        catalog_entries: tuple[SkillSummary, ...],
    ) -> None:
        self._workspace_root = workspace_root  # 所有 Skill 路径的最高信任边界。
        self._skills_root = skills_root  # workspace 下的 skills 根目录。
        self._records = dict(records)  # 内部完整记录，模型只能看到摘要。
        self.names = tuple(sorted(records))  # 稳定名称快照，便于测试和日志。
        self.catalog_entries = catalog_entries  # 已应用预算的公开摘要快照。
        self.tool_definition = ToolDefinition(
            LOAD_SKILL_TOOL_NAME,
            "加载当前 workspace catalog 中指定 Skill 的完整说明。",
            {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_SKILL_NAME_LENGTH,
                        "pattern": SKILL_NAME_PATTERN.pattern,
                    }
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            "read",
            self._handle_load,
            _validate_skill_input,
        )

    @classmethod
    def scan(
        cls,
        workspace: str,
        *,
        skills_directory: str = DEFAULT_SKILLS_DIRECTORY,
        max_catalog_entries: int = DEFAULT_MAX_CATALOG_ENTRIES,
        max_catalog_bytes: int = DEFAULT_MAX_CATALOG_BYTES,
    ) -> SkillRegistry:
        """扫描一级 Skill 目录，只解析 frontmatter 并建立不可变摘要。

        这是什么：
            类工厂方法，在启动时扫描 skills/ 目录并创建不可变的 SkillRegistry。

        Java 类比：
            static SkillRegistry scan(String workspace) 类工厂方法
            类似 Spring 的 @PostConstruct 初始化逻辑。

        为什么需要：
            - 启动时只读取每个 SKILL.md 的 frontmatter（name + description）
            - 不读取完整正文，避免 System Prompt 过长
            - 应用目录预算（最多 100 条、8000 字节），不截断半条目录行
            - 返回不可变注册表，保证线程安全
        """
        if (
            isinstance(max_catalog_entries, bool)
            or not isinstance(max_catalog_entries, int)
            or max_catalog_entries <= 0
        ):
            raise ValueError("max_catalog_entries 必须是正整数")
        if (
            isinstance(max_catalog_bytes, bool)
            or not isinstance(max_catalog_bytes, int)
            or max_catalog_bytes <= 0
        ):
            raise ValueError("max_catalog_bytes 必须是正整数")
        workspace_root = _workspace_root(workspace)
        skills_path = _resolve_skill_root(workspace_root, skills_directory)
        if not skills_path.exists():
            return cls(workspace_root, skills_path, {}, ())
        skills_root = _checked_real_directory(
            skills_path, workspace_root, "Skills 目录逃逸 workspace"
        )
        discovered: list[_SkillRecord] = []
        records: dict[str, _SkillRecord] = {}
        for entry in sorted(skills_root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir() and not entry.is_symlink():
                continue
            directory_real = _checked_real_directory(entry, skills_root, "Skill 目录逃逸 Skills 根")
            manifest = entry / "SKILL.md"
            if not manifest.exists():
                continue
            manifest_real = _checked_real_file(manifest, directory_real, "Skill manifest 逃逸目录")
            summary, _body = _parse_document(_read_frontmatter(manifest_real), manifest_real)
            if summary.name in records:
                raise DuplicateSkillError(f"Skill 名称重复: {summary.name}")
            record = _SkillRecord(summary, entry.name, entry, manifest)
            records[summary.name] = record
            discovered.append(record)
        for record in discovered:
            if record.summary.name != record.directory_name:
                raise SkillManifestError("Skill name 必须与目录名一致")
        catalog = _bounded_catalog(list(records.values()), max_catalog_entries, max_catalog_bytes)
        return cls(workspace_root, skills_root, records, catalog)

    def render_catalog(self) -> str:
        """渲染只含名称和描述的目录，不读取正文。"""
        return "\n".join(
            f"- **{entry.name}**: {entry.description}" for entry in self.catalog_entries
        )

    def load_skill(self, name: str) -> str:
        """重新检查路径并返回 frontmatter 后的正文。

        这是什么：
            按名称加载 Skill 完整正文的方法，模型调用 load_skill 工具时触发。

        Java 类比：
            String loadSkill(String name) 延迟加载方法
            类似 Service 层的业务方法。

        为什么需要：
            - 模型根据目录中的 description 判断需要哪个 Skill 后调用
            - 重新校验路径安全（防止扫描后符号链接被替换）
            - 读取完整正文（frontmatter 后的内容）并返回给模型
            - TOCTOU 防御：扫描时安全不代表加载时仍然安全
        """
        _validate_skill_name(name)
        record = self._records.get(name)
        if record is None:
            raise SkillNotFoundError(f"Skill 不存在: {name}")
        current_root = _checked_real_directory(
            self._skills_root, self._workspace_root, "Skills 目录已逃逸 workspace"
        )
        current_directory = _checked_real_directory(
            record.directory_path, current_root, "Skill 目录已逃逸 Skills 根"
        )
        current_manifest = _checked_real_file(
            record.manifest_path, current_directory, "Skill manifest 已逃逸目录"
        )
        try:
            document = current_manifest.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillManifestError("Skill manifest 不是合法 UTF-8") from error
        summary, body = _parse_document(document, current_manifest)
        if summary.name != record.summary.name or summary.name != record.directory_name:
            raise SkillManifestError("Skill name 必须与目录名一致")
        return body

    def _handle_load(self, arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """校验 ToolContext 属于本注册表后，把领域错误映射成稳定工具结果。"""
        try:
            context_workspace = _workspace_root(context.workspace)
        except SkillPathError:
            return tool_error("skill_workspace_error", "当前工作区无法解析")
        if context_workspace != self._workspace_root:
            return tool_error("skill_workspace_mismatch", "Skill 注册表属于另一个工作区")
        try:
            return tool_success(self.load_skill(str(arguments["name"])))
        except SkillNotFoundError:
            return tool_error("skill_not_found", "请求的 Skill 未注册")
        except SkillPathError:
            return tool_error("skill_path_escape", "已注册 Skill 的路径不再安全")
        except SkillManifestError:
            return tool_error("invalid_skill", "已注册 Skill 的清单无效")
        except Exception:  # noqa: BLE001
            return tool_error("skill_load_error", "Skill 无法加载")
