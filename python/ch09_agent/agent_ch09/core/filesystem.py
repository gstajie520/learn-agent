"""工作区文件系统的领域错误和接口。

Java 对照：这里是领域异常 + `interface` 的组合。核心工具只依赖
`WorkspaceFileSystem`，不直接依赖 `pathlib` 或操作系统 API。

这是什么：文件系统操作的抽象接口和领域异常定义
Java 类比：类似定义 FileSystemService 接口和自定义异常类
为什么需要：让核心层不依赖具体实现，便于测试和替换不同文件系统
"""

from typing import Protocol


# ==================== 领域异常定义 ====================

class WorkspacePathError(Exception):
    """路径不是工作区内的安全相对路径。

    这是什么：路径安全校验失败的异常
    Java 类比：类似 PathTraversalException 或 SecurityException
    为什么需要：防止路径逃逸攻击，确保工具只能操作工作区内文件
    """


class TextNotFoundError(Exception):
    """编辑时找不到要求精确匹配的旧文本。

    这是什么：精确文本替换失败的异常
    Java 类比：类似 TextNotFoundException
    为什么需要：区分"文件不存在"和"文本不匹配"两种失败场景
    """


class InvalidUtf8Error(Exception):
    """文件字节不能按严格 UTF-8 解码。

    这是什么：文件编码错误的异常
    Java 类比：类似 CharacterCodingException 或 UnsupportedEncodingException
    为什么需要：确保工具只处理 UTF-8 文本，避免编码混乱
    """


class FileNotFoundError(Exception):
    """目标文件或目录不存在。

    这是什么：文件不存在的异常
    Java 类比：类似 java.io.FileNotFoundException
    为什么需要：明确区分文件不存在和其他文件系统错误
    """


class InvalidFilePathError(Exception):
    """路径存在，但文件/目录类型不符合当前操作。

    这是什么：文件类型不匹配的异常
    Java 类比：类似 InvalidPathException 或自定义 FileTypeMismatchException
    为什么需要：区分"路径存在但不是文件"和"路径不存在"的情况
    """


class FileSystemOperationError(Exception):
    """无法归入其他领域错误的底层文件系统失败。

    这是什么：通用文件系统操作失败的异常
    Java 类比：类似 IOException 或 FileSystemException
    为什么需要：捕获所有其他无法精确分类的文件系统错误
    """


# ==================== 文件系统接口定义 ====================

class WorkspaceWriteBoundary(Protocol):
    """权限层使用的窄接口，只判断写路径是否仍在工作区。

    这是什么：路径安全检查的最小接口
    Java 类比：interface WorkspaceWriteBoundary { boolean isPathWithinWorkspace(...); }
    为什么需要：权限层只需要路径检查，不需要完整的文件操作能力
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """检查路径是否在工作区内，防止路径逃逸。

        这是什么：路径安全校验方法
        Java 类比：类似 boolean isPathSafe(String workspace, String path)
        为什么需要：确保所有文件写入都在工作区边界内

        参数：
            workspace: 工作区根路径
            relative_path: 相对路径

        返回：
            bool: 安全路径返回 True，路径逃逸返回 False

        异常：
            其他故障向上抛出（如路径格式错误）
        """


class WorkspaceFileSystem(WorkspaceWriteBoundary, Protocol):
    """工作区文件系统接口，定义所有文件操作的契约。

    这是什么：文件系统操作的完整接口定义
    Java 类比：interface WorkspaceFileSystem extends WorkspaceWriteBoundary { ... }
    为什么需要：让核心工具不依赖具体实现，支持本地文件系统、内存文件系统等
    """

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取 UTF-8 文本文件。

        这是什么：文件读取方法
        Java 类比：类似 String readFile(String workspace, String path, Integer limit)
        为什么需要：提供安全的文件读取能力，支持行数限制

        参数：
            workspace: 工作区根路径
            relative_path: 相对路径
            limit: 按行数限制返回内容（None 表示读取全部）

        返回：
            str: 文件内容（UTF-8 文本）

        异常：
            WorkspacePathError: 路径不安全
            FileNotFoundError: 文件不存在
            InvalidUtf8Error: 文件不是 UTF-8 编码
        """

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """写入完整 UTF-8 文本并返回实际字节数。

        这是什么：文件写入方法
        Java 类比：类似 int writeFile(String workspace, String path, String content)
        为什么需要：提供安全的文件写入能力，返回字节数便于验证

        参数：
            workspace: 工作区根路径
            relative_path: 相对路径
            content: 要写入的文本内容

        返回：
            int: 实际写入的字节数

        异常：
            WorkspacePathError: 路径不安全
            FileSystemOperationError: 写入失败
        """

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """只替换第一次精确匹配的文本，找不到时不修改文件。

        这是什么：精确文本替换方法
        Java 类比：类似 void editFile(String workspace, String path, String oldText, String newText)
        为什么需要：支持精确的增量编辑，避免全量重写文件

        参数：
            workspace: 工作区根路径
            relative_path: 相对路径
            old_text: 要替换的旧文本（必须精确匹配）
            new_text: 替换后的新文本

        异常：
            WorkspacePathError: 路径不安全
            FileNotFoundError: 文件不存在
            TextNotFoundError: 找不到旧文本
            InvalidUtf8Error: 文件不是 UTF-8 编码
        """

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """列出工作区内匹配模式的相对路径，并按稳定顺序返回。

        这是什么：文件模式匹配方法
        Java 类比：类似 List<String> globFiles(String workspace, String pattern)
        为什么需要：支持工具查找特定模式的文件（如 *.py）

        参数：
            workspace: 工作区根路径
            pattern: glob 模式（如 "*.py", "src/**/*.ts"）

        返回：
            tuple[str, ...]: 匹配的相对路径列表（不可变、已排序）

        异常：
            WorkspacePathError: 模式不安全
            FileSystemOperationError: 查找失败
        """
