"""工作区文件系统的领域错误和接口。

这是什么：
    文件系统领域层，定义领域异常和接口契约。

Java 类比：
    类似领域异常 + `interface` 的组合。核心工具只依赖
    `WorkspaceFileSystem`，不直接依赖 `pathlib` 或操作系统 API。

为什么需要：
    - 定义清晰的领域异常体系，区分不同类型的文件系统错误
    - 提供接口抽象，让核心层不依赖具体文件系统实现
    - 测试时可以注入 Fake，不需要真实文件系统
    - 符合依赖倒置原则：核心定义接口，适配器提供实现

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
    """权限层使用的窄接口，只判断写路径是否仍在工作区。

    这是什么：
        权限策略使用的轻量级接口，只包含路径边界检查方法。

    Java 类比：
        interface WorkspaceWriteBoundary
        类似单一职责的窄接口，只做一件事。

    为什么需要：
        - 权限层只需要检查路径是否安全，不需要完整的文件系统操作
        - 接口隔离原则：不让权限层依赖完整的 WorkspaceFileSystem
        - 便于独立测试路径边界检查逻辑
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """安全路径返回 True，路径逃逸返回 False，其他故障向上抛出。"""


class WorkspaceFileSystem(WorkspaceWriteBoundary, Protocol):
    """工作区文件系统接口，类似 Java 的 `WorkspaceFileSystem` interface。

    这是什么：
        文件系统操作的核心接口，定义读、写、编辑、glob 方法。

    Java 类比：
        interface WorkspaceFileSystem extends WorkspaceWriteBoundary
        类似 Repository 接口，但操作的是文件而非数据库。

    为什么需要：
        - 核心工具只依赖接口，不直接调用 pathlib
        - 测试时可以注入 Fake，不需要真实文件系统
        - 适配器层可以提供不同实现（本地、内存、远程）
        - 符合接口隔离原则：只暴露工作区所需的最小方法集
    """

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取 UTF-8 文本；limit 按行数限制返回内容。"""

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """写入完整 UTF-8 文本并返回实际字节数。"""

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """只替换第一次精确匹配，找不到时不修改文件。"""

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """列出工作区内匹配模式的相对路径，并按稳定顺序返回。"""
