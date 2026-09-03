"""本地文件系统适配器。

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
    """把 Python 操作系统异常转换成稳定的领域异常。

    这是什么：异常转换器，将操作系统级异常映射为领域异常
    Java 类比：类似 catch (IOException e) { throw new DomainException(e); }
    为什么需要：屏蔽操作系统差异，让上层只需处理领域异常而非底层 OSError
    """
    if isinstance(error, FileNotFoundError):
        return error
    if getattr(error, "errno", None) == 2:  # errno 2 = ENOENT（文件不存在）
        return FileNotFoundError("文件或目录不存在")
    if getattr(error, "errno", None) in {20, 21}:  # 20=ENOTDIR, 21=EISDIR
        return InvalidFilePathError("路径指向了错误的文件类型")
    return FileSystemOperationError("文件系统操作失败")


def _is_windows_reserved(component: str) -> bool:
    """拒绝 Windows 设备名、非法字符和尾随空格/点。

    这是什么：Windows 保留名检测器
    Java 类比：类似 validator.isWindowsReservedName(String)
    为什么需要：防止创建 CON、NUL、COM1 等在 Windows 上无法操作的文件名
    """
    if component.endswith((" ", ".")):
        return True
    if any(ord(char) < 32 or char in '<>:"|*?' for char in component):
        return True
    stem = component.split(".", 1)[0].rstrip(" ").upper()
    if stem in _WINDOWS_DEVICE_NAMES:
        return True
    return len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789"


def _relative_parts(value: str, label: str, allow_wildcards: bool = False) -> list[str]:
    """把用户路径拆成安全相对组件；绝对路径和 `..` 永远拒绝。

    这是什么：路径安全解析器，将用户输入拆分为规范化的路径组件
    Java 类比：类似 Path.of(value).normalize() 但拒绝绝对路径和父目录跳转
    为什么需要：防止路径遍历攻击（如 ../../etc/passwd）和绝对路径逃逸工作区
    """
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
    """取得工作区真实目录，并拒绝把文件当成工作区。

    这是什么：工作区根目录解析器
    Java 类比：类似 File.getCanonicalFile() 并检查 isDirectory()
    为什么需要：确保工作区是一个真实存在的目录，而非文件或符号链接
    """
    try:
        root = Path(workspace).resolve(strict=True)
    except OSError as error:
        raise _translate_os_error(error) from error
    if not root.is_dir():
        raise InvalidFilePathError(f"工作区不是目录: {workspace}")
    return root


def safe_path(workspace: str, relative_path: str) -> Path:
    """解析工作区相对路径，并检查词法路径和真实路径都没有逃逸。

    这是什么：安全路径解析器，防止符号链接逃逸
    Java 类比：类似 workspace.resolve(relative).toRealPath() 并检查是否在边界内
    为什么需要：即使词法路径合法，符号链接也可能指向工作区外，必须同时检查两种路径
    """
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

    这是什么：文件系统适配器的具体实现
    Java 类比：类似 @Component class LocalFileSystemAdapter implements FileSystemPort
    为什么需要：将 Python pathlib 的底层调用封装为领域接口，便于测试时替换为内存实现
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """供权限策略在写入前检查真实路径边界。

        这是什么：路径边界检查器
        Java 类比：类似 boolean isWithinBoundary(Path workspace, Path target)
        为什么需要：权限系统在授权前需要快速判断路径是否合法，不能等到真正写入时才发现
        """
        try:
            safe_path(workspace, relative_path)
            return True
        except WorkspacePathError:
            return False

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取文本；超出 limit 时追加剩余行数提示。

        这是什么：带行数限制的文件读取器
        Java 类比：类似 Files.readString(path, UTF_8) 但会截断超长文件
        为什么需要：防止模型一次性读取巨大文件导致上下文溢出，同时告知模型还有多少行未显示
        """
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
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
        """创建父目录后写入 UTF-8 字节，并返回字节数。

        这是什么：带自动创建目录的文件写入器
        Java 类比：类似 Files.createDirectories(parent); Files.writeString(path, content, UTF_8)
        为什么需要：工具层不应要求用户先手动创建目录，自动创建提升易用性
        """
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
        """替换第一次精确文本；旧文本不存在时保证不写盘。

        这是什么：精确文本替换器
        Java 类比：类似 String.replaceFirst(oldText, newText) 但操作文件内容
        为什么需要：让模型能精确修改代码片段，不存在时拒绝写入可防止误操作
        """
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
        """遍历工作区并返回稳定排序的 POSIX 风格相对路径。

        这是什么：通配符文件搜索器
        Java 类比：类似 Files.walk(path).filter(PathMatcher) 但返回规范化路径
        为什么需要：让模型能搜索文件（如 "*.py"），同时防止符号链接逃逸工作区
        """
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
