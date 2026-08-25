"""第十九章最小验收：真实 Git Worktree、claim 路由和安全删除。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_ch19.adapters.git import SubprocessGitRunner
from agent_ch19.adapters.task_sqlite import SqliteTaskStore
from agent_ch19.core.tools import ToolContext
from agent_ch19.features.tasks import CreateTaskInput
from agent_ch19.features.worktrees import WorktreeContextError, WorktreeRuntime, WorktreeStateError


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _components(tmp_path: Path) -> tuple[SqliteTaskStore, WorktreeRuntime]:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Agent Tutorial")
    _git(tmp_path, "config", "user.email", "agent@example.test")
    (tmp_path / ".gitignore").write_text(".agent_tutorial/\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "commit", "-m", "initial")
    store = SqliteTaskStore(tmp_path.as_posix())
    runtime = WorktreeRuntime(tmp_path.as_posix(), store, SubprocessGitRunner())
    runtime.validate_repository()
    return store, runtime


def test_create_claim_and_route_to_worktree(tmp_path: Path) -> None:
    store, runtime = _components(tmp_path)
    task = store.create_task(CreateTaskInput("alice task"))
    binding = runtime.create_worktree(task.id, "alice", "refs/heads/main")
    assert binding.status == "active"
    claim = runtime.claim_next("alice")
    assert claim is not None
    context = ToolContext(
        tmp_path.as_posix(), "alice", claim_token=claim.claim_token, execution_scope=object()
    )
    routed = runtime.resolve(context)
    assert Path(routed.workspace) == tmp_path / binding.relative_path
    assert routed.task_id == task.id


def test_failed_claim_never_falls_back_to_main_workspace(tmp_path: Path) -> None:
    store, runtime = _components(tmp_path)
    task = store.create_task(CreateTaskInput("alice task"))
    runtime.create_worktree(task.id, "alice", "refs/heads/main")
    claim = runtime.claim_next("alice")
    assert claim is not None
    runtime.complete_task(
        task.id,
        claim.claim_token,
        ToolContext(tmp_path.as_posix(), "alice", execution_scope=object()),
    )
    with pytest.raises(WorktreeContextError):
        runtime.resolve(
            ToolContext(
                tmp_path.as_posix(),
                "alice",
                claim_token=claim.claim_token,
                execution_scope=object(),
            )
        )


def test_remove_requires_completed_task(tmp_path: Path) -> None:
    store, runtime = _components(tmp_path)
    task = store.create_task(CreateTaskInput("not done"))
    runtime.create_worktree(task.id, "alice", "refs/heads/main")
    with pytest.raises(WorktreeStateError):
        runtime.remove_worktree(task.id)
