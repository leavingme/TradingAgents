#!/usr/bin/env python3
"""
Activate the Longbridge MCP vendor by redeeming a one-time authorization code.

Usage:
    /data/disk/workspace/TradingAgents/venv/bin/python scripts/activate_longbridge_mcp.py --auth-code <CODE>

You can generate the code at https://open.longbridge.com/connect — it's valid for
10 minutes and single-use.

This script also writes the bearer token to:
    /data/disk/workspace/TradingAgents/.longbridge_mcp_token.json
    (mode 0600, owner only)

The token is then picked up at runtime by tradingagents.dataflows.longbridge_mcp.
"""
import argparse
import json
import os
import re
import stat
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = ROOT / ".longbridge_mcp_token.json"

# Default to global endpoint; CN users can override via env MCP_BASE_URL
DEFAULT_BASE_URL = os.getenv("MCP_BASE_URL", "https://mcp.longbridge.com")
AGENT_PATH = "/agent"  # temporary authorize-only endpoint


def _http_post_sse_text(url: str, payload: dict, headers: dict | None = None) -> str:
    """POST JSON to a JSON-RPC endpoint; return raw body. Works for both SSE
    envelopes (`data: {...}`) and plain JSON responses."""
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {body[:500]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}") from e


def _parse_jsonrpc_reply(text: str) -> dict:
    """Decode a JSON-RPC reply that may arrive as `data: {...}` SSE or as a
    plain JSON body."""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    for line in text.splitlines():
        m = re.match(r"^data:\s*(.*)$", line)
        if m is None:
            continue
        body = m.group(1).strip()
        if not body:
            continue
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            # body might be JSON itself, but plain `data:` followed by a `\n\n`
            # event boundary — try joining data lines too.
            continue
    joined = "\n".join(
        re.match(r"^data:\s*(.*)$", l).group(1)
        for l in text.splitlines()
        if re.match(r"^data:\s*(.*)$", l)
    )
    try:
        return json.loads(joined)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not decode JSON-RPC reply:\n{text[:500]}") from e


def authenticate(base_url: str, auth_code: str) -> dict:
    """
    Call the temporary `/agent` endpoint's `authenticate` tool to redeem the code.
    Returns the unwrapped payload (parsed from `result.content[0].text` if the
    server wrapped it in MCP-style content, or the raw `result` dict).
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "authenticate",
            "arguments": {"auth_code": auth_code},
        },
    }
    url = base_url.rstrip("/") + AGENT_PATH
    text = _http_post_sse_text(url, payload)
    resp = _parse_jsonrpc_reply(text)
    if "error" in resp:
        raise RuntimeError(f"authenticate error: {resp['error']}")

    result = resp.get("result", {})

    # MCP result shape: {content: [{type:'text', text:'...json...'}]}
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text_payload = item.get("text", "")
            try:
                return json.loads(text_payload)
            except json.JSONDecodeError:
                # Maybe the text already IS the dict-shaped token info.
                return {"raw_text": text_payload}
    if isinstance(result, dict) and result:
        return result
    raise RuntimeError(f"unexpected authenticate response:\n{text[:800]}")


def extract_token(auth_payload: dict) -> dict:
    """
    Pull the access token out of the authenticate response. The shape is
    published per service; we try a few common keys, then dump the full payload
    so the user can paste it in a bug report if we miss.
    """
    token_fields = ("access_token", "token", "bearer", "bearer_token")
    for k in token_fields:
        if k in auth_payload:
            return {
                "access_token": auth_payload[k],
                "expires_in": auth_payload.get("expires_in"),
                "refresh_token": auth_payload.get("refresh_token"),
                "raw": auth_payload,
            }
    raise RuntimeError(
        f"could not find access token in authenticate response. "
        f"keys={list(auth_payload.keys())}, full={json.dumps(auth_payload)[:500]}"
    )


def save_token(payload: dict, base_url: str) -> None:
    """Persist the bearer token to disk with restrictive permissions."""
    expires_in = payload.get("expires_in") or 3600
    expiry = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    stored = {
        "base_url": base_url,
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expiry": expiry.isoformat(),
        "expires_in": expires_in,
    }
    TOKEN_PATH.write_text(json.dumps(stored, indent=2))
    os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    print(f"✓ saved token to {TOKEN_PATH}  (expiry {stored['expiry']})")


def validate_token(base_url: str, access_token: str) -> bool:
    """Smoke-check the token against the main MCP service via initialize()."""
    payload = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "tradingagents-longbridge-mcp-activator", "version": "0.1.0"},
        },
    }
    url = base_url.rstrip("/") + "/"
    try:
        text = _http_post_sse_text(
            url,
            payload,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp = _parse_jsonrpc_reply(text)
        # If we got a `result`, we're authenticated.
        if "result" in resp and "serverInfo" in resp["result"]:
            print(f"✓ token validated against {base_url}")
            print(f"  server: {resp['result']['serverInfo']}")
            return True
        print(f"!! initialize did not return serverInfo: {json.dumps(resp)[:300]}")
        return False
    except Exception as e:
        print(f"!! validate failed: {e}")
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--auth-code", required=True, help="10-minute, single-use code from https://open.longbridge.com/connect")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="MCP base URL (default global; CN users set MCP_BASE_URL=https://mcp.longbridge.cn)")
    args = p.parse_args()

    print(f"== Activating Longbridge MCP at {args.base_url} ==")
    print(f"   redeem code length={len(args.auth_code)} chars")

    auth_payload = authenticate(args.base_url, args.auth_code)
    print("  authenticate response keys:", list(auth_payload.keys()))

    token_info = extract_token(auth_payload)
    save_token(token_info, args.base_url)

    ok = validate_token(args.base_url, token_info["access_token"])
    if not ok:
        print("!! token did NOT validate — saved anyway, but downstream calls will fail")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
