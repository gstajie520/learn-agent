"""操作系统命令执行边界。

Java 对照：`CommandRunner` 类似 interface，`CommandResult` 类似 record。
核心层通过接口调用 Shell，不依赖具体的 subprocess 或 PowerShell API。

这是什么：定义 Shell 工具的接口和返回值格式
为什么需要：隔离操作系统差异，让核心循环不关心是 PowerShell 还是 Bash
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)  # frozen=True 表示不可变返回值
class CommandResult:
    """操作系统命令执行后的统一结果。

    这是什么：Shell 命令的执行结果封装
    Java 类比：record CommandResult(String output, int exitCode, boolean timedOut, boolean truncated)
    为什么需要：不直接返回 subprocess 对象，避免核心层依赖具体操作系统 API

    不直接返回 subprocess 对象，是为了让核心层不依赖具体操作系统 API。
    """
    output: str  # stdout 和 stderr 合并后的文本，模型能直接阅读
    exit_code: int  # 进程退出码，通常 0 表示成功，非 0 表示失败
    timed_out: bool  # 是否因为超过时间限制被终止（防止无限运行）
    truncated: bool  # 输出是否超过上限并被截断（防止输出过大消耗 token）


class CommandRunner(Protocol):  # Protocol = Java 的 interface
    """命令执行接口；真实实现和测试 Fake 都遵守它。

    这是什么：定义 Shell 执行器的契约
    Java 类比：interface CommandRunner { CommandResult run(String command, String cwd, Integer timeoutMs); }
    为什么需要：核心循环只依赖接口，测试时可以注入不会真正启动 PowerShell 的 Fake

    Java 对照：这就是一个只有一个核心方法的 `interface`。AgentRunner
    只依赖这个接口，因此测试时可以传入不会真正启动 PowerShell 的 Fake。
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令，并返回与操作系统无关的结果对象。

        这是什么：执行一条 Shell 命令的方法
        Java 类比：CommandResult run(String command, String cwd, Integer timeoutMs)
        为什么需要：统一命令执行接口，支持工作目录隔离和超时保护

        参数：
            command: 要执行的 Shell 命令字符串
            cwd: 命令的工作目录，限制文件操作范围
            timeout_ms: 可选的超时毫秒数，None 表示使用默认值

        返回：
            CommandResult: 包含输出、退出码和执行状态的不可变对象
        """
        ...  # Protocol 接口方法，类似 Java 接口中的抽象方法声明
