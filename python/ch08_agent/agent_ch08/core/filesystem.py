"""工作区文件系统的领域错误和接口。

这是什么：定义文件系统操作的接口和领域异常
Java 类比：类似 FileSystemPort 接口和一组自定义的 FileSystemException 子类
为什么需要：抽象文件操作细节，让核心工具不直接依赖 pathlib 或 os 模块

Java 对照：这里是领域异常 + `interface` 的组合。核心工具只依赖
`WorkspaceFileSystem`，不直接依赖 `pathlib` 或操作系统 API。
"""

from typing import Protocol


class WorkspacePathError(Exception):
    """路径不是工作区内的安全相对路径。

    这是什么：表示路径逃逸或非法的异常
    Java 类比：类似 PathTraversalException
    为什么需要：拒绝 ..、绝对路径、符号链接逃逸等安全风险操作
    """


class TextNotFoundError(Exception):
    """编辑时找不到要求精确匹配的旧文本。

    这是什么：edit_file 找不到目标文本时的异常
    Java 类比：类似 TextNotFoundException
    为什么需要：确保编辑操作的原子性，找不到目标就不修改文件
    """


class InvalidUtf8Error(Exception):
    """文件字节不能按严格 UTF-8 解码。

    这是什么：文件编码错误的异常
    Java 类比：类似 MalformedInputException
    为什么需要：拒绝处理非 UTF-8 文件，避免乱码或数据损坏
    """


class FileNotFoundError(Exception):
    """目标文件或目录不存在。

    这是什么：文件不存在的异常
    Java 类比：类似 java.io.FileNotFoundException
    为什么需要：区分文件不存在和其他 I/O 错误，让调用方能明确处理
    """


class InvalidFilePathError(Exception):
    """路径存在，但文件/目录类型不符合当前操作。

    这是什么：路径类型错误的异常（比如对目录调用 read_file）
    Java 类比：类似 NotRegularFileException
    为什么需要：防止对目录执行文件操作，或对文件执行目录操作
    """


class FileSystemOperationError(Exception):
    """无法归入其他领域错误的底层文件系统失败。

    这是什么：通用文件系统错误的兜底异常
    Java 类比：类似 IOException 作为其他 I/O 异常的基类
    为什么需要：捕获无法细分的底层 I/O 错误，避免泄露操作系统细节
    """


class WorkspaceWriteBoundary(Protocol):
    """权限层使用的窄接口，只判断写路径是否仍在工作区。

    这是什么：用于路径安全检查的最小接口
    Java 类比：类似 interface PathValidator { boolean isWithinWorkspace(...); }
    为什么需要：权限层只需校验路径，不需要完整的文件系统操作能力
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """安全路径返回 True，路径逃逸返回 False，其他故障向上抛出。

        这是什么：判断相对路径是否在工作区内的方法
        Java 类比：类似 boolean isWithinBoundary(Path workspace, String relativePath)
        为什么需要：防止路径遍历攻击，确保所有写操作都限制在工作区内
        """


class WorkspaceFileSystem(WorkspaceWriteBoundary, Protocol):
    """工作区文件系统接口，类似 Java 的 `WorkspaceFileSystem` interface。

    这是什么：定义所有文件操作的完整接口
    Java 类比：类似 interface FileSystemPort extends PathValidator { ... }
    为什么需要：核心层通过接口操作文件，测试时可用内存实现替换真实文件系统
    """

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取 UTF-8 文本；limit 按行数限制返回内容。

        这是什么：读取文本文件的方法
        Java 类比：类似 String readFile(Path workspace, String path, Integer lineLimit)
        为什么需要：提供统一的文件读取接口，支持限制返回行数以控制 token 消耗
        """

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """写入完整 UTF-8 文本并返回实际字节数。

        这是什么：覆写文件内容的方法
        Java 类比：类似 int writeFile(Path workspace, String path, String content)
        为什么需要：提供统一的文件写入接口，返回字节数便于审计和配额管理
        """

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """只替换第一次精确匹配，找不到时不修改文件。

        这是什么：精确替换文本片段的方法
        Java 类比：类似 void replaceFirst(Path workspace, String path, String old, String new)
        为什么需要：实现精确的局部编辑，避免覆写整个文件时的竞态和 token 浪费
        """

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """列出工作区内匹配模式的相对路径，并按稳定顺序返回。

        这是什么：按通配符模式查找文件的方法
        Java 类比：类似 List<String> glob(Path workspace, String pattern)
        为什么需要：让模型能通过模式匹配查找文件，不需要遍历整个目录树
        """
