"""一行一个 JSON-RPC 消息的最小 MCP 演示 Server。"""

from __future__ import annotations

import json
import sys
from typing import Any


def main() -> int:
    """处理 initialize、tools/list 和 tools/call。"""
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = _handle(request)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            continue
        # stdio 协议统一输出 ASCII 转义，避免 Windows 子进程默认代码页破坏 JSON 字节流。
        print(json.dumps(response, ensure_ascii=True), flush=True)
    return 0


def _handle(request: dict[str, Any]) -> dict[str, Any]:
    """返回与请求 id 配对的 JSON-RPC 响应。"""
    request_id = request.get("id")
    method = request.get("method")
    result: dict[str, Any]
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "demo", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "lookup",
                    "description": "在演示数据中查询文本。",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                }
            ]
        }
    elif method == "tools/call":
        params = request.get("params", {})
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        query = arguments.get("query", "") if isinstance(arguments, dict) else ""
        result = {
            "content": [{"type": "text", "text": f"demo lookup: {query}"}],
            "structuredContent": {"query": query, "found": query == "needle"},
            "isError": False,
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": "method not found"},
        }
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


if __name__ == "__main__":
    raise SystemExit(main())
