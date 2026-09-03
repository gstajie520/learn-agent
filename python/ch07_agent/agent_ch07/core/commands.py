"""操作系统命令执行边界。

这是什么：
    定义命令执行的接口契约和返回值对象，隔离核心层与具体操作系统 API。

Java 类比：
    类似定义 ProcessExecutor 接口 + ExecutionResult DTO，核心服务只依赖接口。

为什么需要：
    - 核心 Agent 不直接调用 subprocess，保持平台无关性
    - 测试时可以注入 Fake，不需要真正启动 PowerShell 进程
    - 统一错误处理和超时/截断逻辑
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """操作系统命令执行后的统一结果。

    这是什么：
        命令执行的不可变返回值对象，封装输出、退出码和执行状态。

    Java 类比：
        类似 record ExecutionResult(String output, int exitCode, boolean timedOut, boolean truncated)

    为什么需要：
        - 不直接返回 subprocess 对象，让核心层不依赖具体操作系统 API
        - 不可变设计避免并发问题
        - 包含所有诊断信息（超时、截断）供上层决策
    """

    output: str  # stdout 和 stderr 合并后的文本
    exit_code: int  # 进程退出码，通常 0 表示成功
    timed_out: bool  # 是否因为超过时间限制被终止
    truncated: bool  # 输出是否超过上限并被截断


class CommandRunner(Protocol):
    """命令执行接口；真实实现和测试 Fake 都遵守它。

    这是什么：
        命令执行器的抽象接口，定义核心层依赖的执行契约。

    Java 类比：
        interface CommandRunner { ExecutionResult run(String command, String cwd, Integer timeoutMs); }

    为什么需要：
        - AgentRunner 只依赖这个接口，因此测试时可以传入不会真正启动 PowerShell 的 Fake
        - 适配器层可以提供不同操作系统的实现（PowerShell、Bash）
        - 依赖倒置原则：核心定义接口，基础设施提供实现
    """

    def run(self, command: str, cwd: str, timeout_ms: int | None = None) -> CommandResult:
        """在受控工作目录中执行一条命令，并返回与操作系统无关的结果对象。

        参数：
            command: 要执行的命令文本
            cwd: 工作目录绝对路径
            timeout_ms: 可选超时毫秒数，覆盖默认值

        返回：
            CommandResult: 包含输出、退出码和执行状态的不可变对象
        """
