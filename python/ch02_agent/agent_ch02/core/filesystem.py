"""工作区文件系统的领域错误和接口。

这是什么：文件系统的领域层定义，包含异常类型和接口契约
Java 类比：类似定义领域异常类 + FileSystem 接口
为什么需要：定义文件操作的领域语言，隔离底层文件系统实现

Java 对照：这里是领域异常 + `interface` 的组合。核心工具只依赖
`WorkspaceFileSystem`，不直接依赖 `pathlib` 或操作系统 API。
"""

from typing import Protocol


class WorkspacePathError(Exception):
    """路径不是工作区内的安全相对路径。

    这是什么：路径安全异常，表示路径逃逸工作区或格式非法
    Java 类比：类似 PathSecurityException 或 IllegalPathException
    为什么需要：明确标识路径安全问题，防止目录遍历攻击
    """


class TextNotFoundError(Exception):
    """编辑时找不到要求精确匹配的旧文本。

    这是什么：文本查找失败异常
    Java 类比：类似 TextNotFoundException
    为什么需要：区分文本不存在和文件不存在，避免误操作
    """


class InvalidUtf8Error(Exception):
    """文件字节不能按严格 UTF-8 解码。

    这是什么：编码格式异常
    Java 类比：类似 CharacterCodingException
    为什么需要：明确标识编码问题，避免乱码或解析错误
    """


class FileNotFoundError(Exception):
    """目标文件或目录不存在。

    这是什么：文件不存在异常
    Java 类比：类似 FileNotFoundException
    为什么需要：明确标识文件缺失，区分其他文件系统错误
    """


class InvalidFilePathError(Exception):
    """路径存在，但文件/目录类型不符合当前操作。

    这是什么：文件类型不匹配异常（如尝试读取目录）
    Java 类比：类似 InvalidPathTypeException
    为什么需要：区分路径存在但类型错误的情况，提供精确错误信息
    """


class FileSystemOperationError(Exception):
    """无法归入其他领域错误的底层文件系统失败。

    这是什么：通用文件系统操作异常
    Java 类比：类似 IOException 的基类
    为什么需要：捕获无法精确分类的文件系统错误，避免异常泄漏
    """


class WorkspaceFileSystem(Protocol):
    """工作区文件系统接口，类似 Java 的 `WorkspaceFileSystem` interface。

    这是什么：文件系统操作的接口定义（Protocol）
    Java 类比：interface WorkspaceFileSystem { String readFile(...); int writeFile(...); ... }
    为什么需要：定义文件操作契约，让核心层不依赖具体实现，支持内存实现用于测试
    """

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取 UTF-8 文本；limit 按行数限制返回内容。

        这是什么：文件读取方法签名
        Java 类比：String readFile(String workspace, String path, Integer lineLimit) throws IOException
        为什么需要：定义统一的文件读取接口，支持大文件限制读取
        """

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """写入完整 UTF-8 文本并返回实际字节数。

        这是什么：文件写入方法签名
        Java 类比：int writeFile(String workspace, String path, String content) throws IOException
        为什么需要：定义统一的文件写入接口，返回字节数便于验证
        """

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """只替换第一次精确匹配，找不到时不修改文件。

        这是什么：文件编辑方法签名
        Java 类比：void editFile(String workspace, String path, String oldText, String newText) throws IOException
        为什么需要：定义安全的文本替换接口，避免全文替换风险
        """

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """列出工作区内匹配模式的相对路径，并按稳定顺序返回。

        这是什么：文件匹配方法签名
        Java 类比：List<String> globFiles(String workspace, String pattern) throws IOException
        为什么需要：定义文件搜索接口，支持通配符模式匹配
        """
