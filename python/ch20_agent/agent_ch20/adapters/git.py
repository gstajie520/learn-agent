"""Git 外部适配器。

Java 对照：``SubprocessGitRunner`` 类似一个只负责调用 ``ProcessBuilder`` 的 Adapter。
它不理解业务状态，只返回退出码和两条输出流，领域层再决定成功含义。
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class GitExecutionError(RuntimeError):
    """Git 进程无法启动或超时。"""


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """一次 Git 调用的结构化结果。"""

    returncode: int
    stdout: str
    stderr: str


class SubprocessGitRunner:
    """不经过 shell 执行 Git，避免命令拼接注入。"""

    def run(self, arguments: Sequence[str], cwd: str) -> GitCommandResult:
        """在指定目录执行 Git；普通非零退出码作为结果返回。"""
        if not arguments or any(not isinstance(item, str) or not item for item in arguments):
            raise ValueError("Git 参数必须是非空字符串数组")
        path = Path(cwd).resolve(strict=True)
        if not path.is_dir():
            raise GitExecutionError("Git 工作目录不是目录")
        try:
            completed = subprocess.run(
                ["git", "--no-pager", *arguments],
                cwd=path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            raise GitExecutionError("Git 命令执行超时") from error
        except OSError as error:
            raise GitExecutionError("Git 进程启动失败") from error
        return GitCommandResult(completed.returncode, completed.stdout, completed.stderr)
