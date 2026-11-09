"""Read-only Longbridge MCP adapters for OHLCV and server-side indicators."""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)

_TOOL_NAMES = {
    "stock_data": "history_candlesticks_by_date",
    "technical_indicator": "quant_run",
    "static_info": "static_info",
    "valuation_index": "calc_indexes",
    "financial_report": "financial_report",
    "news": "news",
}


def _credentials() -> tuple[str, str]:
    direct = os.getenv("LONGBRIDGE_MCP_ACCESS_TOKEN", "").strip()
    if direct:
        base_url = os.getenv("LONGBRIDGE_MCP_URL", os.getenv("MCP_BASE_URL", "https://mcp.longbridge.com"))
        return direct, base_url
    default_path = Path.home() / ".config" / "tradingagents" / "longbridge_mcp_token.json"
    project_token = Path.cwd() / ".longbridge_mcp_token.json"
    if not default_path.exists() and project_token.exists():
        default_path = project_token
    token_path = Path(os.getenv("LONGBRIDGE_MCP_TOKEN_FILE", str(default_path))).expanduser()
    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise VendorNotConfiguredError("Longbridge MCP token is not configured.") from None
    except (OSError, json.JSONDecodeError):
        raise VendorNotConfiguredError("Longbridge MCP token file is unreadable or invalid.") from None
    access_token = payload.get("access_token") if isinstance(payload, dict) else None
    expiry = payload.get("expiry") if isinstance(payload, dict) else None
    if not isinstance(access_token, str) or not access_token.strip():
        raise VendorNotConfiguredError("Longbridge MCP token file has no access token.")
    if expiry:
        try:
            expires_at = datetime.fromisoformat(expiry)
        except (TypeError, ValueError):
            raise VendorNotConfiguredError("Longbridge MCP token expiry is invalid.") from None
        if expires_at.tzinfo is None:
            raise VendorNotConfiguredError("Longbridge MCP token expiry must include a timezone.")
        if datetime.now(expires_at.tzinfo) >= expires_at - timedelta(seconds=60):
            raise VendorNotConfiguredError("Longbridge MCP token is expired.")
    base_url = os.getenv("LONGBRIDGE_MCP_URL", os.getenv("MCP_BASE_URL", payload.get("base_url", "https://mcp.longbridge.com")))
    return access_token, base_url


def _post(
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    protocol_version: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    token, base_url = _credentials()
    base_url = base_url.rstrip("/")
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(
        base_url + "/",
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            text = response.read().decode("utf-8")
            response_session_id = response.headers.get("Mcp-Session-Id")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise VendorNotConfiguredError("Longbridge MCP rejected its configured authorization.") from None
        raise VendorUnavailableError(f"Longbridge MCP returned HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise VendorUnavailableError("Longbridge MCP request failed at the transport layer.") from None

    if not text.strip():
        return {}, response_session_id
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip()), response_session_id
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text), response_session_id
    except json.JSONDecodeError:
        raise VendorUnavailableError("Longbridge MCP returned an unreadable response.") from None


class _Client:
    def __init__(self) -> None:
        # Validate credentials before making a network request.
        _credentials()
        self._id = 0
        self._tools: set[str] | None = None
        self._session_id: str | None = None
        self._protocol_version: str | None = None
        response, session_id = _post({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "tradingagents-market-data", "version": "0.1.0"},
            },
        })
        if "error" in response:
            error = response.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise VendorUnavailableError(f"Longbridge MCP initialization failed (code {code}).")
        result = response.get("result")
        version = result.get("protocolVersion") if isinstance(result, dict) else None
        if not isinstance(version, str) or not version:
            raise VendorUnavailableError("Longbridge MCP initialization returned no protocol version.")
        self._protocol_version = version
        self._session_id = session_id
        self.notify("notifications/initialized")

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        response, session_id = _post(
            {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params or {}},
            session_id=self._session_id,
            protocol_version=self._protocol_version,
        )
        self._session_id = session_id or self._session_id
        if "error" in response:
            error = response.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise VendorUnavailableError(f"Longbridge MCP RPC failed (code {code}).")
        return response.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        response, session_id = _post(
            {"jsonrpc": "2.0", "method": method, "params": params or {}},
            session_id=self._session_id,
            protocol_version=self._protocol_version,
        )
        self._session_id = session_id or self._session_id
        if isinstance(response, dict) and "error" in response:
            error = response.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise VendorUnavailableError(f"Longbridge MCP notification failed (code {code}).")

    @property
    def tools(self) -> set[str]:
        if self._tools is None:
            result = self.rpc("tools/list")
            tools = result.get("tools", []) if isinstance(result, dict) else []
            self._tools = {str(item["name"]) for item in tools if isinstance(item, dict) and item.get("name")}
        return self._tools

    def call(self, capability: str, arguments: dict[str, Any]) -> Any:
        name = _TOOL_NAMES[capability]
        if name not in self.tools:
            raise VendorNotConfiguredError(f"Longbridge MCP does not expose {capability}.")
        params = {"name": name, "arguments": arguments}
        # These adapters expose read-only data tools. A transient MCP tool error
        # should not immediately push the request onto a rate-limited fallback.
        result = None
        for attempt in range(3):
            try:
                result = self.rpc("tools/call", params)
            except VendorUnavailableError:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))
                continue
            if not isinstance(result, dict) or not result.get("isError"):
                break
            if attempt == 2:
                raise VendorUnavailableError("Longbridge MCP tool call failed after 3 attempts.")
            time.sleep(0.5 * (attempt + 1))
        if not isinstance(result, dict):
            return result
        for block in result.get("content", []):
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                try:
                    return json.loads(block["text"])
                except json.JSONDecodeError:
                    continue
        return result


