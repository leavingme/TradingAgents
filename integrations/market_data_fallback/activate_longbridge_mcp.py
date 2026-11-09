#!/usr/bin/env python3
"""Redeem a one-time Longbridge MCP authorization code into a private token file."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Longbridge MCP authorization failed (HTTP {exc.code}).") from None
    except urllib.error.URLError:
        raise RuntimeError("Could not reach Longbridge MCP authorization service.") from None
    for line in body.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise RuntimeError("Longbridge MCP authorization returned invalid JSON.") from None


def redeem(base_url: str, auth_code: str) -> dict:
    response = _post(
        base_url.rstrip("/") + "/agent",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "authenticate", "arguments": {"auth_code": auth_code}},
        },
    )
    if "error" in response:
        raise RuntimeError("Longbridge MCP rejected the authorization code.")
    result = response.get("result", {})
    content = result.get("content", []) if isinstance(result, dict) else []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            try:
                payload = json.loads(item["text"])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
    if isinstance(result, dict) and result.get("access_token"):
        return result
    raise RuntimeError("Authorization response did not include a token payload.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-code", help="One-time code; if omitted, prompt without echoing it")
    parser.add_argument(
        "--base-url",
        default=os.getenv("LONGBRIDGE_MCP_URL", "https://mcp.longbridge.com"),
    )
    parser.add_argument(
        "--token-file",
        default=os.getenv(
            "LONGBRIDGE_MCP_TOKEN_FILE",
            str(Path.home() / ".config" / "tradingagents" / "longbridge_mcp_token.json"),
        ),
    )
    args = parser.parse_args()
    auth_code = args.auth_code or getpass.getpass("Longbridge MCP one-time authorization code: ")
    payload = redeem(args.base_url, auth_code)
    access_token = next(
        (payload.get(key) for key in ("access_token", "token", "bearer", "bearer_token") if payload.get(key)),
        None,
    )
    if not isinstance(access_token, str):
        raise RuntimeError("Authorization response did not include an access token.")
    expires_in = int(payload.get("expires_in") or 3600)
    token_file = Path(args.token_file).expanduser()
    token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(token_file.parent, stat.S_IRWXU)
    stored = {
        "base_url": args.base_url,
        "access_token": access_token,
        "refresh_token": payload.get("refresh_token"),
        "expiry": (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat(),
        "expires_in": expires_in,
    }
    token_file.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    os.chmod(token_file, stat.S_IRUSR | stat.S_IWUSR)
    print(f"Longbridge MCP token saved with owner-only permissions: {token_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
