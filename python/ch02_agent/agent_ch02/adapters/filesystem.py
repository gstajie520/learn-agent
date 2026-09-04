"""本地文件系统适配器。

这是什么：文件系统的基础设施层实现，封装 pathlib 和 os 操作
Java 类比：类似 @Repository class FileSystemAdapter implements WorkspaceFileSystem
为什么需要：隔离文件系统细节，提供安全边界检查，统一错误处理

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

_WINDOWS_DEVICE_NAMES = {"AUX", "CLOCK$", "CON", "CONIN$", "CONOUT$", "NUL", "PRN"}  # Windows 保留设备名


def _translate_os_error(error: OSError) -> Exception:
    """把 Python 操作系统异常转换成稳定的领域异常。

    这是什么：异常转换器，将底层 OSError 映射为领域异常
    Java 类比：类似异常转换工具类 static Exception translateException(IOException e)
    为什么需要：统一异常类型，让上层不依赖具体的 errno 码，提升可测试性
    """
    if isinstance(error, FileNotFoundError):  # 已经是领域异常，直接返回
        return error
    if getattr(error, "errno", None) == 2:  # errno 2 = ENOENT（文件不存在）
        return FileNotFoundError("文件或目录不存在")
    if getattr(error, "errno", None) in {20, 21}:  # errno 20/21 = EISDIR/ENOTDIR
        return InvalidFilePathError("路径指向了错误的文件类型")
    return FileSystemOperationError("文件系统操作失败")  # 其他 OS 错误统一包装


def _is_windows_reserved(component: str) -> bool:
    """拒绝 Windows 设备名、非法字符和尾随空格/点。

    这是什么：Windows 路径合法性检查器
    Java 类比：类似 static boolean isValidWindowsPath(String name)
    为什么需要：防止创建 CON、NUL 等特殊设备文件，避免跨平台问题
    """
    if component.endswith((" ", ".")):  # Windows 不允许文件名以空格或点结尾
        return True
    if any(ord(char) < 32 or char in '<>:"|*?' for char in component):  # 控制字符和非法字符
        return True
    stem = component.split(".", 1)[0].rstrip(" ").upper()  # 取扩展名前的主干
    if stem in _WINDOWS_DEVICE_NAMES:  # CON、NUL 等设备名
        return True
    return len(stem) == 4 and stem[:3] in {"COM", "LPT"} and stem[3] in "123456789"  # COM1-COM9、LPT1-LPT9


def _relative_parts(value: str, label: str, allow_wildcards: bool = False) -> list[str]:
    """把用户路径拆成安全相对组件；绝对路径和 `..` 永远拒绝。

    这是什么：路径安全解析器，拆分并验证路径组件
    Java 类比：类似 static List<String> parseRelativePath(String path, boolean allowWildcards)
    为什么需要：防止目录遍历攻击，拒绝绝对路径和父目录引用
    """
    if not value:  # 空路径直接拒绝
        raise WorkspacePathError(f"{label} 不能为空")
    normalized = value.replace("\\", "/")  # 统一使用 POSIX 风格斜杠
    if "\x00" in normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):  # 拒绝空字符、绝对路径、盘符
        raise WorkspacePathError(f"{label} 必须是相对路径，不能使用绝对路径")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]  # 过滤空片段和当前目录标记
    if ".." in parts:  # 拒绝父目录遍历
        raise WorkspacePathError(f"{label} 不能包含父目录片段 ..")
    for part in parts:  # 逐个检查路径组件
        if not allow_wildcards and _is_windows_reserved(part):  # glob 模式允许通配符
            raise WorkspacePathError(f"{label} 包含 Windows 保留路径组件: {part}")
        if any(ord(char) < 32 or char in '<>:"|' for char in part):  # 控制字符和非法字符
            raise WorkspacePathError(f"{label} 包含非法路径组件: {part}")
    return parts  # 返回安全的路径组件列表


def _workspace_root(workspace: str) -> Path:
    """取得工作区真实目录，并拒绝把文件当成工作区。

    这是什么：工作区根目录验证器
    Java 类比：类似 static Path validateWorkspaceRoot(String path) throws IOException
    为什么需要：确保工作区是真实存在的目录，避免后续操作基于无效的根路径
    """
    try:
        root = Path(workspace).resolve(strict=True)  # strict=True 要求路径必须存在
    except OSError as error:
        raise _translate_os_error(error) from error
    if not root.is_dir():  # 工作区必须是目录而非文件
        raise InvalidFilePathError(f"工作区不是目录: {workspace}")
    return root  # 返回规范化的绝对路径


def safe_path(workspace: str, relative_path: str) -> Path:
    """解析工作区相对路径，并检查词法路径和真实路径都没有逃逸。

    这是什么：双重边界检查的路径解析器（词法检查 + 物理检查）
    Java 类比：类似 static Path resolveSafePath(Path workspace, String relative) throws SecurityException
    为什么需要：防止符号链接绕过词法检查逃逸工作区，这是路径安全的核心防护
    """
    root = _workspace_root(workspace)  # 获取并验证工作区根目录
    parts = _relative_parts(relative_path, "路径")  # 词法检查：拆分并验证路径组件
    target = root.joinpath(*parts)  # 拼接成完整路径
    try:
        # 物理检查：找到目标路径或其最近已存在的父目录
        existing = target
        while not existing.exists() and existing != root:  # 向上查找直到找到存在的路径
            existing = existing.parent
        physical_parent = existing.resolve(strict=True)  # 解析符号链接得到真实路径
    except OSError as error:
        raise _translate_os_error(error) from error
    # 重新拼接：用真实父路径 + 剩余组件，得到最终物理路径
    candidate = physical_parent.joinpath(*target.relative_to(existing).parts).resolve()
    try:
        candidate.relative_to(root)  # 检查最终物理路径是否仍在工作区内
    except ValueError as error:  # relative_to 失败说明路径已逃逸
        raise WorkspacePathError(f"路径逃逸工作区: {relative_path}") from error
    return candidate  # 返回安全的绝对路径


class LocalWorkspaceFileSystem(WorkspaceFileSystem):
    """基于 pathlib 的真实工作区实现。

    这是什么：文件系统适配器的具体实现，封装 pathlib 操作
    Java 类比：类似 @Component class FileSystemAdapter implements FileSystem
    为什么需要：隔离底层文件系统细节，统一异常处理，方便测试时替换为内存实现
    """

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取文本；超出 limit 时追加剩余行数提示。

        这是什么：带行数限制的文本文件读取器
        Java 类比：类似 String readFile(Path workspace, String path, Integer limit) throws IOException
        为什么需要：防止大文件耗尽内存，支持预览功能，强制 UTF-8 编码保证文本一致性
        """
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):  # 验证 limit 类型和范围
            raise ValueError("limit 必须是正整数")
        try:
            target = safe_path(workspace, relative_path)  # 先做路径安全检查
            if not target.exists():  # 文件必须存在
                raise FileNotFoundError(f"文件不存在: {relative_path}")
            if not target.is_file():  # 必须是普通文件而非目录
                raise InvalidFilePathError(f"路径不是文件: {relative_path}")
            try:
                text = target.read_bytes().decode("utf-8")  # 强制 UTF-8 解码
            except UnicodeDecodeError as error:
                raise InvalidUtf8Error(f"文件不是合法 UTF-8: {relative_path}") from error
        except (WorkspacePathError, InvalidFilePathError, InvalidUtf8Error, FileNotFoundError):  # 领域异常直接抛出
            raise
        except OSError as error:  # 其他 OS 错误转换为领域异常
            raise _translate_os_error(error) from error
        lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()  # 统一换行符为 \n
        if limit is not None and limit < len(lines):  # 超出限制时截断并提示剩余行数
            return "\n".join([*lines[:limit], f"... ({len(lines) - limit} more lines)"])
        return "\n".join(lines)  # 返回完整或截断后的文本

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """创建父目录后写入 UTF-8 字节，并返回字节数。

        这是什么：文件写入器，自动创建缺失的父目录
        Java 类比：类似 int writeFile(Path workspace, String path, String content) throws IOException
        为什么需要：简化文件创建流程，避免手动创建目录，返回字节数便于统计和验证
        """
        try:
            target = safe_path(workspace, relative_path)  # 路径安全检查
            target.parent.mkdir(parents=True, exist_ok=True)  # 递归创建父目录，类似 mkdir -p
            data = content.encode("utf-8")  # 编码为 UTF-8 字节
            target.write_bytes(data)  # 写入文件
            return len(data)  # 返回写入的字节数
        except WorkspacePathError:  # 路径安全异常直接抛出
            raise
        except OSError as error:  # 其他 OS 错误转换为领域异常
            raise _translate_os_error(error) from error

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """替换第一次精确文本；旧文本不存在时保证不写盘。

        这是什么：精确文本替换器，只替换首次匹配
        Java 类比：类似 void replaceFirstOccurrence(Path file, String oldText, String newText) throws IOException
        为什么需要：避免全文件替换的误操作风险，找不到旧文本时快速失败，保证原子性
        """
        if not old_text:  # 空文本无法定位，直接拒绝
            raise ValueError("old_text 不能为空")
        target = safe_path(workspace, relative_path)  # 路径安全检查
        try:
            current = target.read_bytes().decode("utf-8")  # 读取当前文件内容
        except UnicodeDecodeError as error:
            raise InvalidUtf8Error(f"文件不是合法 UTF-8: {relative_path}") from error
        except OSError as error:
            raise _translate_os_error(error) from error
        if old_text not in current:  # 找不到旧文本时快速失败，不修改文件
            raise TextNotFoundError(f"文件中找不到精确文本: {relative_path}")
        updated = current.replace(old_text, new_text, 1)  # 只替换第一次出现，避免误改
        try:
            target.write_bytes(updated.encode("utf-8"))  # 写回文件
        except OSError as error:
            raise _translate_os_error(error) from error

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """遍历工作区并返回稳定排序的 POSIX 风格相对路径。

        这是什么：工作区文件匹配器，支持通配符模式
        Java 类比：类似 List<String> globFiles(Path workspace, String pattern) throws IOException
        为什么需要：提供安全的文件搜索能力，防止符号链接逃逸，保证结果顺序稳定便于测试
        """
        root = _workspace_root(workspace)  # 获取并验证工作区根目录
        parts = _relative_parts(pattern, "glob 模式", allow_wildcards=True)  # 允许通配符的路径解析
        normalized = "/".join(parts) if parts else "."  # 拼接为标准化模式
        # 第一个通配符之前是确定路径，必须先走 safe_path。
        # 例如 escape/*.txt 中 escape 若是指向工作区外的链接，应明确报错，
        # 不能因为遍历时跳过链接就伪装成"没有匹配"。
        literal_parts: list[str] = []  # 提取字面路径前缀
        for part in parts:
            if any(char in part for char in "*?["):  # 遇到通配符就停止
                break
            literal_parts.append(part)
        if literal_parts:  # 有字面前缀时先做路径安全检查
            safe_path(workspace, "/".join(literal_parts))
        results: list[str] = []  # 存储匹配结果
        for path in root.rglob("*"):  # 递归遍历工作区所有路径
            if path.is_symlink():  # 不跟随符号链接，避免 glob 递归到工作区外
                continue
            relative = path.relative_to(root).as_posix()  # 转为相对路径和 POSIX 格式
            matches = fnmatch.fnmatchcase(relative, normalized)  # 大小写敏感匹配
            # Python fnmatch 不把 `**/` 解释为"零层或多层目录"，
            # 因此额外尝试去掉前缀，保证 `**/*.txt` 也匹配根目录文件。
            if normalized.startswith("**/"):  # 特殊处理 **/ 前缀
                matches = matches or fnmatch.fnmatchcase(relative, normalized[3:])
            if path.is_file() and matches:  # 只收集匹配的文件（不包含目录）
                safe_path(workspace, relative)  # 再次验证结果路径的安全性
                results.append(relative)
        if not results and not any(char in normalized for char in "*?["):  # 无通配符且无结果时尝试直接匹配
            candidate = root / normalized
            if candidate.exists() and candidate.is_file():  # 如果是已存在的文件就返回
                results.append(normalized)
        return tuple(sorted(set(results)))  # 去重排序后返回不可变元组
