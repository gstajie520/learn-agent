"""本地文件系统适配器。

这是什么：
    本地文件系统的适配器实现，封装 pathlib/os 的细节并提供路径安全边界。

Java 类比：
    类似 Java 的基础设施适配器：把 `Files`/`Paths` 的细节藏起来，
    并在每次操作前检查工作区边界、符号链接和 Windows 保留路径名。

为什么需要：
    - 每次操作前检查工作区边界、符号链接和 Windows 保留路径名
    - 统一错误处理，将 OSError 转换为领域异常
    - 核心层通过 WorkspaceFileSystem 接口调用，不直接依赖 pathlib
    - 提供路径安全函数供其他模块（如 Skill）复用

这层相当于 Java 的基础设施适配器：把 `pathlib`/`os` 的细节藏起来，
并在每次操作前检查工作区边界、符号链接和 Windows 保留路径名。
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from ..core.filesystem import (
    FileNotFoundError,
    FileSystemOperationError,
    InvalidFilePathError,
    InvalidUtf8Error,
    TextNotFoundError,
    WorkspaceFileSystem,
    WorkspacePathError,
)

_WINDOWS_DEVICE_NAMES = {"AUX", "CLOCK$", "CON", "CONIN$", "CONOUT$", "NUL", "PRN"}


def _translate_os_error(error: OSError) -> Exception:
    """把 Python 操作系统异常转换成稳定的领域异常。"""
    if isinstance(error, FileNotFoundError):
        return error
    if getattr(error, "errno", None) == 2:
        return FileNotFoundError("文件或目录不存在")
    if getattr(error, "errno", None) in {20, 21}:
        return InvalidFilePathError("路径指向了错误的文件类型")
    return FileSystemOperationError("文件系统操作失败")


def _is_windows_reserved(component: str) -> bool:
    """拒绝 Windows 设备名、非法字符和尾随空格/点。"""
    if component.endswith((" ", ".")):
        return True
    if any(ord(char) < 32 or char in '<>:"|*?' for char in component):
        return True
    stem = component.split(".", 1)[0].rstrip(" ").upper()
    if stem in _WINDOWS_DEVICE_NAMES:
        return True
    return len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789"


def is_windows_reserved_component(component: str) -> bool:
    """公开给其他路径功能复用的 Windows 保留组件判断。

    这是什么：
        检查路径组件是否是 Windows 保留名称的公共函数。

    Java 类比：
        类似把内部校验方法提炼成 package-private/public utility，避免
        Skill 和文件工具各自维护一份容易漂移的规则。

    为什么需要：
        - 防止使用 Windows 设备名（NUL、CON、PRN、AUX 等）导致系统异常
        - 拒绝尾随空格/点、非法字符（<>:"|*?）
        - 供 Skill 路径校验等其他模块复用，保证规则一致性
    """
    return _is_windows_reserved(component)


def _relative_parts(value: str, label: str, allow_wildcards: bool = False) -> list[str]:
    """把用户路径拆成安全相对组件；绝对路径和 `..` 永远拒绝。"""
    if not value:
        raise WorkspacePathError(f"{label} 不能为空")
    normalized = value.replace("\\", "/")
    if "\x00" in normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise WorkspacePathError(f"{label} 必须是相对路径，不能使用绝对路径")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if ".." in parts:
        raise WorkspacePathError(f"{label} 不能包含父目录片段 ..")
    for part in parts:
        if not allow_wildcards and _is_windows_reserved(part):
            raise WorkspacePathError(f"{label} 包含 Windows 保留路径组件: {part}")
        if any(ord(char) < 32 or char in '<>:"|' for char in part):
            raise WorkspacePathError(f"{label} 包含非法路径组件: {part}")
    return parts


def _workspace_root(workspace: str) -> Path:
    """取得工作区真实目录，并拒绝把文件当成工作区。"""
    try:
        root = Path(workspace).resolve(strict=True)
    except OSError as error:
        raise _translate_os_error(error) from error
    if not root.is_dir():
        raise InvalidFilePathError(f"工作区不是目录: {workspace}")
    return root


def safe_path(workspace: str, relative_path: str) -> Path:
    """解析工作区相对路径，并检查词法路径和真实路径都没有逃逸。"""
    root = _workspace_root(workspace)
    parts = _relative_parts(relative_path, "路径")
    target = root.joinpath(*parts)
    try:
        existing = target
        while not existing.exists() and existing != root:
            existing = existing.parent
        physical_parent = existing.resolve(strict=True)
    except OSError as error:
        raise _translate_os_error(error) from error
    candidate = physical_parent.joinpath(*target.relative_to(existing).parts).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise WorkspacePathError(f"路径逃逸工作区: {relative_path}") from error
    return candidate


class LocalWorkspaceFileSystem(WorkspaceFileSystem):
    """基于 pathlib 的真实工作区实现。

    这是什么：
        实现 WorkspaceFileSystem 接口的本地文件系统适配器。

    Java 类比：
        class LocalWorkspaceFileSystem implements WorkspaceFileSystem
        类似适配器模式，将操作系统 API 适配到内部接口。

    为什么需要：
        - 实现核心层定义的文件系统接口（读、写、编辑、glob）
        - 每次操作前检查路径安全（工作区边界、符号链接）
        - 统一错误处理，转换为领域异常
        - 测试时可以注入 Fake，不需要真实文件系统
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """供权限策略在写入前检查真实路径边界。"""
        try:
            safe_path(workspace, relative_path)
            return True
        except WorkspacePathError:
            return False

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取文本；超出 limit 时追加剩余行数提示。"""
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0
        ):
            raise ValueError("limit 必须是正整数")
        try:
            target = safe_path(workspace, relative_path)
            if not target.exists():
                raise FileNotFoundError(f"文件不存在: {relative_path}")
            if not target.is_file():
                raise InvalidFilePathError(f"路径不是文件: {relative_path}")
            try:
                text = target.read_bytes().decode("utf-8")
            except UnicodeDecodeError as error:
                raise InvalidUtf8Error(f"文件不是合法 UTF-8: {relative_path}") from error
        except (WorkspacePathError, InvalidFilePathError, InvalidUtf8Error, FileNotFoundError):
            raise
        except OSError as error:
            raise _translate_os_error(error) from error
        lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        if limit is not None and limit < len(lines):
            return "\n".join([*lines[:limit], f"... ({len(lines) - limit} more lines)"])
        return "\n".join(lines)

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """创建父目录后写入 UTF-8 字节，并返回字节数。"""
        try:
            target = safe_path(workspace, relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = content.encode("utf-8")
            target.write_bytes(data)
            return len(data)
        except WorkspacePathError:
            raise
        except OSError as error:
            raise _translate_os_error(error) from error

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """替换第一次精确文本；旧文本不存在时保证不写盘。"""
        if not old_text:
            raise ValueError("old_text 不能为空")
        target = safe_path(workspace, relative_path)
        try:
            current = target.read_bytes().decode("utf-8")
        except UnicodeDecodeError as error:
            raise InvalidUtf8Error(f"文件不是合法 UTF-8: {relative_path}") from error
        except OSError as error:
            raise _translate_os_error(error) from error
        if old_text not in current:
            raise TextNotFoundError(f"文件中找不到精确文本: {relative_path}")
        updated = current.replace(old_text, new_text, 1)
        try:
            target.write_bytes(updated.encode("utf-8"))
        except OSError as error:
            raise _translate_os_error(error) from error

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """遍历工作区并返回稳定排序的 POSIX 风格相对路径。"""
        root = _workspace_root(workspace)
        parts = _relative_parts(pattern, "glob 模式", allow_wildcards=True)
        normalized = "/".join(parts) if parts else "."
        # 第一个通配符之前是确定路径，必须先走 safe_path。
        # 例如 escape/*.txt 中 escape 若是指向工作区外的链接，应明确报错，
        # 不能因为遍历时跳过链接就伪装成“没有匹配”。
        literal_parts: list[str] = []
        for part in parts:
            if any(char in part for char in "*?["):
                break
            literal_parts.append(part)
        if literal_parts:
            safe_path(workspace, "/".join(literal_parts))
        results: list[str] = []
        for path in root.rglob("*"):
            if path.is_symlink():
                # 不跟随符号链接，避免 glob 递归到工作区外。
                continue
            relative = path.relative_to(root).as_posix()
            matches = fnmatch.fnmatchcase(relative, normalized)
            # Python fnmatch 不把 `**/` 解释为“零层或多层目录”，
            # 因此额外尝试去掉前缀，保证 `**/*.txt` 也匹配根目录文件。
            if normalized.startswith("**/"):
                matches = matches or fnmatch.fnmatchcase(relative, normalized[3:])
            if path.is_file() and matches:
                safe_path(workspace, relative)
                results.append(relative)
        if not results and not any(char in normalized for char in "*?["):
            candidate = root / normalized
            if candidate.exists() and candidate.is_file():
                results.append(normalized)
        return tuple(sorted(set(results)))
