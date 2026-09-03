"""工作区文件系统的领域错误和接口。

Java 对照：这里是领域异常 + `interface` 的组合。核心工具只依赖
`WorkspaceFileSystem`，不直接依赖 `pathlib` 或操作系统 API。
"""

from typing import Protocol


class WorkspacePathError(Exception):
    """路径不是工作区内的安全相对路径。

    这是什么：文件路径违反工作区边界的领域异常
    Java 类比：类似自定义的 PathEscapeException
    为什么需要：区分路径逃逸和其他文件错误，让权限层精确拒绝越界写入
    """


class TextNotFoundError(Exception):
    """编辑时找不到要求精确匹配的旧文本。

    这是什么：edit_file 操作中旧文本不存在的专用异常
    Java 类比：类似 TextNotFoundException
    为什么需要：避免盲目修改文件，edit 操作要求旧文本必须精确匹配
    """


class InvalidUtf8Error(Exception):
    """文件字节不能按严格 UTF-8 解码。

    这是什么：文件编码错误的领域异常
    Java 类比：类似 CharacterCodingException
    为什么需要：Agent 只处理 UTF-8 文本，避免把二进制文件或乱码发给模型
    """


class FileNotFoundError(Exception):
    """目标文件或目录不存在。

    这是什么：文件或目录缺失的领域异常
    Java 类比：类似 java.io.FileNotFoundException
    为什么需要：统一文件不存在的错误表示，避免直接暴露操作系统异常
    """


class InvalidFilePathError(Exception):
    """路径存在，但文件/目录类型不符合当前操作。

    这是什么：路径类型不匹配的领域异常
    Java 类比：类似 NotDirectoryException / NotRegularFileException
    为什么需要：区分"文件不存在"和"路径类型错误"（如把目录当文件读）
    """


class FileSystemOperationError(Exception):
    """无法归入其他领域错误的底层文件系统失败。

    这是什么：文件系统操作的兜底异常
    Java 类比：类似 IOException
    为什么需要：统一处理权限不足、磁盘满等无法精确分类的文件系统错误
    """


class WorkspaceWriteBoundary(Protocol):
    """权限层使用的窄接口，只判断写路径是否仍在工作区。

    这是什么：工作区边界检查的最小接口
    Java 类比：interface WorkspaceWriteBoundary { boolean isPathWithin(...); }
    为什么需要：权限策略只需要判断路径合法性，不需要完整文件系统能力
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """安全路径返回 True，路径逃逸返回 False，其他故障向上抛出。

        参数：
            workspace: 工作区根目录绝对路径
            relative_path: 待检查的相对路径

        返回：
            bool: 路径在工作区内返回 True，逃逸返回 False
        """


class WorkspaceFileSystem(WorkspaceWriteBoundary, Protocol):
    """工作区文件系统接口，类似 Java 的 `WorkspaceFileSystem` interface。

    这是什么：文件操作的领域边界接口
    Java 类比：interface WorkspaceFileSystem { String read(...); void write(...); }
    为什么需要：核心层不依赖 pathlib 或操作系统 API，测试时可用 Fake 替换
    """

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取 UTF-8 文本；limit 按行数限制返回内容。

        参数：
            workspace: 工作区根目录
            relative_path: 工作区内的相对路径
            limit: 可选的行数限制，超出时追加剩余行数提示
        """

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """写入完整 UTF-8 文本并返回实际字节数。

        参数：
            workspace: 工作区根目录
            relative_path: 工作区内的相对路径
            content: 要写入的 UTF-8 文本内容
        """

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """只替换第一次精确匹配，找不到时不修改文件。

        参数：
            workspace: 工作区根目录
            relative_path: 工作区内的相对路径
            old_text: 要替换的旧文本，必须精确匹配
            new_text: 替换后的新文本
        """

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """列出工作区内匹配模式的相对路径，并按稳定顺序返回。

        参数：
            workspace: 工作区根目录
            pattern: glob 模式，如 "**/*.py"
        """
