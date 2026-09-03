"""工作区文件系统的领域错误和接口。

Java 对照：这里是领域异常 + `interface` 的组合。核心工具只依赖
`WorkspaceFileSystem`，不直接依赖 `pathlib` 或操作系统 API。
"""

from typing import Protocol


class WorkspacePathError(Exception):
    """路径不是工作区内的安全相对路径。

    这是什么：路径安全校验失败的异常
    Java 类比：类似 PathTraversalException
    为什么需要：标识路径逃逸工作区或包含非法字符的情况，防止安全漏洞
    """


class TextNotFoundError(Exception):
    """编辑时找不到要求精确匹配的旧文本。

    这是什么：文本替换失败的专用异常
    Java 类比：类似 TextNotFoundException
    为什么需要：edit_file 需要精确匹配旧文本，未找到时拒绝写入以防止误操作
    """


class InvalidUtf8Error(Exception):
    """文件字节不能按严格 UTF-8 解码。

    这是什么：文件编码错误的异常
    Java 类比：类似 CharsetDecodingException
    为什么需要：本项目只支持 UTF-8 文本，二进制或其他编码文件必须明确拒绝
    """


class FileNotFoundError(Exception):
    """目标文件或目录不存在。

    这是什么：文件不存在的异常
    Java 类比：类似 java.io.FileNotFoundException
    为什么需要：明确区分文件不存在和其他文件系统错误，便于上层针对性处理
    """


class InvalidFilePathError(Exception):
    """路径存在，但文件/目录类型不符合当前操作。

    这是什么：文件类型不匹配的异常
    Java 类比：类似 NotAFileException 或 NotADirectoryException
    为什么需要：防止把目录当文件读，或把文件当目录遍历
    """


class FileSystemOperationError(Exception):
    """无法归入其他领域错误的底层文件系统失败。

    这是什么：文件系统操作的兜底异常
    Java 类比：类似 IOException
    为什么需要：捕获权限不足、磁盘满等无法精确分类的底层错误
    """


class WorkspaceWriteBoundary(Protocol):
    """权限层使用的窄接口，只判断写路径是否仍在工作区。

    这是什么：路径边界检查的最小接口
    Java 类比：类似 interface WriteBoundaryValidator { boolean isWithin(...); }
    为什么需要：权限系统只需要边界检查能力，不应依赖完整的文件系统接口（接口隔离原则）
    """

    def is_path_within_workspace(self, workspace: str, relative_path: str) -> bool:
        """安全路径返回 True，路径逃逸返回 False，其他故障向上抛出。

        这是什么：路径边界判断方法
        Java 类比：类似 boolean validate(Path workspace, String relativePath)
        为什么需要：权限决策前快速判断路径合法性，避免授权后才发现路径非法
        """


class WorkspaceFileSystem(WorkspaceWriteBoundary, Protocol):
    """工作区文件系统接口，类似 Java 的 `WorkspaceFileSystem` interface。

    这是什么：文件系统操作的完整协议定义
    Java 类比：类似 interface FileSystemPort { String read(...); int write(...); ... }
    为什么需要：定义核心层需要的文件操作契约，让适配器可替换（真实文件系统或内存实现）
    """

    def read_file(self, workspace: str, relative_path: str, limit: int | None = None) -> str:
        """严格读取 UTF-8 文本；limit 按行数限制返回内容。

        这是什么：文件读取的抽象方法
        Java 类比：类似 String readFile(Path workspace, String path, Integer lineLimit)
        为什么需要：定义读取契约，支持限制行数以防止大文件撑爆上下文
        """

    def write_file(self, workspace: str, relative_path: str, content: str) -> int:
        """写入完整 UTF-8 文本并返回实际字节数。

        这是什么：文件写入的抽象方法
        Java 类比：类似 int writeFile(Path workspace, String path, String content)
        为什么需要：定义写入契约，返回字节数便于工具向模型报告写入结果
        """

    def edit_file(self, workspace: str, relative_path: str, old_text: str, new_text: str) -> None:
        """只替换第一次精确匹配，找不到时不修改文件。

        这是什么：文本替换的抽象方法
        Java 类比：类似 void replaceFirst(Path workspace, String path, String old, String new)
        为什么需要：定义精确替换契约，让模型能安全修改代码片段而不覆盖全文
        """

    def glob_files(self, workspace: str, pattern: str) -> tuple[str, ...]:
        """列出工作区内匹配模式的相对路径，并按稳定顺序返回。

        这是什么：文件搜索的抽象方法
        Java 类比：类似 List<String> glob(Path workspace, String pattern)
        为什么需要：定义通配符搜索契约，让模型能按模式查找文件（如 "*.py"）
        """
