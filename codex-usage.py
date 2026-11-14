#!/usr/bin/env python3
"""Expose Codex account rate limits as an MCP server over stdio."""

import json
import os
import queue
import subprocess
import sys
import threading
import time

SERVER_INFO = {"name": "codex-usage", "version": "1.0.0"}
TOOL = {
    "name": "get_codex_usage",
    "description": "Read the current Codex account rate limits and usage windows.",
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "openWorldHint": True},
}


def read_usage():
    """Start an app server, read rate limits, and always shut it down."""
    executable = os.environ.get("CODEX_CLI", "codex")
    try:
        proc = subprocess.Popen(
            [executable, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
    except OSError as exc:
        raise RuntimeError(f"Could not start Codex CLI: {exc}") from exc

    lines = queue.Queue()

    def read_lines():
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=read_lines, daemon=True).start()

    def send(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def receive(request_id, stage):
        deadline = time.monotonic() + 30
        while True:
            try:
                line = lines.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise RuntimeError(
                    f"Timed out during {stage}. Check that Codex can access its "
                    "configuration, authentication, and the network in this environment."
                ) from exc
            if line is None:
                raise RuntimeError(
                    f"Codex app server exited during {stage} (exit code {proc.poll()}). "
                    "Check its stderr and access to the Codex configuration and authentication."
                )
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Codex app server returned invalid JSON") from exc
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"Codex app server error: {message['error']}")
                return message["result"]

    try:
        send({"id": 0, "method": "initialize", "params": {"clientInfo": {
            "name": "codex-usage-mcp", "title": "Codex Usage MCP", "version": "1.0.0"
        }}})
        receive(0, "app-server initialization")
        send({"method": "initialized", "params": {}})
        send({"id": 1, "method": "account/rateLimits/read"})
        return receive(1, "account rate-limit request")
    except (OSError, KeyError) as exc:
        raise RuntimeError(f"Codex app server communication failed: {exc}") from exc
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdin.close()
        proc.stdout.close()


def handle(request):
    """Handle one JSON-RPC message; notifications have no response."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32600, "message": "Invalid Request"}}
    if "id" not in request:
        return None
    request_id = request["id"]
    method = request["method"]
    params = request.get("params", {})
    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Invalid params"}}
    if method == "initialize":
        version = params.get("protocolVersion", "2025-06-18")
        if version not in ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"):
            version = "2025-06-18"
        result = {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        if params.get("name") != TOOL["name"] or params.get("arguments", {}) != {}:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Unknown tool or invalid arguments"}}
        try:
            usage = read_usage()
            result = {"content": [{"type": "text", "text": json.dumps(usage, indent=2)}]}
        except RuntimeError as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            response = handle(request)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
