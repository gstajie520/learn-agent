"""操作系统命令执行边界。

这是什么：命令执行的抽象接口定义
Java 类比：类似定义 CommandExecutor 接口和结果 DTO
为什么需要：让核心层不依赖具体操作系统 API，便于测试和跨平台
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """操作系统命令执行后的统一结果。

    这是什么：命令执行的结果数据对象
    Java 类比：类似 record CommandResult(String output, int exitCode, boolean timedOut, ...)
    为什么需要：不直接返回 subprocess 对象，让核心层不依赖具体操作系统 API

    参数：
        output: stdout 和 stderr 合并后的文本
        exit_code: 进程退出码，通常 0 表示成功
        timed_out: 是否因为超过时间限制被终止
        truncated: 输出是否超过上限并被截断
    """

    output: str  # 命令输出
    exit_code: int  # 退出码
    timed_out: bool  # 是否超时
    truncated: bool  # 是否截断


class CommandRunner(Protocol):
    """命令执行接口；真实实现和测试 Fake 都遵守它。

    这是什么：命令执行器的抽象接口
    Java 类比：interface CommandRunner { CommandResult run(String cmd, String cwd, Integer timeout); }
    为什么需要：AgentRunner 只依赖这个接口，测试时可以传入不会真正启动 PowerShell 的 Fake
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令，并返回与操作系统无关的结果对象。

        这是什么：命令执行的核心方法
        Java 类比：类似 CommandResult execute(String command, String workDir, Integer timeout)
        为什么需要：定义统一的命令执行契约

        参数：
            command: 要执行的命令字符串
            cwd: 工作目录（命令在此目录下执行）
            timeout_ms: 超时时间（毫秒），None 表示无限制

        返回：
            CommandResult: 命令执行结果对象
        """
