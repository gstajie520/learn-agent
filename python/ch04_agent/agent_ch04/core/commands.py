"""操作系统命令执行边界。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """操作系统命令执行后的统一结果。

    这是什么：命令执行结果的值对象
    Java 类比：类似 record CommandResult(String output, int exitCode, boolean timedOut, boolean truncated)
    为什么需要：将 subprocess 的底层返回值封装为领域对象，让核心层不依赖操作系统 API
    """
    output: str  # stdout 和 stderr 合并后的文本。
    exit_code: int  # 进程退出码，通常 0 表示成功。
    timed_out: bool  # 是否因为超过时间限制被终止。
    truncated: bool  # 输出是否超过上限并被截断。


class CommandRunner(Protocol):
    """命令执行接口；真实实现和测试 Fake 都遵守它。

    这是什么：命令执行器的协议定义
    Java 类比：类似 interface CommandRunner { CommandResult run(...); }
    为什么需要：让核心层只依赖接口而非具体实现，测试时可注入不启动真实进程的 Fake
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令，并返回与操作系统无关的结果对象。

        这是什么：命令执行的抽象方法
        Java 类比：类似接口中的 CommandResult execute(String cmd, String workDir, Integer timeout)
        为什么需要：定义统一契约，屏蔽 Windows/Linux 差异和 subprocess 细节
        """
