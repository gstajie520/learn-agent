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

    这是什么：将底层 OSError 映射为业务层能识别的异常类型
    Java 类比：类似 catch (IOException e) 后根据 e.getClass() 重新抛出自定义异常
    为什么需要：避免核心逻辑直接依赖操作系统的 errno 编号，保持异常类型稳定
    """
    if isinstance(error, FileNotFoundError):
        return error
    if getattr(error, "errno", None) == 2:
        return FileNotFoundError("文件或目录不存在")
    if getattr(error, "errno", None) in {20, 21}:
        return InvalidFilePathError("路径指向了错误的文件类型")
    return FileSystemOperationError("文件系统操作失败")


def _is_windows_reserved(component: str) -> bool:
    """拒绝 Windows 设备名、非法字符和尾随空格/点。

    这是什么：检查路径组件是否触犯 Windows 文件名禁忌
    Java 类比：类似 Path.of(name).normalize() 前的预校验逻辑
    为什么需要：防止创建 CON、PRN 等设备文件导致程序卡死或系统异常
    """
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

    Java 对照：类似把内部校验方法提炼成 package-private/public utility，避免
    Skill 和文件工具各自维护一份容易漂移的规则。
    """
    return _is_windows_reserved(component)


def _relative_parts(value: str, label: str, allow_wildcards: bool = False) -> list[str]:
    """把用户路径拆成安全相对组件；绝对路径和 `..` 永远拒绝。

    这是什么：将用户输入的路径字符串拆分为安全的路径片段列表
    Java 类比：类似 Path.of(str).normalize().iterator() 后的逐段校验
    为什么需要：在文件系统操作前确保路径不会逃逸工作区或包含危险字符
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

    这是什么：将工作区路径解析为绝对路径并验证其为有效目录
    Java 类比：类似 Path.of(workspace).toRealPath().toFile().isDirectory()
    为什么需要：所有文件操作必须锚定在一个已验证的根目录下，防止操作错误的位置
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

    这是什么：将相对路径转换为安全的绝对路径并验证其在工作区边界内
    Java 类比：类似 workspace.resolve(relative).normalize() 后检查 startsWith(workspace)
    为什么需要：防止符号链接攻击，确保即使路径中含有软链接也不会逃出工作区
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

    这是什么：WorkspaceFileSystem 接口的生产环境实现
    Java 类比：类似 class LocalFileSystemAdapter implements FileSystemPort
    为什么需要：封装真实文件 I/O，让核心逻辑可以用内存 Fake 实现进行测试
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """供权限策略在写入前检查真实路径边界。

        这是什么：验证路径是否在工作区范围内的快速检查方法
        Java 类比：类似 boolean isWithinBoundary(Path workspace, String relative)
        为什么需要：权限系统需要在执行前判断路径合法性，不能等到写入时才报错
        """
        try:
            safe_path(workspace, relative_path)
            return True
        except WorkspacePathError:
            return False

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取文本；超出 limit 时追加剩余行数提示。

        这是什么：从工作区读取 UTF-8 文本文件，可选截断到指定行数
        Java 类比：类似 Files.readString(path, UTF_8).lines().limit(n).collect()
        为什么需要：避免一次性加载超大文件撑爆内存，同时告知模型还有多少内容未读
        """
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
        """创建父目录后写入 UTF-8 字节，并返回字节数。

        这是什么：将字符串内容写入工作区文件，自动创建所需的父目录
        Java 类比：类似 Files.createDirectories(parent); Files.writeString(path, content, UTF_8)
        为什么需要：简化文件创建逻辑，避免调用方手动处理目录不存在的情况
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

        这是什么：在文件中精确查找并替换第一次出现的文本片段
        Java 类比：类似 content.replaceFirst(Pattern.quote(old), new) 后写回文件
        为什么需要：确保替换操作的原子性，找不到目标文本时不修改文件避免数据损坏
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

        这是什么：在工作区内执行通配符模式匹配，返回所有符合条件的文件路径
        Java 类比：类似 Files.walk(root).filter(PathMatcher).sorted().toList()
        为什么需要：让模型能批量查找文件，同时确保不跟随符号链接防止逃逸工作区
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
