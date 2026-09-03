"""PowerShell 进程适配器。

这层相当于 Java 中的 ProcessBuilder 适配器：负责 cwd、超时、stdout/stderr
收集和输出上限，核心 Agent 不直接接触 subprocess。
"""

import subprocess
from dataclasses import dataclass

from ..core.commands import CommandResult, CommandRunner


@dataclass(frozen=True, slots=True)
class PowerShellRunner(CommandRunner):
    """CommandRunner 的真实 Windows 实现。

    这是什么：PowerShell 命令执行适配器，封装子进程管理
    Java 类比：类似 @Component class ProcessExecutor implements CommandRunner
    为什么需要：隔离 subprocess 细节，统一超时、编码和输出限制，方便测试时替换

    Java 对照：这相当于一个内部使用 `ProcessBuilder` 的实现类。
    dataclass 自动生成构造方法，下面三个字段就是构造参数和成员变量。
    """

    executable: str = "powershell.exe"  # 要启动的程序，类似 ProcessBuilder 的第一个参数。
    timeout_ms: int = 120_000  # 默认超时时间，单位毫秒；120_000 就是 120000。
    output_limit: int = 50_000  # stdout 和 stderr 合并后最多保留多少个字符。

    def __post_init__(self) -> None:
        """dataclass 构造完成后自动调用，用来校验构造参数。

        这是什么：dataclass 的后置初始化钩子，用于参数验证
        Java 类比：类似构造方法末尾的 validate() 调用
        为什么需要：在对象创建时就发现配置错误，避免运行时才暴露问题

        Java 对照：相当于在构造方法末尾执行参数检查。
        """
        if self.timeout_ms <= 0:  # 超时时间必须大于 0
            raise ValueError("timeout_ms 必须是正整数")
        if self.output_limit <= 0:  # 输出限制必须大于 0
            raise ValueError("output_limit 必须是正整数")

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """启动 PowerShell 子进程并把结果收敛成 CommandResult。

        这是什么：命令执行方法，启动子进程并收集结果
        Java 类比：类似 CommandResult execute(String command, String cwd, Integer timeout) throws IOException
        为什么需要：统一处理进程启动、超时、编码转换和输出截断，封装平台差异

        参数：command 是命令文本；cwd 是工作目录；timeout_ms 可以覆盖默认超时。
        返回：不暴露 subprocess 对象，只返回核心层定义的 CommandResult。
        """
        if not command:  # 空命令直接拒绝
            raise ValueError("command 不能为空")

        # subprocess 使用秒，而项目配置使用毫秒，因此这里除以 1000。
        timeout_seconds = (timeout_ms if timeout_ms is not None else self.timeout_ms) / 1000

        # 明确要求 PowerShell 使用 UTF-8 输出，否则中文在不同 Windows 环境下容易乱码。
        script = "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); " + command
        try:
            # 类似 Java ProcessBuilder：参数使用列表传入，不再经过额外一层 shell 拆词。
            completed = subprocess.run(
                [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],  # PowerShell 参数列表
                cwd=cwd,  # 工作目录
                capture_output=True,  # 捕获 stdout 和 stderr
                timeout=timeout_seconds,  # 超时时间（秒）
                text=False,  # 返回字节而非字符串，由我们自己处理编码
                check=False,  # 不因为非零退出码抛异常
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # Windows 下不弹出窗口
            )
            # stdout 是正常输出，stderr 是错误输出。两者都需要交回模型，因此合并保存。
            output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").rstrip()  # 合并输出并解码
            truncated = len(output) > self.output_limit  # 检查是否超出限制
            return CommandResult(output[: self.output_limit], completed.returncode, False, truncated)  # 返回结果对象
        except subprocess.TimeoutExpired as error:  # 处理超时异常
            # 超时异常中仍可能带有终止前已经产生的部分输出，不能直接丢掉。
            stdout = error.stdout or b""  # 获取已产生的 stdout
            stderr = error.stderr or b""  # 获取已产生的 stderr
            raw = stdout + stderr  # 合并输出
            output = raw.decode("utf-8", errors="replace").rstrip()  # 解码并去除尾随空白
            truncated = len(output) > self.output_limit  # 检查是否超出限制
            return CommandResult(output[: self.output_limit], 1, True, truncated)  # 返回超时结果，退出码为 1
