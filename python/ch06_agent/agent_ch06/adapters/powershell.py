"""PowerShell 进程适配器。

这是什么：实现 CommandRunner 接口，封装 PowerShell 命令执行
Java 类比：@Service class PowerShellRunner implements CommandRunner
为什么需要：隔离进程管理细节，提供超时控制和输出限制的统一接口

这层相当于 Java 中的 ProcessBuilder 适配器：负责 cwd、超时、stdout/stderr
收集和输出上限，核心 Agent 不直接接触 subprocess。
"""

import subprocess
from dataclasses import dataclass

from ..core.commands import CommandResult, CommandRunner


@dataclass(frozen=True, slots=True)
class PowerShellRunner(CommandRunner):
    """CommandRunner 的真实 Windows 实现。

    Java 对照：这相当于一个内部使用 `ProcessBuilder` 的实现类。
    dataclass 自动生成构造方法，下面三个字段就是构造参数和成员变量。
    """

    executable: str = "powershell.exe"  # 要启动的程序，类似 ProcessBuilder 的第一个参数。
    timeout_ms: int = 120_000  # 默认超时时间，单位毫秒；120_000 就是 120000。
    output_limit: int = 50_000  # stdout 和 stderr 合并后最多保留多少个字符。

    def __post_init__(self) -> None:
        """dataclass 构造完成后自动调用，用来校验构造参数。

        Java 对照：相当于在构造方法末尾执行参数检查。
        """
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms 必须是正整数")
        if self.output_limit <= 0:
            raise ValueError("output_limit 必须是正整数")

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """启动 PowerShell 子进程并把结果收敛成 CommandResult。

        参数：command 是命令文本；cwd 是工作目录；timeout_ms 可以覆盖默认超时。
        返回：不暴露 subprocess 对象，只返回核心层定义的 CommandResult。
        """
        if not command:
            raise ValueError("command 不能为空")

        # subprocess 使用秒，而项目配置使用毫秒，因此这里除以 1000。
        timeout_seconds = (timeout_ms if timeout_ms is not None else self.timeout_ms) / 1000

        # 明确要求 PowerShell 使用 UTF-8 输出，否则中文在不同 Windows 环境下容易乱码。
        script = "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); " + command
        try:
            # 类似 Java ProcessBuilder：参数使用列表传入，不再经过额外一层 shell 拆词。
            completed = subprocess.run(
                [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=cwd,
                capture_output=True,
                timeout=timeout_seconds,
                text=False,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            # stdout 是正常输出，stderr 是错误输出。两者都需要交回模型，因此合并保存。
            output = (
                (completed.stdout + completed.stderr).decode("utf-8", errors="replace").rstrip()
            )
            truncated = len(output) > self.output_limit
            return CommandResult(
                output[: self.output_limit], completed.returncode, False, truncated
            )
        except subprocess.TimeoutExpired as error:
            # 超时异常中仍可能带有终止前已经产生的部分输出，不能直接丢掉。
            stdout = error.stdout or b""
            stderr = error.stderr or b""
            raw = stdout + stderr
            output = raw.decode("utf-8", errors="replace").rstrip()
            truncated = len(output) > self.output_limit
            return CommandResult(output[: self.output_limit], 1, True, truncated)
