"""第七章按需加载 Skill。

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
    """Skill 领域错误的共同父类。"""


class SkillPathError(SkillError):
    """Skill 根目录、Skill 目录或 manifest 逃出了受控边界。"""


class SkillManifestError(SkillError):
    """SKILL.md 的 frontmatter 缺失、YAML 错误或字段不符合契约。"""


class DuplicateSkillError(SkillError):
    """多个目录声明了同一个 Skill 名称。"""


class SkillNameError(SkillError):
    """请求或 manifest 中的 Skill 名称不合法。"""


class SkillNotFoundError(SkillError):
    """名称格式正确，但当前注册表没有该 Skill。"""


@dataclass(frozen=True, slots=True)
class SkillSummary:
    """公开给模型的目录条目，只包含路由所需的两项元数据。"""

    name: str  # 稳定的工具路由名称，也必须等于目录名。
    description: str  # 一行路由说明，不包含 Skill 私有正文。


@dataclass(frozen=True, slots=True)
class _SkillRecord:
    """注册表内部记录；路径保存逻辑入口，加载时会重新解析真实路径。"""

    summary: SkillSummary  # 扫描阶段校验过的名称和描述。
    directory_name: str  # workspace/skills 下的目录名。
    directory_path: Path  # 逻辑目录入口，防止扫描后替换链接不被发现。
    manifest_path: Path  # 逻辑 SKILL.md 入口，加载时重新做 realpath 校验。


def _validate_skill_name(name: str) -> None:
    """校验名称到目录的映射，拒绝路径穿越和 Windows 设备名。"""
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
    """绑定一个 workspace 的 Skill 元数据注册表和 `load_skill` 工具。"""

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
        """扫描一级 Skill 目录，只解析 frontmatter 并建立不可变摘要。"""
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
        """重新检查路径并返回 frontmatter 后的正文。"""
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
