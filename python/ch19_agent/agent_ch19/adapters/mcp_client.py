"""MCP stdio JSON-RPC 适配器。

这是学习版的最小实现：每次请求写一行 JSON、读取一行 JSON，避免引入额外 SDK，
方便 Java 开发者把它类比成 ``ProcessBuilder`` + 一个简单的 RPC Client。
"""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any

from ..features.mcp_tools import (
    McpCallResult,
    McpConnection,
    McpPublishedTool,
    McpServerSpec,
    McpTimeoutError,
    McpTransportError,
)


class SubprocessMcpConnectionFactory:
    """创建不经过 shell 的 MCP stdio 连接。"""

    def open(self, spec: McpServerSpec) -> McpConnection:
        """启动 MCP 子进程并完成 initialize 握手。"""
        connection = SubprocessMcpConnection(spec)
        try:
            connection.start()
            return connection
        except Exception:
            connection.close()
            raise


class SubprocessMcpConnection:
    """一个串行化的 JSON-RPC stdio 连接。"""

    def __init__(self, spec: McpServerSpec) -> None:
        """只保存配置，不在构造阶段启动进程。"""
        self._spec = spec
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._lock = threading.RLock()

    def start(self) -> None:
        """启动子进程并发送 initialize。"""
        try:
            self._process = subprocess.Popen(
                [self._spec.command, *self._spec.args],
                cwd=self._spec.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                shell=False,
            )
            self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "agent-tutorial", "version": "0.1.0"},
                },
            )
        except subprocess.TimeoutExpired as error:
            raise McpTimeoutError("MCP initialize 超时") from error
        except OSError as error:
            raise McpTransportError("MCP 子进程启动失败") from error

    def list_tools(self) -> tuple[McpPublishedTool, ...]:
        """读取 tools/list，并把远程声明转换成领域对象。"""
        result = self._request("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise McpTransportError("MCP tools/list 返回格式无效")
        return tuple(
            McpPublishedTool(
                str(item["name"]),
                dict(item["inputSchema"]),
                str(item.get("description", "")),
            )
            for item in tools
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("inputSchema"), dict)
        )

    def call_tool(
        self, name: str, arguments: dict[str, Any], timeout_seconds: float
    ) -> McpCallResult:
        """调用 tools/call，并映射远程结果。"""
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments}, timeout_seconds
        )
        content = result.get("content", [])
        if not isinstance(content, list) or not all(isinstance(item, dict) for item in content):
            raise McpTransportError("MCP tools/call content 无效")
        structured = result.get("structuredContent")
        return McpCallResult(
            tuple(content),
            structured if isinstance(structured, dict) else None,
            result.get("isError") is True,
        )

    def wait_for_failure(self) -> None:
        """阻塞等待子进程退出；学习版由 Runtime.close 主动回收。"""
        process = self._process
        if process is not None:
            process.wait()

    def close(self) -> None:
        """关闭 stdin/stdout 并终止子进程。"""
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._process = None

    def _request(
        self, method: str, params: dict[str, Any], timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        """发送一条 JSON-RPC 请求并读取响应。"""
        with self._lock:
            process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                raise McpTransportError("MCP 连接未启动")
            request_id = self._next_id
            self._next_id += 1
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
                + "\n"
            )
            process.stdin.flush()
            try:
                line = process.stdout.readline()
            except Exception as error:
                raise McpTransportError("MCP 读取响应失败") from error
            if not line:
                raise McpTransportError("MCP 子进程已退出")
            payload = json.loads(line)
            if not isinstance(payload, dict) or payload.get("id") != request_id:
                raise McpTransportError("MCP JSON-RPC 响应不匹配")
            if "error" in payload:
                raise McpTransportError("MCP server 返回协议错误")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise McpTransportError("MCP JSON-RPC result 无效")
            return result
