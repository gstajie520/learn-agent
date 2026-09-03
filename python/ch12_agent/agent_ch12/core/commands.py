"""操作系统命令执行边界。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """操作系统命令执行后的统一结果。

    这是什么：命令执行的不可变返回值对象
    Java 类比：record CommandResult(String output, int exitCode, boolean timedOut, boolean truncated)
    为什么需要：不直接返回 subprocess 对象，让核心层不依赖具体操作系统 API

    参数：
        output: stdout 和 stderr 合并后的文本
        exit_code: 进程退出码，通常 0 表示成功
        timed_out: 是否因为超过时间限制被终止
        truncated: 输出是否超过上限并被截断
    """

    output: str  # stdout 和 stderr 合并后的文本。
    exit_code: int  # 进程退出码，通常 0 表示成功。
    timed_out: bool  # 是否因为超过时间限制被终止。
    truncated: bool  # 输出是否超过上限并被截断。


class CommandRunner(Protocol):
    """命令执行接口；真实实现和测试 Fake 都遵守它。

    这是什么：操作系统命令执行的抽象接口
    Java 类比：interface CommandRunner { CommandResult run(String cmd, String cwd); }
    为什么需要：AgentRunner 只依赖这个接口，测试时可以传入不会真正启动 PowerShell 的 Fake
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令，并返回与操作系统无关的结果对象。

        参数：
            command: 要执行的命令文本
            cwd: 命令的工作目录
            timeout_ms: 可选的超时时间（毫秒），None 表示使用默认值
        """
