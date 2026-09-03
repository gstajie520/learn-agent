"""工作区文件系统的领域错误和接口。

这是什么：文件系统操作的接口定义和领域异常
Java 类比：interface WorkspaceFileSystem + 自定义异常类
为什么需要：定义文件系统的抽象接口，让核心代码不依赖具体的文件操作实现

Java 对照：这里是领域异常 + `interface` 的组合。核心工具只依赖
`WorkspaceFileSystem`，不直接依赖 `pathlib` 或操作系统 API。
"""

from typing import Protocol


class WorkspacePathError(Exception):
    """路径不是工作区内的安全相对路径。"""


class TextNotFoundError(Exception):
    """编辑时找不到要求精确匹配的旧文本。"""


class InvalidUtf8Error(Exception):
    """文件字节不能按严格 UTF-8 解码。"""


class FileNotFoundError(Exception):
    """目标文件或目录不存在。"""


class InvalidFilePathError(Exception):
    """路径存在，但文件/目录类型不符合当前操作。"""


class FileSystemOperationError(Exception):
    """无法归入其他领域错误的底层文件系统失败。"""


class WorkspaceWriteBoundary(Protocol):
    """权限层使用的窄接口，只判断写路径是否仍在工作区。"""

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """安全路径返回 True，路径逃逸返回 False，其他故障向上抛出。"""


class WorkspaceFileSystem(WorkspaceWriteBoundary, Protocol):
    """工作区文件系统接口，类似 Java 的 `WorkspaceFileSystem` interface。"""

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取 UTF-8 文本；limit 按行数限制返回内容。"""

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """写入完整 UTF-8 文本并返回实际字节数。"""

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """只替换第一次精确匹配，找不到时不修改文件。"""

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """列出工作区内匹配模式的相对路径，并按稳定顺序返回。"""