def _symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if "." in value:
        code, market = value.rsplit(".", 1)
        # Longbridge MCP requires unpadded HK codes (700.HK, not 00700.HK).
        if market == "HK" and code.isdigit():
            code = str(int(code))
        return f"{code}.{market}"
    if value.isdigit():
        return f"{int(value)}.HK"
    return f"{value}.US"


def _rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        for key in ("candlesticks", "data", "bars", "items", "rows"):
            if isinstance(raw.get(key), list):
                return _rows(raw[key])
        return [raw] if any(key in raw for key in ("time", "timestamp", "date", "Date")) else []
    if isinstance(raw, str):
        try:
            return _rows(json.loads(raw))
        except json.JSONDecodeError:
            return []
    return []


def _ohlcv(symbol: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    canonical = _symbol(symbol)
    raw = _Client().call(
        "stock_data",
        {
            "symbol": canonical,
            "period": "day",
            "forward_adjust": False,
            "trade_sessions": "intraday",
            "start": start_date,
            "end": end_date,
        },
    )
    rows = []
    for row in _rows(raw):
        lowered = {str(key).lower(): value for key, value in row.items()}
        stamp = lowered.get("time", lowered.get("timestamp", lowered.get("date")))
        try:
            day = str(stamp)[:10]
            datetime.strptime(day, "%Y-%m-%d")
            values = {
                "Date": day,
                "Open": float(lowered.get("open")),
                "High": float(lowered.get("high")),
                "Low": float(lowered.get("low")),
                "Close": float(lowered.get("close")),
                "Volume": float(lowered.get("volume", 0) or 0),
            }
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(values[key]) for key in ("Open", "High", "Low", "Close", "Volume")):
            continue
        if start_date <= day <= end_date:
            rows.append(values)
    rows.sort(key=lambda row: row["Date"])
    if not rows:
        raise NoMarketDataError(symbol, canonical, "Longbridge MCP returned no OHLCV rows")
    latest = datetime.strptime(rows[-1]["Date"], "%Y-%m-%d").date()
    requested = datetime.strptime(end_date, "%Y-%m-%d").date()
    stale_days = (requested - latest).days
    if stale_days > 7:
        raise NoMarketDataError(
            symbol, canonical,
            f"Longbridge MCP latest row is {latest}, {stale_days} days before the requested date (stale)",
        )
    return rows


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    rows = _ohlcv(symbol, start_date, end_date)
    lines = [
        f"# Stock data for {_symbol(symbol)} from {start_date} to {end_date}",
        f"# Total records: {len(rows)}",
        "",
        "Date,Open,High,Low,Close,Volume",
    ]
    lines.extend(
        f"{row['Date']},{row['Open']},{row['High']},{row['Low']},{row['Close']},{row['Volume']}"
        for row in rows
    )
    return "\n".join(lines)


_PINE = {
    "rsi": ("rsi", "//@version=6\nindicator('RSI')\nplot(ta.rsi(close, 14))\n"),
    "macd": ("macd", "//@version=6\nindicator('MACD')\n[m,s,h]=ta.macd(close,12,26,9)\nplot(m)\n"),
    "macds": ("macd", "//@version=6\nindicator('MACD Signal')\n[m,s,h]=ta.macd(close,12,26,9)\nplot(s)\n"),
    "macdh": ("macd", "//@version=6\nindicator('MACD Histogram')\n[m,s,h]=ta.macd(close,12,26,9)\nplot(h)\n"),
    "boll": ("boll", "//@version=6\nindicator('Bollinger')\n[m,u,l]=ta.bb(close,20,2)\nplot(m)\n"),
    "boll_ub": ("boll", "//@version=6\nindicator('Bollinger Upper')\n[m,u,l]=ta.bb(close,20,2)\nplot(u)\n"),
    "boll_lb": ("boll", "//@version=6\nindicator('Bollinger Lower')\n[m,u,l]=ta.bb(close,20,2)\nplot(l)\n"),
    "atr": ("atr", "//@version=6\nindicator('ATR')\nplot(ta.atr(14))\n"),
    "vwma": ("vwma", "//@version=6\nindicator('VWMA')\nplot(ta.vwma(close,20))\n"),
    "close_10_ema": ("ema10", "//@version=6\nindicator('EMA10')\nplot(ta.ema(close,10))\n"),
    "close_50_sma": ("sma50", "//@version=6\nindicator('SMA50')\nplot(ta.sma(close,50))\n"),
    "close_200_sma": ("sma200", "//@version=6\nindicator('SMA200')\nplot(ta.sma(close,200))\n"),
}


