"""第二章内置工具：保留 shell，并增加四个工作区文件工具。"""

from collections.abc import Mapping
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


def _shell_args(value: Mapping[str, Any]) -> bool:
    """校验 shell 工具参数：只允许 command 字段且必须非空。

    这是什么：shell 工具的参数校验器
    Java 类比：类似 boolean validateShellArgs(Map<String, Object> args)
    为什么需要：在 JSON Schema 之外增加严格校验，确保只有 command 字段且值为非空字符串
    """
    return set(value) == {"command"} and isinstance(value.get("command"), str) and bool(value["command"])


def create_shell_tool(command_runner: CommandRunner) -> ToolDefinition:
    """构造 shell 工具；它是第一章能力在第二章的原样保留。

    这是什么：shell 工具定义工厂方法
    Java 类比：类似 @Bean ToolDefinition shellTool(CommandRunner runner)
    为什么需要：创建 PowerShell 命令执行工具，将命令运行器注入到工具处理器中
    """
    def handler(arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        try:
            result = command_runner.run(str(arguments["command"]), context.workspace)
        except Exception:  # noqa: BLE001
            return tool_error("shell_start_failed", "无法启动 PowerShell 进程")
        output = result.output or "(无输出)"
        if result.truncated:
            output += "\n[输出已截断]"
        if result.timed_out:
            return tool_error("shell_timeout", output)
        if result.exit_code != 0:
            return tool_error("shell_failed", f"PowerShell 退出码为 {result.exit_code}\n{output}")
        return tool_success(output)

    return ToolDefinition(
        "shell",
        "在当前工作目录执行 PowerShell 命令；需要人工批准。",
        {"type": "object", "properties": {"command": {"type": "string", "minLength": 1}}, "required": ["command"], "additionalProperties": False},
        "execute",
        handler,
        _shell_args,
    )


def _read_args(value: Mapping[str, Any]) -> bool:
    """校验 read_file 工具参数：path 必填，limit 可选且为正整数。

    这是什么：read_file 工具的参数校验器
    Java 类比：类似 boolean validateReadArgs(Map<String, Object> args)
    为什么需要：确保 path 非空，limit（如果存在）是正整数而非布尔值
    """
    return set(value) <= {"path", "limit"} and isinstance(value.get("path"), str) and bool(value["path"]) and ("limit" not in value or (isinstance(value["limit"], int) and not isinstance(value["limit"], bool) and value["limit"] > 0))


def _write_args(value: Mapping[str, Any]) -> bool:
    """校验 write_file 工具参数：path 和 content 都必填且为字符串。

    这是什么：write_file 工具的参数校验器
    Java 类比：类似 boolean validateWriteArgs(Map<String, Object> args)
    为什么需要：确保 path 非空且 content 存在（允许空字符串）
    """
    return set(value) == {"path", "content"} and isinstance(value.get("path"), str) and bool(value["path"]) and isinstance(value.get("content"), str)


def _edit_args(value: Mapping[str, Any]) -> bool:
    """校验 edit_file 工具参数：path、old_text、new_text 都必填，old_text 非空。

    这是什么：edit_file 工具的参数校验器
    Java 类比：类似 boolean validateEditArgs(Map<String, Object> args)
    为什么需要：确保三个字段都是字符串，且 path 和 old_text 非空（new_text 允许空）
    """
    return set(value) == {"path", "old_text", "new_text"} and all(isinstance(value.get(key), str) for key in value) and bool(value["path"]) and bool(value["old_text"])


def _glob_args(value: Mapping[str, Any]) -> bool:
    """校验 glob 工具参数：pattern 必填且非空。

    这是什么：glob 工具的参数校验器
    Java 类比：类似 boolean validateGlobArgs(Map<String, Object> args)
    为什么需要：确保 pattern 是非空字符串
    """
    return set(value) == {"pattern"} and isinstance(value.get("pattern"), str) and bool(value["pattern"])


def _map_file_error(error: Exception, path: str) -> ToolResult:
    """把文件系统领域异常映射为稳定错误码和中文说明。

    这是什么：文件系统异常到工具错误的映射器
    Java 类比：类似 ToolResult mapException(Exception e, String path)
    为什么需要：将领域异常转换为模型可理解的错误码和消息，避免暴露内部实现细节
    """
    if isinstance(error, WorkspacePathError):
        return tool_error("path_escape", str(error))
    if isinstance(error, InvalidUtf8Error):
        return tool_error("invalid_utf8", f"文件不是合法 UTF-8: {path}")
    if isinstance(error, FileNotFoundError):
        return tool_error("file_not_found", f"文件不存在: {path}")
    if isinstance(error, InvalidFilePathError):
        return tool_error("invalid_path", f"路径不是文件: {path}")
    if isinstance(error, FileSystemOperationError):
        return tool_error("filesystem_error", f"文件系统操作失败: {path}")
    raise error


def create_read_file_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建严格 UTF-8 读取工具。

    这是什么：read_file 工具定义工厂方法
    Java 类比：类似 @Bean ToolDefinition readFileTool(FileSystem fs)
    为什么需要：创建文件读取工具，将文件系统注入到工具处理器中
    """
    def handler(arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        path = str(arguments["path"])
        try:
            return tool_success(file_system.read_file(context.workspace, path, arguments.get("limit")))
        except Exception as error:  # noqa: BLE001
            return _map_file_error(error, path)
    return ToolDefinition("read_file", "读取工作区内的 UTF-8 文本文件，可按行数限制输出。", {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer", "minimum": 1}}, "required": ["path"], "additionalProperties": False}, "read", handler, _read_args)


def create_write_file_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建完整写入工具；父目录不存在时自动创建。

    这是什么：write_file 工具定义工厂方法
    Java 类比：类似 @Bean ToolDefinition writeFileTool(FileSystem fs)
    为什么需要：创建文件写入工具，自动创建父目录提升易用性
    """
    def handler(arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        path = str(arguments["path"])
        try:
            count = file_system.write_file(context.workspace, path, str(arguments["content"]))
            return tool_success(f"已写入 {count} 个 UTF-8 字节: {path}")
        except Exception as error:  # noqa: BLE001
            return _map_file_error(error, path)
    return ToolDefinition("write_file", "向工作区文件写入完整 UTF-8 文本，自动创建父目录。", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False}, "write", handler, _write_args)


def create_edit_file_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建精确编辑工具；只替换第一次匹配。

    这是什么：edit_file 工具定义工厂方法
    Java 类比：类似 @Bean ToolDefinition editFileTool(FileSystem fs)
    为什么需要：创建文本替换工具，让模型能精确修改代码片段而不覆盖全文
    """
    def handler(arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        path = str(arguments["path"])
        try:
            file_system.edit_file(context.workspace, path, str(arguments["old_text"]), str(arguments["new_text"]))
            return tool_success(f"已编辑文件: {path}")
        except Exception as error:  # noqa: BLE001
            if isinstance(error, TextNotFoundError):
                return tool_error("text_not_found", f"文件中找不到精确文本: {path}")
            return _map_file_error(error, path)
    return ToolDefinition("edit_file", "将工作区 UTF-8 文件中的 old_text 精确替换一次。", {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string", "minLength": 1}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"], "additionalProperties": False}, "write", handler, _edit_args)


def create_glob_tool(file_system: WorkspaceFileSystem) -> ToolDefinition:
    """创建文件发现工具，结果按字母排序。

    这是什么：glob 工具定义工厂方法
    Java 类比：类似 @Bean ToolDefinition globTool(FileSystem fs)
    为什么需要：创建文件搜索工具，让模型能按通配符模式查找文件
    """
    def handler(arguments: Mapping[str, Any], context: ToolContext) -> ToolResult:
        pattern = str(arguments["pattern"])
        try:
            matches = file_system.glob_files(context.workspace, pattern)
            return tool_success("\n".join(matches) if matches else "(无匹配文件)")
        except Exception as error:  # noqa: BLE001
            return _map_file_error(error, pattern)
    return ToolDefinition("glob", "列出工作区内匹配 glob 模式的文件，结果按字母排序。", {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"], "additionalProperties": False}, "read", handler, _glob_args)


def create_chapter_one_tools(command_runner: CommandRunner) -> ToolRegistry:
    """构造 P01 工具集，仅包含 shell。

    这是什么：第一章工具集工厂方法
    Java 类比：类似 @Bean ToolRegistry chapterOneTools(CommandRunner runner)
    为什么需要：创建第一章的工具集，只包含 shell 工具
    """
    registry = ToolRegistry()
    registry.register(create_shell_tool(command_runner))
    return registry


def create_chapter_two_tools(command_runner: CommandRunner, file_system: WorkspaceFileSystem) -> ToolRegistry:
    """在 P01 工具集上累加四个文件工具。

    这是什么：第二章工具集工厂方法
    Java 类比：类似 @Bean ToolRegistry chapterTwoTools(CommandRunner runner, FileSystem fs)
    为什么需要：创建第二章的工具集，在第一章基础上增加文件操作工具
    """
    registry = create_chapter_one_tools(command_runner)
    registry.register(create_read_file_tool(file_system))
    registry.register(create_write_file_tool(file_system))
    registry.register(create_edit_file_tool(file_system))
    registry.register(create_glob_tool(file_system))
    return registry
