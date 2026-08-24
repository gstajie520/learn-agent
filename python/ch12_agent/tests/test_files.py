from pathlib import Path

import pytest

from agent_ch12.adapters.filesystem import LocalWorkspaceFileSystem, safe_path
from agent_ch12.core.filesystem import (
    FileNotFoundError,
    InvalidFilePathError,
    InvalidUtf8Error,
    TextNotFoundError,
    WorkspacePathError,
)


def test_rejects_parent_absolute_and_reserved_paths(tmp_path: Path) -> None:
    with pytest.raises(WorkspacePathError):
        safe_path(str(tmp_path), "../secret.txt")
    with pytest.raises(WorkspacePathError):
        safe_path(str(tmp_path), str(tmp_path / "secret.txt"))
    with pytest.raises(WorkspacePathError):
        safe_path(str(tmp_path), "NUL")


def test_reads_writes_edits_and_globs_stably(tmp_path: Path) -> None:
    fs = LocalWorkspaceFileSystem()
    content = "你好 Agent\n第二行\n"
    assert fs.write_file(str(tmp_path), "nested/note.txt", content) == len(content.encode("utf-8"))
    fs.edit_file(str(tmp_path), "nested/note.txt", "你好", "您好")
    assert fs.read_file(str(tmp_path), "nested/note.txt", 1) == "您好 Agent\n... (1 more lines)"
    fs.write_file(str(tmp_path), "a.txt", "")
    assert fs.glob_files(str(tmp_path), "**/*.txt") == ("a.txt", "nested/note.txt")


def test_maps_missing_invalid_utf8_and_text_not_found(tmp_path: Path) -> None:
    fs = LocalWorkspaceFileSystem()
    with pytest.raises(FileNotFoundError):
        fs.read_file(str(tmp_path), "missing.txt")
    (tmp_path / "bad.txt").write_bytes(b"\xff")
    with pytest.raises(InvalidUtf8Error):
        fs.read_file(str(tmp_path), "bad.txt")
    fs.write_file(str(tmp_path), "note.txt", "keep")
    with pytest.raises(TextNotFoundError):
        fs.edit_file(str(tmp_path), "note.txt", "missing", "new")
    (tmp_path / "folder").mkdir()
    with pytest.raises(InvalidFilePathError):
        fs.read_file(str(tmp_path), "folder")
