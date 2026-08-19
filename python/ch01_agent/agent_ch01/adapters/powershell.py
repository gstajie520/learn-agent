"""PowerShell 进程适配器。

这层相当于 Java 中的 ProcessBuilder 适配器：负责 cwd、超时、stdout/stderr
收集和输出上限，核心 Agent 不直接接触 subprocess。
"""

from dataclasses import dataclass
import subprocess

from ..core.commands import CommandResult, CommandRunner


@dataclass(frozen=True, slots=True)
class PowerShellRunner(CommandRunner):
    """CommandRunner 的真实 Windows 实现。"""
    executable: str = "powershell.exe"
    timeout_ms: int = 120_000
    output_limit: int = 50_000

    def __post_init__(self) -> None:
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        if self.output_limit <= 0:
            raise ValueError("output_limit must be a positive integer")

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """启动 PowerShell 子进程并把结果收敛成 CommandResult。"""
        if not command:
            raise ValueError("command must not be empty")

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
            output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").rstrip()
            truncated = len(output) > self.output_limit
            return CommandResult(output[: self.output_limit], completed.returncode, False, truncated)
        except subprocess.TimeoutExpired as error:
            # 超时异常中仍可能带有终止前已经产生的部分输出，不能直接丢掉。
            stdout = error.stdout or b""
            stderr = error.stderr or b""
            raw = stdout + stderr
            output = raw.decode("utf-8", errors="replace").rstrip()
            truncated = len(output) > self.output_limit
            return CommandResult(output[: self.output_limit], 1, True, truncated)
