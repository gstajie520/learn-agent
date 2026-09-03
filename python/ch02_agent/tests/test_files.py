"""文件系统操作测试。

这是什么：文件系统适配器的单元测试
Java 类比：类似 FileSystemServiceTest 测试类
为什么需要：验证路径安全、文件读写编辑、错误映射等核心功能
"""

from pathlib import Path

import pytest

from agent_ch02.adapters.filesystem import LocalWorkspaceFileSystem, safe_path
from agent_ch02.core.filesystem import (
    FileNotFoundError,
    InvalidFilePathError,
    InvalidUtf8Error,
    TextNotFoundError,
    WorkspacePathError,
)


def test_rejects_parent_absolute_and_reserved_paths(tmp_path: Path) -> None:
    """验证拒绝父目录、绝对路径和保留路径。

    这是什么：路径安全验证测试用例
    Java 类比：类似 @Test void testPathSecurityValidation()
    为什么需要：确保路径验证阻止目录遍历攻击和访问保留设备名
    """
    with pytest.raises(WorkspacePathError):  # 父目录引用应被拒绝
        safe_path(str(tmp_path), "../secret.txt")
    with pytest.raises(WorkspacePathError):  # 绝对路径应被拒绝
        safe_path(str(tmp_path), str(tmp_path / "secret.txt"))
    with pytest.raises(WorkspacePathError):  # Windows 保留名应被拒绝
        safe_path(str(tmp_path), "NUL")


def test_reads_writes_edits_and_globs_stably(tmp_path: Path) -> None:
    """验证读写编辑和搜索操作的稳定性。

    这是什么：文件操作集成测试用例
    Java 类比：类似 @Test void testFileOperationsIntegration()
    为什么需要：验证文件系统的核心操作正确协作，包括 UTF-8 和嵌套路径
    """
    fs = LocalWorkspaceFileSystem()  # 创建文件系统实例
    content = "你好 Agent\n第二行\n"  # UTF-8 内容
    assert fs.write_file(str(tmp_path), "nested/note.txt", content) == len(content.encode("utf-8"))  # 写入返回字节数
    fs.edit_file(str(tmp_path), "nested/note.txt", "你好", "您好")  # 编辑中文内容
    assert fs.read_file(str(tmp_path), "nested/note.txt", 1) == "您好 Agent\n... (1 more lines)"  # 读取限制行数
    fs.write_file(str(tmp_path), "a.txt", "")  # 创建空文件
    assert fs.glob_files(str(tmp_path), "**/*.txt") == ("a.txt", "nested/note.txt")  # 递归搜索返回排序结果


def test_maps_missing_invalid_utf8_and_text_not_found(tmp_path: Path) -> None:
    """验证文件缺失、非 UTF-8 和文本未找到的错误映射。

    这是什么：文件系统错误处理测试用例
    Java 类比：类似 @Test void testFileSystemErrorMapping()
    为什么需要：确保各种文件错误正确映射为领域异常，便于上层统一处理
    """
    fs = LocalWorkspaceFileSystem()  # 创建文件系统实例
    with pytest.raises(FileNotFoundError):  # 读取不存在的文件
        fs.read_file(str(tmp_path), "missing.txt")
    (tmp_path / "bad.txt").write_bytes(b"\xff")  # 写入无效 UTF-8
    with pytest.raises(InvalidUtf8Error):  # 应该抛出 UTF-8 错误
        fs.read_file(str(tmp_path), "bad.txt")
    fs.write_file(str(tmp_path), "note.txt", "keep")  # 写入正常文件
    with pytest.raises(TextNotFoundError):  # 编辑时文本未找到
        fs.edit_file(str(tmp_path), "note.txt", "missing", "new")
    (tmp_path / "folder").mkdir()  # 创建目录
    with pytest.raises(InvalidFilePathError):  # 读取目录应报错
        fs.read_file(str(tmp_path), "folder")
