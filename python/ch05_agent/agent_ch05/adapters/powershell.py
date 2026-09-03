"""PowerShell 进程适配器。

这层相当于 Java 中的 ProcessBuilder 适配器：负责 cwd、超时、stdout/stderr
收集和输出上限，核心 Agent 不直接接触 subprocess。

Java 对照：这是对 subprocess.run 的封装，类似 Java 中实现 CommandRunner 接口
的 PowerShellProcessAdapter 类。

这是什么：真实 PowerShell 命令执行器
为什么需要：核心循环不依赖 subprocess 细节，所有进程管理在此层处理
"""

import subprocess
from dataclasses import dataclass

from ..core.commands import CommandResult, CommandRunner


@dataclass(frozen=True, slots=True)  # frozen=True 表示字段不可变
class PowerShellRunner(CommandRunner):
    """CommandRunner 的真实 Windows 实现。

    这是什么：启动 PowerShell 子进程并收集结果的适配器
    Java 类比：class PowerShellRunner implements CommandRunner (使用 ProcessBuilder)
    为什么需要：封装 subprocess 细节，提供超时、输出限制等生产级功能

    Java 对照：这相当于一个内部使用 `ProcessBuilder` 的实现类。
    dataclass 自动生成构造方法，下面三个字段就是构造参数和成员变量。
    """

    executable: str = "powershell.exe"  # 要启动的程序，类似 ProcessBuilder 的第一个参数
    timeout_ms: int = 120_000  # 默认超时时间（毫秒），120_000 = 120000（Python 允许用下划线分隔数字）
    output_limit: int = 50_000  # stdout 和 stderr 合并后最多保留多少个字符，防止输出爆炸

    def __post_init__(self) -> None:
        """dataclass 构造完成后自动调用，用来校验构造参数。

        这是什么：构造后钩子，用于参数校验
        Java 类比：在构造方法末尾执行 if (timeout <= 0) throw new IllegalArgumentException(...)
        为什么需要：dataclass 不能在字段定义中写校验逻辑，需要 __post_init__ 补充

        Java 对照：相当于在构造方法末尾执行参数检查。
        """
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms 必须是正整数")
        if self.output_limit <= 0:
            raise ValueError("output_limit 必须是正整数")

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """启动 PowerShell 子进程并把结果收敛成 CommandResult。

        这是什么：CommandRunner 接口的实现方法
        Java 类比：@Override public CommandResult run(String command, String cwd, Integer timeoutMs)
        为什么需要：执行真实 Shell 命令，隔离 subprocess 模块的使用细节

        参数：
            command: 要执行的 PowerShell 命令文本
            cwd: 工作目录，限制命令能访问的文件范围
            timeout_ms: 可选的超时毫秒数，覆盖默认值

        返回：
            CommandResult: 包含输出、退出码和执行状态的不可变对象
        """
        if not command:
            raise ValueError("command 不能为空")

        # subprocess 使用秒，而项目配置使用毫秒，因此这里除以 1000
        timeout_seconds = (timeout_ms if timeout_ms is not None else self.timeout_ms) / 1000

        # 明确要求 PowerShell 使用 UTF-8 输出，否则中文在不同 Windows 环境下容易乱码
        # $OutputEncoding 是 PowerShell 的特殊变量，控制输出编码
        script = "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); " + command

        try:
            # 类似 Java ProcessBuilder：参数使用列表传入，不再经过额外一层 shell 拆词
            completed = subprocess.run(
                [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                cwd=cwd,  # 设置工作目录
                capture_output=True,  # 捕获 stdout 和 stderr
                timeout=timeout_seconds,  # 超时自动终止
                text=False,  # 返回字节而不是字符串，由我们控制解码方式
                check=False,  # 不自动抛出异常，由我们处理退出码
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # Windows 下不显示黑窗口
            )

            # stdout 是正常输出，stderr 是错误输出。两者都需要交回模型，因此合并保存
            output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").rstrip()

            # 输出可能非常大，需要截断保护，避免消耗过多 token
            truncated = len(output) > self.output_limit
            return CommandResult(
                output[: self.output_limit],  # 只保留前 N 个字符
                completed.returncode,  # 进程退出码
                False,  # 没有超时
                truncated  # 是否被截断
            )

        except subprocess.TimeoutExpired as error:
            # 超时异常中仍可能带有终止前已经产生的部分输出，不能直接丢掉
            stdout = error.stdout or b""
            stderr = error.stderr or b""
            raw = stdout + stderr
            output = raw.decode("utf-8", errors="replace").rstrip()
            truncated = len(output) > self.output_limit

            # 超时视为执行失败，退出码设为 1
            return CommandResult(output[: self.output_limit], 1, True, truncated)
