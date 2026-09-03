"""操作系统命令执行边界。

这是什么：命令执行的接口定义和结果对象
Java 类比：interface CommandRunner + record CommandResult
为什么需要：抽象命令执行细节，让核心代码不依赖具体的进程管理实现
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """操作系统命令执行后的统一结果。

    这是什么：命令执行结果的数据对象
    Java 类比：record CommandResult(String output, int exitCode, boolean timedOut, boolean truncated)
    为什么需要：封装命令执行的结果信息，避免直接暴露底层进程对象

    不直接返回 subprocess 对象，是为了让核心层不依赖具体操作系统 API。
    """

    output: str  # stdout 和 stderr 合并后的文本。
    exit_code: int  # 进程退出码，通常 0 表示成功。
    timed_out: bool  # 是否因为超过时间限制被终止。
    truncated: bool  # 输出是否超过上限并被截断。


class CommandRunner(Protocol):
    """命令执行接口；真实实现和测试 Fake 都遵守它。

    这是什么：命令执行器的协议接口
    Java 类比：interface CommandRunner
    为什么需要：定义命令执行的契约，支持依赖注入和测试替换

    Java 对照：这就是一个只有一个核心方法的 `interface`。AgentRunner
    只依赖这个接口，因此测试时可以传入不会真正启动 PowerShell 的 Fake。
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令，并返回与操作系统无关的结果对象。

        这是什么：命令执行方法
        Java 类比：CommandResult run(String command, String cwd, Integer timeoutMs)
        为什么需要：提供统一的命令执行接口，隔离平台差异
        """
