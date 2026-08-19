"""操作系统命令执行边界。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """操作系统命令执行后的统一结果。

    不直接返回 subprocess 对象，是为了让核心层不依赖具体操作系统 API。
    """
    output: str
    exit_code: int
    timed_out: bool
    truncated: bool


class CommandRunner(Protocol):
    """命令执行接口；真实实现和测试 Fake 都遵守它。"""
    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令。"""
