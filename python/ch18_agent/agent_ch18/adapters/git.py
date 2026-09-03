"""Git 外部适配器。

Java 对照：``SubprocessGitRunner`` 类似一个只负责调用 ``ProcessBuilder`` 的 Adapter。
它不理解业务状态，只返回退出码和两条输出流，领域层再决定成功含义。
"""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class GitExecutionError(RuntimeError):
    """Git 进程无法启动或超时。

    这是什么：Git 适配器层的进程级异常
    Java 类比：类似 IOException 或 ProcessExecutionException
    为什么需要：区分进程失败（超时、启动失败）和业务失败（退出码非零但可解析）
    """


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """一次 Git 调用的结构化结果。

    这是什么：封装 Git 命令的退出码和双流输出
    Java 类比：record GitCommandResult(int returncode, String stdout, String stderr)
    为什么需要：适配器层只负责原样返回进程结果，领域层再解释业务含义

    参数：
        returncode: Git 进程退出码（0 表示成功，非零表示失败）
        stdout: 标准输出流内容（UTF-8 解码）
        stderr: 标准错误流内容（UTF-8 解码）
    """

    returncode: int  # Git 退出码
    stdout: str      # 标准输出
    stderr: str      # 标准错误


class SubprocessGitRunner:
    """不经过 shell 执行 Git，避免命令拼接注入。

    这是什么：Git 命令的 subprocess 适配器
    Java 类比：封装 ProcessBuilder 的 Adapter 类
    为什么需要：统一 Git 调用方式，确保参数安全传递而非字符串拼接
    """

    def run(self, arguments: Sequence[str], cwd: str) -> GitCommandResult:
        """在指定目录执行 Git；普通非零退出码作为结果返回。

        这是什么：执行 Git 命令并返回结构化结果
        Java 类比：类似 ProcessBuilder.start().waitFor() + 流读取
        为什么需要：统一错误处理，区分进程级异常和业务级失败

        参数：
            arguments: Git 子命令和参数（如 ["status", "--porcelain"]）
            cwd: Git 工作目录（必须是真实存在的目录）

        返回：
            GitCommandResult: 包含退出码和双流输出

        异常：
            ValueError: 参数格式非法
            GitExecutionError: 进程启动失败或超时
        """
        # 参数校验：防止空参数或非字符串元素
        if not arguments or any(not isinstance(item, str) or not item for item in arguments):
            raise ValueError("Git 参数必须是非空字符串数组")

        # 解析并校验工作目录：strict=True 要求路径真实存在
        path = Path(cwd).resolve(strict=True)
        if not path.is_dir():
            raise GitExecutionError("Git 工作目录不是目录")

        try:
            # 关键：使用列表形式传参，避免 shell 注入
            # --no-pager 防止 Git 等待用户交互
            completed = subprocess.run(
                ["git", "--no-pager", *arguments],  # 列表形式，不经过 shell
                cwd=path,                            # 工作目录
                capture_output=True,                 # 捕获 stdout 和 stderr
                text=True,                           # 以文本模式读取
                encoding="utf-8",                    # 强制 UTF-8 编码
                errors="replace",                    # 无效字符替换为 �
                timeout=30,                          # 30 秒超时
                check=False,                         # 不自动抛异常（手动检查退出码）
                shell=False,                         # 关键：禁用 shell，防止注入
            )
        except subprocess.TimeoutExpired as error:
            # 超时视为进程级异常，不是业务失败
            raise GitExecutionError("Git 命令执行超时") from error
        except OSError as error:
            # 进程启动失败（如 git 不在 PATH 中）
            raise GitExecutionError("Git 进程启动失败") from error

        # 返回原始结果，领域层决定退出码的业务含义
        return GitCommandResult(completed.returncode, completed.stdout, completed.stderr)
