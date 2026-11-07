"""Small JSON-RPC client for the local Codex App Server stdio protocol.

This intentionally uses only the Python standard library. It starts a fresh
ephemeral Codex thread, uses the user's configured MCP servers/auth, and only
calls the two read-only Futu account tools needed for a holdings snapshot.
"""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
from typing import Any


class AppServerError(RuntimeError):
    """The local Codex App Server could not complete an RPC request."""


class CodexAppServer:
    def __init__(self, cwd: str, executable: str = "codex", timeout: float = 60):
        path = shutil.which(executable)
        if path is None:
            raise AppServerError("找不到 codex 命令；请先安装并登录 Codex CLI。")
        self.cwd = cwd
        self.timeout = timeout
        self._next_id = 1
        self._messages: queue.Queue[str | None] = queue.Queue()
        self.process = subprocess.Popen(
            [path, "app-server", "--listen", "stdio://"],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            # App-server diagnostics may contain MCP configuration details.
            # They are intentionally not copied to this command's output.
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self.thread_id: str | None = None

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._messages.put(line)
        self._messages.put(None)

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _read_response(self, request_id: int) -> dict[str, Any]:
        while True:
            try:
                line = self._messages.get(timeout=self.timeout)
            except queue.Empty:
                raise AppServerError(f"等待 App Server RPC 响应超时（请求 {request_id}）。")
            if line is None:
                code = self.process.poll()
                raise AppServerError(f"Codex App Server 已退出（状态 {code}）。")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # Ignore non-protocol output defensively; Codex normally keeps
                # stdout exclusively for newline-delimited JSON-RPC messages.
                continue
            if message.get("id") != request_id:
                continue  # notification or a response to another request
            if "error" in message:
                # Do not include arbitrary server data: it may echo account IDs.
                raise AppServerError(f"App Server RPC 请求失败（{message.get('id')}）。")
            return message.get("result", {})

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        return self._read_response(request_id)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def start(self) -> str:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "tradingagents_futu_bridge",
                    "title": "TradingAgents Futu Bridge",
                    "version": "0.1.0",
                },
                "capabilities": {},
            },
        )
        self.notify("initialized")
        result = self.request("thread/start", {"cwd": self.cwd, "ephemeral": True})
        thread = result.get("thread") or {}
        thread_id = thread.get("id") or result.get("threadId")
        if not thread_id:
            raise AppServerError("App Server 没有返回临时线程 ID。")
        self.thread_id = str(thread_id)
        return self.thread_id

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not self.thread_id:
            raise AppServerError("App Server 线程尚未启动。")
        return self.request(
            "mcpServer/tool/call",
            {
                "threadId": self.thread_id,
                "server": "futu-mcp",
                "tool": tool_name,
                "arguments": arguments,
            },
        )

    def call_futu(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call one named read-only Futu tool after confirming the server is ready."""
        if tool_name not in {"account_authorized_trd_accs", "account_positions"}:
            raise ValueError(f"桥接未开放此 Futu 工具：{tool_name}")
        if not self.thread_id:
            raise AppServerError("App Server 线程尚未启动。")
        status = self.request(
            "mcpServerStatus/list",
            {"threadId": self.thread_id, "serverName": "futu-mcp", "detail": "toolsAndAuthOnly"},
        )
        servers = status.get("data", status.get("servers", status if isinstance(status, list) else []))
        futu = next((s for s in servers if s.get("name") == "futu-mcp"), None)
        if futu is None:
            # Some App Server versions return the selected server directly.
            futu = status if isinstance(status, dict) and status.get("name") == "futu-mcp" else None
        if not futu or futu.get("runtimeStatus") != "connected":
            raise AppServerError("当前 Codex App Server 中 futu-mcp 未连接；检查 MCP 配置和授权后重试。")
        return self._call(tool_name, arguments)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def __enter__(self) -> "CodexAppServer":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