def get_indicators(symbol: str, indicator: str, as_of_date: str, look_back_days: int) -> str:
    key = indicator.lower().strip()
    if key not in _PINE:
        raise VendorNotConfiguredError(f"Longbridge MCP has no Pine template for indicator {key}.")
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    start = end - timedelta(days=max(int(look_back_days), 250) + 50)
    raw = _Client().call(
        "technical_indicator",
        {
            "symbol": _symbol(symbol),
            "period": "day",
            "start": start.strftime("%Y-%m-%d"),
            "end": (end + timedelta(days=1)).strftime("%Y-%m-%d"),
            "script": _PINE[key][1],
        },
    )
    if isinstance(raw, dict) and raw.get("report_json"):
        report = raw["report_json"]
        try:
            report = json.loads(report) if isinstance(report, str) else report
        except json.JSONDecodeError:
            pass
        detail = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    else:
        detail = json.dumps(raw, ensure_ascii=False, indent=2, default=str)
    return (
        f"Technical Indicator Report for {_symbol(symbol)}\n"
        f"Indicator: {key.upper()}\nReport Date: {as_of_date}\n"
        f"Lookback Period: {look_back_days} days\n\n{detail}\n\n"
        "Data Source: Longbridge MCP"
    )


def _render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def get_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    symbol = _symbol(ticker)
    client = _Client()
    reference = client.call("static_info", {"symbols": [symbol]})
    valuation = client.call("valuation_index", {"symbols": [symbol]})
    return (
        f"## Longbridge company reference: {symbol}\n"
        f"Static information:\n{_render(reference)}\n\n"
        f"Valuation indexes:\n{_render(valuation)}"
    )


def _financial_report(ticker: str, kind: str, freq: str | None = None, curr_date: str | None = None) -> str:
    symbol = _symbol(ticker)
    report_type = "af" if str(freq or "").lower() in {"annual", "year", "yearly"} else "qf"
    result = _Client().call(
        "financial_report",
        {"symbol": symbol, "kind": kind, "report_type": report_type},
    )
    return f"## Longbridge {kind} report for {symbol} ({report_type})\n{_render(result)}"


def get_income_statement(ticker: str, freq: str | None = None, curr_date: str | None = None) -> str:
    return _financial_report(ticker, "IS", freq, curr_date)


def get_balance_sheet(ticker: str, freq: str | None = None, curr_date: str | None = None) -> str:
    return _financial_report(ticker, "BS", freq, curr_date)


def get_cashflow(ticker: str, freq: str | None = None, curr_date: str | None = None) -> str:
    return _financial_report(ticker, "CF", freq, curr_date)


def _published_date(row: dict[str, Any]) -> str:
    raw = row.get("published_at") or row.get("publish_time") or row.get("time") or row.get("date")
    if raw is None:
        return ""
    try:
        if isinstance(raw, (int, float)) or str(raw).strip().replace(".", "", 1).isdigit():
            epoch = float(raw)
            if epoch > 10**12:
                epoch /= 1000
            stamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
        else:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        return ""
    return stamp.date().isoformat()


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    symbol = _symbol(ticker)
    raw = _Client().call("news", {"symbol": symbol})
    if isinstance(raw, dict):
        rows = raw.get("items") or raw.get("news_list") or raw.get("list") or []
    else:
        rows = raw
    if not isinstance(rows, list):
        raise VendorUnavailableError("Longbridge MCP returned an unexpected news payload.")
    lines = [f"# News for {symbol} from {start_date} to {end_date}"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _published_date(row)
        # Undated news is omitted to prevent leakage into historical runs.
        if not day or not start_date <= day <= end_date:
            continue
        title = str(row.get("title") or "No title").replace("\n", " ")
        source = str(row.get("source") or row.get("source_name") or "Longbridge")
        summary = str(row.get("description") or row.get("summary") or "").replace("\n", " ")
        url = str(row.get("url") or "")
        lines.append(f"- {day} | {source} | {title}\n  {summary}\n  {url}")
    if len(lines) == 1:
        raise NoMarketDataError(ticker, symbol, "Longbridge MCP returned no dated news in the requested window")
    return "\n".join(lines)
