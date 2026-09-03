"""操作系统命令执行边界。

这是什么：定义命令执行的统一接口和返回值。
Java 类比：类似 ProcessExecutor interface 和 ProcessResult DTO。
为什么需要：Agent 循环不应直接依赖 subprocess，这样可以用 Fake 隔离测试。
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """操作系统命令执行后的统一结果。

    不直接返回 subprocess 对象，是为了让核心层不依赖具体操作系统 API。
    """
    output: str  # stdout 和 stderr 合并后的文本。
    exit_code: int  # 进程退出码，通常 0 表示成功。
    timed_out: bool  # 是否因为超过时间限制被终止。
    truncated: bool  # 输出是否超过上限并被截断。


class CommandRunner(Protocol):
    """命令执行接口；真实实现和测试 Fake 都遵守它。

    Java 对照：这就是一个只有一个核心方法的 `interface`。AgentRunner
    只依赖这个接口，因此测试时可以传入不会真正启动 PowerShell 的 Fake。
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令，并返回与操作系统无关的结果对象。"""
