"""第二章内置工具：保留 shell，并增加四个工作区文件工具。

这是什么：内置工具定义层，提供 shell 和文件操作工具
Java 类比：类似工具工厂类，定义各种 ToolDefinition
为什么需要：封装工具创建逻辑，统一参数校验和错误处理
"""

from typing import Any

from ..core.commands import CommandRunner
from ..core.filesystem import (
    FileNotFoundError,
    FileSystemOperationError,
    InvalidFilePathError,
    InvalidUtf8Error,
    TextNotFoundError,
    WorkspaceFileSystem,
    WorkspacePathError,
)
from ..core.tools import (
    ToolContext,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    tool_error,
    tool_success,
)


def _shell_args(value: dict[str, Any]) -> bool:
    """验证 shell 工具参数格式。

    这是什么：shell 参数校验器
    Java 类比：类似 static boolean validateShellArgs(Map<String, Object> args)
    为什么需要：在执行前严格校验参数，防止注入和格式错误
    """
    return set(value) == {"command"} and isinstance(value.get("command"), str) and bool(value["command"])  # 必须只有 command 字段且为非空字符串


def create_shell_tool(command_runner: CommandRunner) -> ToolDefinition:
    """构造 shell 工具；它是第一章能力在第二章的原样保留。

    这是什么：shell 工具工厂方法
    Java 类比：类似 static ToolDefinition createShellTool(CommandRunner runner)
    为什么需要：创建 shell 命令执行工具，注入命令执行器依赖
    """
    def handler(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """shell 工具的执行处理器。

        这是什么：shell 命令执行逻辑
        Java 类比：类似 ToolResult handle(Map args, Context ctx)
        为什么需要：封装命令执行、错误转换和结果格式化
        """
        try:
            result = command_runner.run(str(arguments["command"]), context.workspace)  # 执行命令
        except Exception:  # noqa: BLE001 | 捕获所有启动异常
            return tool_error("shell_start_failed", "无法启动 PowerShell 进程")
        output = result.output or "(无输出)"  # 提取输出，空输出时显示提示
        if result.truncated:  # 输出被截断时添加提示
            output += "\n[输出已截断]"
        if result.timed_out:  # 超时时返回错误
            return tool_error("shell_timeout", output)
        if result.exit_code != 0:  # 非零退出码表示失败
            return tool_error("shell_failed", f"PowerShell 退出码为 {result.exit_code}\n{output}")
        return tool_success(output)  # 返回成功结果

    return ToolDefinition(
        "shell",  # 工具名称
        "在当前工作目录执行 PowerShell 命令；需要人工批准。",  # 工具描述
        {"type": "object", "properties": {"command": {"type": "string", "minLength": 1}}, "required": ["command"], "additionalProperties": False},  # JSON Schema
        "execute",  # 副作用类型：执行类
        handler,  # 处理函数
        _shell_args,  # 参数验证器
    )


def _read_args(value: dict[str, Any]) -> bool:
    """验证 read_file 工具参数格式。

    这是什么：read_file 参数校验器
    Java 类比：类似 static boolean validateReadArgs(Map<String, Object> args)
    为什么需要：确保 path 存在且 limit 为正整数
    """
    return set(value) <= {"path", "limit"} and isinstance(value.get("path"), str) and bool(value["path"]) and ("limit" not in value or (isinstance(value["limit"], int) and not isinstance(value["limit"], bool) and value["limit"] > 0))  # path 必填且非空，limit 可选但必须为正整数


def _write_args(value: dict[str, Any]) -> bool:
    """验证 write_file 工具参数格式。

    这是什么：write_file 参数校验器
    Java 类比：类似 static boolean validateWriteArgs(Map<String, Object> args)
    为什么需要：确保 path 和 content 都存在且为字符串
    """
    return set(value) == {"path", "content"} and isinstance(value.get("path"), str) and bool(value["path"]) and isinstance(value.get("content"), str)  # path 和 content 都必填


def _edit_args(value: dict[str, Any]) -> bool:
    """验证 edit_file 工具参数格式。

    这是什么：edit_file 参数校验器
    Java 类比：类似 static boolean validateEditArgs(Map<String, Object> args)
    为什么需要：确保 path、old_text、new_text 都存在，且 old_text 非空
    """
    return set(value) == {"path", "old_text", "new_text"} and all(isinstance(value.get(key), str) for key in value) and bool(value["path"]) and bool(value["old_text"])  # 三个字段都必填，old_text 不能为空


def _glob_args(value: dict[str, Any]) -> bool:
    """验证 glob_files 工具参数格式。

    这是什么：glob_files 参数校验器
    Java 类比：类似 static boolean validateGlobArgs(Map<String, Object> args)
    为什么需要：确保 pattern 存在且为非空字符串
    """
    return set(value) == {"pattern"} and isinstance(value.get("pattern"), str) and bool(value["pattern"])  # pattern 必填且非空


def _map_file_error(error: Exception, path: str) -> ToolResult:
    """把文件系统领域异常映射为稳定错误码和中文说明。

    这是什么：文件系统异常映射器
    Java 类比：类似 static ToolResult mapException(Exception e, String path)
    为什么需要：统一异常转换，提供结构化错误码和人类可读消息
    """
    if isinstance(error, WorkspacePathError):  # 路径安全异常
        return tool_error("path_escape", str(error))
    if isinstance(error, InvalidUtf8Error):  # 编码异常
        return tool_error("invalid_utf8", f"文件不是合法 UTF-8: {path}")
    if isinstance(error, FileNotFoundError):  # 文件不存在
        return tool_error("file_not_found", f"文件不存在: {path}")
    if isinstance(error, InvalidFilePathError):  # 路径类型错误
        return tool_error("invalid_path", f"路径不是文件: {path}")
    if isinstance(error, FileSystemOperationError):  # 通用文件系统错误
        return tool_error("filesystem_error", f"文件系统操作失败: {path}")
    raise error  # 未识别的异常继续抛出


def create_read_file_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建严格 UTF-8 读取工具。

    这是什么：read_file 工具工厂方法
    Java 类比：类似 static ToolDefinition createReadFileTool(FileSystem fs)
    为什么需要：创建文件读取工具，注入文件系统依赖
    """
    def handler(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """read_file 工具的执行处理器。

        这是什么：文件读取逻辑
        Java 类比：类似 ToolResult handle(Map args, Context ctx)
        为什么需要：封装文件读取和异常转换
        """
        path = str(arguments["path"])  # 提取路径参数
        try:
            return tool_success(file_system.read_file(context.workspace, path, arguments.get("limit")))  # 读取文件
        except Exception as error:  # noqa: BLE001 | 捕获所有文件系统异常
            return _map_file_error(error, path)  # 转换为工具错误
    return ToolDefinition("read_file", "读取工作区内的 UTF-8 文本文件，可按行数限制输出。", {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}}, "required": ["path"], "additionalProperties": False}, "read", handler, _read_args)


def create_write_file_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建完整写入工具；父目录不存在时自动创建。

    这是什么：write_file 工具工厂方法
    Java 类比：类似 static ToolDefinition createWriteFileTool(FileSystem fs)
    为什么需要：创建文件写入工具，注入文件系统依赖
    """
    def handler(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """write_file 工具的执行处理器。

        这是什么：文件写入逻辑
        Java 类比：类似 ToolResult handle(Map args, Context ctx)
        为什么需要：封装文件写入和异常转换
        """
        path = str(arguments["path"])  # 提取路径参数
        try:
            count = file_system.write_file(context.workspace, path, str(arguments["content"]))  # 写入文件
            return tool_success(f"已写入 {count} 个 UTF-8 字节: {path}")  # 返回成功结果
        except Exception as error:  # noqa: BLE001 | 捕获所有文件系统异常
            return _map_file_error(error, path)  # 转换为工具错误
    return ToolDefinition("write_file", "向工作区文件写入完整 UTF-8 文本，自动创建父目录。", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}, "write", handler, _write_args)


def create_edit_file_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建精确编辑工具；只替换第一次匹配。

    这是什么：edit_file 工具工厂方法
    Java 类比：类似 static ToolDefinition createEditFileTool(FileSystem fs)
    为什么需要：创建文件编辑工具，支持精确文本替换
    """
    def handler(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """edit_file 工具的执行处理器。

        这是什么：文件编辑逻辑
        Java 类比：类似 ToolResult handle(Map args, Context ctx)
        为什么需要：封装文本替换和异常转换
        """
        path = str(arguments["path"])  # 提取路径参数
        try:
            file_system.edit_file(context.workspace, path, str(arguments["old_text"]), str(arguments["new_text"]))  # 执行精确替换
            return tool_success(f"已编辑文件: {path}")  # 返回成功结果
        except Exception as error:  # noqa: BLE001 | 捕获所有文件系统异常
            if isinstance(error, TextNotFoundError):  # 文本未找到的特殊处理
                return tool_error("text_not_found", f"文件中找不到精确文本: {path}")
            return _map_file_error(error, path)  # 其他异常统一转换
    return ToolDefinition("edit_file", "将工作区 UTF-8 文件中的 old_text 精确替换一次。", {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string", "minLength": 1}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"], "additionalProperties": False}, "write", handler, _edit_args)


def create_glob_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建文件发现工具，结果按字母排序。

    这是什么：glob_files 工具工厂方法
    Java 类比：类似 static ToolDefinition createGlobTool(FileSystem fs)
    为什么需要：创建文件搜索工具，支持通配符模式匹配
    """
    def handler(arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        """glob_files 工具的执行处理器。

        这是什么：文件搜索逻辑
        Java 类比：类似 ToolResult handle(Map args, Context ctx)
        为什么需要：封装通配符匹配和异常转换
        """
        pattern = str(arguments["pattern"])  # 提取模式参数
        try:
            matches = file_system.glob_files(context.workspace, pattern)  # 执行文件搜索
            return tool_success("\n".join(matches) if matches else "(无匹配文件)")  # 返回匹配结果或提示
        except Exception as error:  # noqa: BLE001 | 捕获所有文件系统异常
            return _map_file_error(error, pattern)  # 转换为工具错误
    return ToolDefinition("glob", "列出工作区内匹配 glob 模式的文件，结果按字母排序。", {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"], "additionalProperties": False}, "read", handler, _glob_args)


def create_chapter_one_tools(command_runner: CommandRunner) -> ToolRegistry:
    """构造 P01 工具集，仅包含 shell。

    这是什么：第一章工具集工厂方法
    Java 类比：类似 static ToolRegistry createChapterOneTools(CommandRunner runner)
    为什么需要：为第一章创建基础工具集，只包含命令执行能力
    """
    registry = ToolRegistry()  # 创建空注册表
    registry.register(create_shell_tool(command_runner))  # 注册 shell 工具
    return registry  # 返回工具注册表


def create_chapter_two_tools(command_runner: CommandRunner, file_system: WorkspaceFileSystem) -> ToolRegistry:
    """在 P01 工具集上累加四个文件工具。

    这是什么：第二章工具集工厂方法
    Java 类比：类似 static ToolRegistry createChapterTwoTools(CommandRunner runner, FileSystem fs)
    为什么需要：为第二章创建扩展工具集，在第一章基础上增加文件操作能力
    """
    registry = create_chapter_one_tools(command_runner)  # 复用第一章工具集
    registry.register(create_read_file_tool(file_system))  # 注册读文件工具
    registry.register(create_write_file_tool(file_system))  # 注册写文件工具
    registry.register(create_edit_file_tool(file_system))  # 注册编辑文件工具
    registry.register(create_glob_tool(file_system))  # 注册文件搜索工具
    return registry  # 返回扩展后的工具注册表
