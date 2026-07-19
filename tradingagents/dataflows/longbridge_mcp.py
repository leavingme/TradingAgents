"""
Longbridge MCP vendor for TradingAgents (2026-07-04 new path).

Uses the Longbridge HTTP MCP service at https://mcp.longbridge.com (or .cn for
mainland). Activated by `scripts/activate_longbridge_mcp.py --auth-code <CODE>`,
which writes a bearer token to:
    /data/workspace/TradingAgents/.longbridge_mcp_token.json   (mode 0600)

Design notes:
  - Transport: streamable HTTP. We POST JSON-RPC and parse the SSE `data:` line.
  - 6 vendor slots mapped to one or more MCP tools. The MCP tool *names* depend
    on the server's `tools/list` response — we discover them lazily on the first
    call (and cache the lookup) so we don't hardcode names that may change.
  - When the token file is missing or expired, vendor methods raise
    `MCPAuthError` so the router can fall back to the CLI vendor.

Compared to the CLI vendor (longbridge.py):
  - No subprocess wrappers / ANSI stripping / ast.literal_eval /
    quant-run pretty-regex parsing. MCP returns plain JSON-RPC `result.content`.
  - One TransportError class instead of distinguishing each CLI quirk.
"""
from typing import Annotated, Any, Optional
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .data_validation import (
    IndicatorBatch,
    IndicatorObservation,
    NormalizedIndicatorData,
)
from .errors import NoMarketDataError
from .evidence_models import NewsFeed, NewsItem, parse_external_datetime
from .indicator_requirements import (
    effective_indicator_lookback_days,
    indicator_calculation_lookback_days,
)

ROOT = Path(__file__).resolve().parents[2]  # /data/disk/workspace/TradingAgents
TOKEN_PATH = ROOT / ".longbridge_mcp_token.json"

DEFAULT_BASE_URL = os.getenv("MCP_BASE_URL", "https://mcp.longbridge.com")


# ---- Errors ----

class MCPAuthError(RuntimeError):
    """Bearer token missing, expired, or rejected. Router should fall back."""


class MCPTransportError(RuntimeError):
    """Network / HTTP / JSON-RPC error talking to MCP."""


class MCPNotActivatedError(MCPAuthError):
    """Token file is missing — caller must run scripts/activate_longbridge_mcp.py."""


# ---- Token store ----

def _load_token() -> Optional[dict]:
    """Return token dict from disk, or None if absent. Never raises on missing file."""
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _token_expiry(token: dict) -> datetime | None:
    expiry_str = token.get("expiry")
    if not isinstance(expiry_str, str) or not expiry_str.strip():
        return None
    try:
        expiry = datetime.fromisoformat(expiry_str)
    except (TypeError, ValueError):
        return None
    if expiry.tzinfo is None or expiry.utcoffset() is None:
        return None
    return expiry


def _is_expired(token: dict, skew_seconds: int = 60) -> bool:
    expiry = _token_expiry(token)
    if expiry is None:
        return True
    return datetime.now(expiry.tzinfo) >= expiry - timedelta(seconds=skew_seconds)


def get_token_status(skew_seconds: int = 60) -> dict[str, str | bool | None]:
    """Return credential health without exposing token material or file paths."""
    token = _load_token()
    if token is None:
        return {"configured": False, "status": "missing", "expires_at": None}
    if not isinstance(token, dict):
        return {"configured": False, "status": "invalid", "expires_at": None}
    access_token = token.get("access_token")
    expiry = _token_expiry(token)
    if not isinstance(access_token, str) or not access_token.strip() or expiry is None:
        return {"configured": False, "status": "invalid", "expires_at": None}
    expires_at = expiry.astimezone(timezone.utc).isoformat()
    if datetime.now(expiry.tzinfo) >= expiry - timedelta(seconds=skew_seconds):
        return {"configured": False, "status": "expired", "expires_at": expires_at}
    return {"configured": True, "status": "valid", "expires_at": expires_at}


def _write_token_from_payload(payload: dict, base_url: str) -> None:
    """Used by the activate script. Idempotent write."""
    from datetime import timezone
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
    os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)


# ---- Symbol normalization ----

def normalize_symbol(symbol: str) -> str:
    """
    Normalize to Longbridge's <CODE>.<MARKET> format. We don't strip HK leading
    zeros here because MCP accepts the leading-zero form (CLI does not).

    Examples:
        NVDA        -> NVDA.US
        AAPL.US     -> AAPL.US
        0700.HK     -> 0700.HK
        700.HK      -> 700.HK    (passed through; MCP is lenient)
        1810.HK     -> 1810.HK
        600519.SH   -> 600519.SH
        1810        -> 1810.HK   (pure digits -> HK guess)
    """
    s = symbol.upper().strip()
    if not s:
        return s
    if "." in s:
        code, _, market = s.partition(".")
        return f"{code}.{market.upper()}"
    if s.isdigit():
        return f"{s}.HK"
    return f"{s}.US"


# ---- MCP transport ----

class LongbridgeMCPClient:
    """
    Thin MCP client. Sync, no streaming pipeline — each call is one POST.
    `tools` cache holds the discovered name → schema map.
    """

    def __init__(self, base_url: Optional[str] = None):
        tok = _load_token()
        if not tok:
            raise MCPNotActivatedError(
                "Longbridge MCP token is not configured."
            )
        if not isinstance(tok, dict):
            raise MCPAuthError("Longbridge MCP token payload is invalid.")
        access_token = tok.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise MCPAuthError("Longbridge MCP token payload is invalid.")
        if _is_expired(tok):
            raise MCPAuthError(
                "Longbridge MCP token is expired or has invalid expiry metadata."
            )
        self.base_url = base_url or tok.get("base_url") or DEFAULT_BASE_URL
        self.access_token = access_token
        self._id = 0
        self._tool_index: Optional[dict[str, dict]] = None  # lazy

    @property
    def tools(self) -> dict[str, dict]:
        if self._tool_index is None:
            self._tool_index = self._list_tools()
        return self._tool_index

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.access_token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in (401, 403):
                raise MCPAuthError(
                    f"Longbridge MCP authentication rejected (HTTP {e.code})."
                ) from None
            raise MCPTransportError(
                f"Longbridge MCP request failed (HTTP {e.code})."
            ) from None
        except urllib.error.URLError:
            raise MCPTransportError("Longbridge MCP network request failed.") from None

        # SSE envelope: `data: {...}\n\n`
        for line in data.splitlines():
            m = re.match(r"^data:\s*(.*)$", line)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    continue
        # Some endpoints return plain JSON
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            raise MCPTransportError(
                "Longbridge MCP response was neither SSE JSON nor plain JSON."
            ) from None

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        resp = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if "error" in resp:
            error = resp.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            safe_code = code if isinstance(code, int) else "unknown"
            raise MCPTransportError(
                f"Longbridge MCP JSON-RPC request failed (code={safe_code})."
            )
        return resp.get("result")

    def _list_tools(self) -> dict[str, dict]:
        result = self._rpc("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        index = {t["name"]: t for t in tools if "name" in t}
        return index

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        """Call a tool by MCP name and return the parsed text-payload (or raw)."""
        # Refresh the tool index if the requested tool isn't in our cache (handles
        # newly added tools after the cache was populated).
        if name not in self.tools:
            self._tool_index = None  # force re-discovery
            if name not in self.tools:
                raise MCPTransportError(
                    "Requested Longbridge MCP tool is not exposed by the server."
                )
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        return _coerce_tool_result(result)


def _coerce_tool_result(result: Any) -> Any:
    """
    MCP tool results are {content: [{type:'text', text:'...' or json}, ...], isError: bool}.

    We collapse text items: try json.loads first (most are JSON), else return raw text.
    If the result is already a primitive, pass it through.
    """
    if not isinstance(result, dict):
        return result
    if result.get("isError"):
        raise MCPTransportError("Longbridge MCP tool returned an error result.")
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return result
    # Prefer the first item that parses as JSON; else concatenate texts.
    parsed_json = None
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text") or ""
            try:
                parsed_json = json.loads(text)
                break
            except json.JSONDecodeError:
                continue
    if parsed_json is not None:
        return parsed_json
    texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(texts) if texts else result


# ---- Tool-name resolution (capability → tool name) ----
#
# Mapping below is derived from the live `/tools/list` schema reported by MCP
# server v0.7.1. Run `python -m tradingagents.dataflows.longbridge_mcp` once
# authenticated to print the current inventory + resolved capability map
# (`ping()` returns this as JSON for quick inspection).

_CAPABILITY_TO_TOOL: dict[str, str] = {
    # Internal capability tag  -> Tool name exposed by MCP server (verified 0.7.1)
    "stock_data":         "history_candlesticks_by_date",   # OHLCV with start/end filter
    "stock_recent":       "candlesticks",                   # OHLCV last N bars
    "static_info":        "static_info",                    # name, EPS, BPS, shares, dividend
    "valuation_index":    "calc_indexes",                   # PE / PB / PS / turnover_rate / mktcap
    "financial_report":   "financial_report",               # IS / BS / CF (kind + report_type)
    "technical_indicator": "quant_run",                     # PineScript V6 server-side
    "news":               "news",                           # per-symbol structured news
    "quote":              "quote",                          # snapshot
}


def _resolve_tool(client: LongbridgeMCPClient, capability: str) -> str:
    """Return the MCP tool name for `capability`. Raises if the server does
    not expose the corresponding tool (rare — tools are pretty stable)."""
    name = _CAPABILITY_TO_TOOL.get(capability)
    if name is None:
        raise MCPTransportError(f"Unknown capability '{capability}'")
    if name not in client.tools:
        # Try a one-shot re-discovery in case the index was populated when the
        # tool wasn't yet available.
        client._tool_index = None
        if name not in client.tools:
            raise MCPTransportError(
                f"Longbridge MCP capability '{capability}' is unavailable."
            )
    return name


# ---- Vendor functions (TradingAgents interface shape) ----
#
# Each returns either:
#   - a Markdown / CSV / text-block string the LLM can read directly, OR
#   - a JSON string when the data shape doesn't map cleanly to text.
# Errors are returned as `Error: ...` strings instead of raised — same
# convention as the CLI vendor.
#
# To keep this file correct under MCP tool-name uncertainty, each call uses
# `_resolve_tool()` so the first real activation rewrites the call site if the
# server's names differ from our keyword guesses.


def _client() -> LongbridgeMCPClient:
    """Construct a client, surfacing MCPAuthError upward if no token file."""
    return LongbridgeMCPClient()


# ---- news_data: per-symbol structured news ----

def get_news(
    ticker: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> NewsFeed:
    """Fetch MCP symbol news and preserve its structured metadata."""
    sym = normalize_symbol(ticker)
    client = _client()
    raw = client.call_tool(_resolve_tool(client, "news"), {"symbol": sym})
    if isinstance(raw, dict):
        rows = raw.get("items") or raw.get("news_list") or raw.get("list") or []
    else:
        rows = raw
    if not isinstance(rows, list):
        raise NoMarketDataError(ticker, sym, detail="Longbridge MCP news returned a non-list payload")
    items: list[NewsItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            published_at = parse_external_datetime(
                row.get("published_at") or row.get("publish_time") or row.get("time")
            )
        except ValueError:
            published_at = ""
        related = row.get("related_symbols") or []
        related_symbols = tuple(
            str(value).upper()
            for value in related
            if isinstance(value, str) and value.strip()
        )
        symbols = tuple(dict.fromkeys((ticker.upper(), *related_symbols)))
        items.append(NewsItem(
            source_id="",
            title=str(row.get("title") or ""),
            publisher=str(row.get("source") or row.get("source_name") or "Longbridge"),
            published_at=published_at,
            url=str(row.get("url") or ""),
            summary=str(row.get("description") or row.get("summary") or ""),
            symbols=symbols,
            vendor="longbridge_mcp",
        ))
    if not items:
        raise NoMarketDataError(ticker, sym, detail="Longbridge MCP returned no news articles")
    return NewsFeed(
        items=tuple(items), scope="ticker", requested_start=start_date,
        requested_end=end_date, query=ticker,
    )


def _format_text_table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    """Render a fixed-width table for LLM legibility (matches CLI vendor style)."""
    if not rows:
        return "(no rows)"
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(str(row[i]))) for i, w in enumerate(widths)]
    sep = "─" * (sum(widths) + 3 * (len(headers) - 1))
    lines = [
        sep,
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        sep,
    ]
    for row in rows:
        lines.append("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))
    lines.append(sep)
    return "\n".join(lines)


# 1. core_stock_apis — OHLCV via history_candlesticks_by_date

def get_stock_data(
    symbol: Annotated[str, "ticker symbol (e.g. NVDA, 1810.HK, 700.HK)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Fetch daily OHLCV via MCP `history_candlesticks_by_date`.

    Results are cached to ~/.tradingagents/cache/{SYMBOL}.csv (one file per
    symbol, accumulated over time).  Repeated calls for overlapping windows
    skip the network round-trip; the cache is refreshed only when the latest
    row is more than MAX_STALE_DAYS before end_date.

    Server schema (verified v0.7.1):
        required: symbol, period, forward_adjust, trade_sessions
        optional: start, end
    """
    from .config import get_config
    from .ohlcv_cache import (
        symbol_to_cache_key,
        read_cached_ohlcv,
        merge_and_write_ohlcv,
        normalize_ohlcv_dates,
        filter_completed_daily_bars,
    )
    from .ohlcv_model import batch_from_frame

    sym = normalize_symbol(symbol)
    cache_key = symbol_to_cache_key(sym)

    config = get_config()
    cache_dir = config["data_cache_dir"]

    # --- cache read ---
    cached = read_cached_ohlcv(
        cache_dir,
        cache_key,
        start_date,
        end_date,
        expected_vendor="longbridge_mcp",
    )
    if cached is not None:
        cached["Date"] = cached["Date"].dt.strftime("%Y-%m-%d")
        rows = list(cached[["Date", "Open", "High", "Low", "Close", "Volume"]].itertuples(index=False, name=None))
        table = _format_text_table(("Date", "Open", "High", "Low", "Close", "Volume"), rows)
        return (
            f"# Stock data for {sym} from {start_date} to {end_date}\n"
            f"# Total records: {len(rows)}\n"
            f"# Data retrieved from local cache on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + table
        )

    # --- fetch from MCP ---
    args = {
        "symbol": sym,
        "period": "day",
        "forward_adjust": False,
        "trade_sessions": "intraday",
        "start": start_date,
        "end": end_date,
    }
    try:
        client = _client()
        raw = client.call_tool(_resolve_tool(client, "stock_data"), args)
    except MCPAuthError:
        raise
    except MCPTransportError as e:
        raise MCPTransportError(f"Error fetching data for {sym}: {e}") from e

    bars = _normalize_candlesticks(raw)
    if not bars:
        raise NoMarketDataError(symbol, sym, f"no rows between {start_date} and {end_date}")

    rows = []
    for b in bars:
        rows.append((
            b.get("Date", b.get("time", b.get("timestamp", ""))),
            b.get("Open"), b.get("High"), b.get("Low"),
            b.get("Close"), b.get("Volume"),
            b.get("Date", b.get("time", b.get("timestamp", ""))),
        ))

    # --- cache write ---
    df = pd.DataFrame(
        rows,
        columns=["Date", "Open", "High", "Low", "Close", "Volume", "RawTimestamp"],
    )
    if not df.empty:
        df = normalize_ohlcv_dates(df, cache_key)
        df = filter_completed_daily_bars(df, cache_key)
        batch = batch_from_frame(
            df,
            symbol=sym,
            vendor="longbridge_mcp",
            adapter_version="longbridge_mcp_ohlcv_v1",
            timezone_semantics="utc_instant_to_exchange_trading_date",
            raw_timestamps=df["RawTimestamp"].astype(str).tolist(),
        )
        merge_and_write_ohlcv(cache_dir, cache_key, batch)
        df = df.drop(columns=["RawTimestamp"])
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        rows = list(df[["Date", "Open", "High", "Low", "Close", "Volume"]].itertuples(index=False, name=None))

    table = _format_text_table(("Date", "Open", "High", "Low", "Close", "Volume"), rows)
    return (
        f"# Stock data for {sym} from {start_date} to {end_date}\n"
        f"# Total records: {len(rows)}\n"
        f"# Data retrieved from Longbridge MCP on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        + table
    )


def _normalize_candlesticks(raw: Any) -> list[dict]:
    """
    Server returns a JSON string inside `content[0].text` that looks like a list
    of candles. Each candle is `{time, open, high, low, close, volume, turnover, ...}`.
    Unwrap to a list of dict and re-key to LLM-friendly capitalized names.
    """
    items = raw
    if isinstance(raw, dict):
        # Possibly already-wrapped — common shapes:
        #   { "candlesticks": [...] } / { "data": [...] } / { "bars": [...] }
        for k in ("candlesticks", "data", "bars", "items"):
            if isinstance(raw.get(k), list):
                items = raw[k]
                break
        else:
            items = [raw]
    if not isinstance(items, list):
        return []
    out = []
    for c in items:
        if not isinstance(c, dict):
            continue
        # Some servers return camelCase, some return Capitalized; normalize to camelCase keys.
        key_map = {
            "time": "Date", "timestamp": "Date",
            "open":  "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume", "turnover": "Turnover",
        }
        rec = {}
        for src, dst in key_map.items():
            if src in c:
                rec[dst] = c[src]
            elif dst in c:
                rec[dst] = c[dst]
        out.append(rec)
    return out


# 2. technical_indicators — quant_run server-side PineScript V6

_PINE_TEMPLATES = {
    "rsi":   "//@version=6\nindicator('RSI')\nplot(ta.rsi(close, 14))\n",
    "macd":  "//@version=6\nindicator('MACD')\n[macd_line, signal, hist] = ta.macd(close, 12, 26, 9)\nplot(macd_line)\nplot(signal)\nplot(hist)\n",
    "sma":   "//@version=6\nindicator('SMA20')\nplot(ta.sma(close, 20))\n",
    "sma50": "//@version=6\nindicator('SMA50')\nplot(ta.sma(close, 50))\n",
    "boll":  "//@version=6\nindicator('BOLL')\n[mid, upper, lower] = ta.bb(close, 20, 2)\nplot(mid)\nplot(upper)\nplot(lower)\n",
    "atr":   "//@version=6\nindicator('ATR')\nplot(ta.atr(14))\n",
    "vwma":  "//@version=6\nindicator('VWMA')\nplot(ta.vwma(close, 20))\n",
    "close_10_ema":  "//@version=6\nindicator('EMA10')\nplot(ta.ema(close, 10))\n",
    "close_50_sma":  "//@version=6\nindicator('SMA50')\nplot(ta.sma(close, 50))\n",
    "close_200_sma": "//@version=6\nindicator('SMA200')\nplot(ta.sma(close, 200))\n",
}

_INDICATOR_ALIASES = {
    "macds": "macd",
    "macdh": "macd",
    "boll_ub": "boll",
    "boll_lb": "boll",
}


def _batch_indicator_script(
    indicators: tuple[str, ...],
) -> tuple[str, list[str], list[str]]:
    """Build one multi-plot OpenPine script and its deterministic plot order."""
    lines = ["//@version=6", 'indicator("TradingAgents Indicator Batch")']
    plot_order: list[str] = []
    unsupported: list[str] = []
    macd_ready = False
    boll_ready = False
    for indicator in indicators:
        if indicator in {"macd", "macds", "macdh"}:
            if not macd_ready:
                lines.append(
                    "[batch_macd, batch_macds, batch_macdh] = "
                    "ta.macd(close, 12, 26, 9)"
                )
                macd_ready = True
            variable = {
                "macd": "batch_macd",
                "macds": "batch_macds",
                "macdh": "batch_macdh",
            }[indicator]
        elif indicator in {"boll", "boll_ub", "boll_lb"}:
            if not boll_ready:
                lines.append(
                    "[batch_boll, batch_boll_ub, batch_boll_lb] = "
                    "ta.bb(close, 20, 2)"
                )
                boll_ready = True
            variable = {
                "boll": "batch_boll",
                "boll_ub": "batch_boll_ub",
                "boll_lb": "batch_boll_lb",
            }[indicator]
        else:
            expression = {
                "rsi": "ta.rsi(close, 14)",
                "atr": "ta.atr(14)",
                "vwma": "ta.vwma(close, 20)",
                "sma": "ta.sma(close, 20)",
                "sma50": "ta.sma(close, 50)",
                "close_10_ema": "ta.ema(close, 10)",
                "close_50_sma": "ta.sma(close, 50)",
                "close_200_sma": "ta.sma(close, 200)",
            }.get(indicator)
            if expression is None:
                unsupported.append(indicator)
                continue
            variable = expression
        lines.append(f'plot({variable}, "{indicator}")')
        plot_order.append(indicator)
    lines.append('plot(close, "__reference_close")')
    plot_order.append("__reference_close")
    return "\n".join(lines) + "\n", plot_order, unsupported


def get_indicators_batch(
    symbol: str,
    indicators: list[str] | tuple[str, ...],
    curr_date: str,
    look_back_days: int,
) -> IndicatorBatch:
    """Fetch multiple indicator series in one MCP quant_run request."""
    requested = tuple(
        dict.fromkeys(
            str(item).lower().strip() for item in indicators if str(item).strip()
        )
    )
    if not requested:
        raise ValueError("At least one indicator is required")
    if len(requested) > 8:
        raise ValueError("At most 8 indicators may be requested in one batch")
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    output_days = {
        item: effective_indicator_lookback_days(item, int(look_back_days))
        for item in requested
    }
    calculation_days = max(
        indicator_calculation_lookback_days(item, output_days[item])
        for item in requested
    )
    start = (end - timedelta(days=calculation_days)).strftime("%Y-%m-%d")
    script, plot_order, unsupported = _batch_indicator_script(requested)
    client = _client()
    raw = client.call_tool(
        _resolve_tool(client, "technical_indicator"),
        {
            "symbol": normalize_symbol(symbol),
            "period": "day",
            "start": start,
            "end": (end + timedelta(days=1)).strftime("%Y-%m-%d"),
            "script": script,
        },
    )

    def parse_json(value):
        if isinstance(value, str):
            return json.loads(value)
        return value

    chart = parse_json(raw.get("chart_json")) if isinstance(raw, dict) else None
    events = parse_json(raw.get("events_json")) if isinstance(raw, dict) else None
    if not isinstance(chart, dict) or not isinstance(events, list):
        raise MCPTransportError("batch quant_run returned no structured chart/events data")

    raw_dates: list[str] = []
    for event in events:
        bar = event.get("BarStart") if isinstance(event, dict) else None
        timestamp = bar.get("timestamp") if isinstance(bar, dict) else None
        if timestamp is None:
            continue
        value = float(timestamp)
        if value > 10_000_000_000:
            value /= 1000
        raw_dates.append(datetime.fromtimestamp(value, tz=timezone.utc).isoformat())

    from .ohlcv_cache import normalize_ohlcv_dates, symbol_to_cache_key

    normalized_dates = normalize_ohlcv_dates(
        pd.DataFrame({"Date": raw_dates}),
        symbol_to_cache_key(normalize_symbol(symbol)),
    )
    dates = [pd.Timestamp(value) for value in normalized_dates["Date"]]

    graphs = chart.get("series_graphs") or {}
    items = sorted(
        graphs.items(),
        key=lambda item: int(item[0]) if str(item[0]).isdigit() else 999,
    )
    extracted: dict[str, tuple[IndicatorObservation, ...]] = {}
    for position, (_, body) in enumerate(items):
        plot = body.get("Plot") if isinstance(body, dict) else None
        values = plot.get("series") if isinstance(plot, dict) else None
        if not isinstance(values, list):
            continue
        title = str(plot.get("title") or "")
        name = title if title in plot_order else (
            plot_order[position] if position < len(plot_order) else ""
        )
        if not name:
            continue
        observations: list[IndicatorObservation] = []
        for index, value in enumerate(values):
            if index >= len(dates) or dates[index] is None or value is None:
                continue
            try:
                observations.append(IndicatorObservation(dates[index], float(value)))
            except (TypeError, ValueError):
                continue
        extracted[name] = tuple(observations)

    reference = tuple(
        item for item in extracted.get("__reference_close", ())
        if item.date <= pd.Timestamp(curr_date)
    )
    if not reference:
        raise MCPTransportError("batch quant_run returned no reference Close series")

    series: list[NormalizedIndicatorData] = []
    failures = [(item, "unsupported by Longbridge batch quant") for item in unsupported]
    for indicator in requested:
        display_start = pd.Timestamp(curr_date) - pd.Timedelta(days=output_days[indicator])
        observations = tuple(
            item for item in extracted.get(indicator, ())
            if display_start <= item.date <= pd.Timestamp(curr_date)
        )
        if not observations:
            if indicator not in unsupported:
                failures.append((indicator, "quant_run returned no series"))
            continue
        source_text = "\n".join([
            f"## {indicator} values from {display_start.strftime('%Y-%m-%d')} to {curr_date}:",
            "",
            *(f"{item.date.strftime('%Y-%m-%d')}: {item.value}" for item in observations),
            "",
            "Data Source: Longbridge MCP (batch quant_run)",
        ])
        series.append(NormalizedIndicatorData(
            indicator=indicator,
            analysis_date=pd.Timestamp(curr_date),
            observations=observations,
            bars=len(observations),
            source_text=source_text,
        ))

    latest_reference = max(reference, key=lambda item: item.date)
    return IndicatorBatch(
        symbol=normalize_symbol(symbol),
        analysis_date=curr_date,
        vendor="longbridge_mcp",
        requested_indicators=requested,
        series=tuple(series),
        latest_ohlcv_date=latest_reference.date.strftime("%Y-%m-%d"),
        reference_close=latest_reference.value,
        calculation_start=start,
        failures=tuple(failures),
    )


def get_indicators(
    symbol: Annotated[str, "ticker symbol"],
    indicator: Annotated[str, "rsi/macd/sma/sma50/boll/atr/vwma"],
    curr_date: Annotated[str, "current trading date YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """
    Run a server-side PineScript via MCP `quant_run` (MCP 0.7.1).

    Server schema:
        required: symbol, start, end
        optional: period (default day), script, input
    """
    sym = normalize_symbol(symbol)
    try:
        end = datetime.strptime(curr_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"invalid curr_date {curr_date!r}: {e}") from e

    indicator_key = _INDICATOR_ALIASES.get(indicator.lower().strip(), indicator.lower().strip())
    script = _PINE_TEMPLATES.get(indicator_key)
    if script is None:
        supported = sorted(set(_PINE_TEMPLATES) | set(_INDICATOR_ALIASES))
        raise MCPTransportError(f"unsupported indicator '{indicator}'. Supported: {supported}")

    output_lookback = effective_indicator_lookback_days(
        indicator_key, look_back_days
    )
    calculation_lookback = indicator_calculation_lookback_days(
        indicator_key, output_lookback
    )
    start = (end - timedelta(days=calculation_lookback)).strftime("%Y-%m-%d")
    # Longbridge quant uses an exclusive `end`; advance it so curr_date is
    # eligible to appear in the calculated series.
    end_s = (end + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        client = _client()
        raw = client.call_tool(
            _resolve_tool(client, "technical_indicator"),
            {"symbol": sym, "period": "day", "start": start,
             "end": end_s, "script": script},
        )
    except MCPAuthError:
        raise
    except MCPTransportError as e:
        raise MCPTransportError(f"Error calculating {indicator} for {sym}: {e}") from e

    # MCP `quant_run` returns {report_json: "...", chart_json: "...", events_json: "..."}
    # where report_json is a STRINGIFIED JSON of {data: {series_name: [{time,value}, ...]}}.
    # We re-use the CLI vendor's text-pretty-summary parse because the underlying
    # engine is the same. But on MCP we get the rich per-bar list, so we also
    # extract first/last/min/max for the summary.
    display_start = (end - timedelta(days=output_lookback)).strftime("%Y-%m-%d")
    summary = _summarize_quant_payload(
        raw,
        display_start=display_start,
        display_end=curr_date,
    )
    return (
        f"Technical Indicator Report for {sym}\n"
        f"Indicator: {indicator.upper()}\n"
        f"Report Date: {curr_date}\n"
        f"Lookback Period: {output_lookback} days\n"
        f"Calculation History: {calculation_lookback} days\n\n"
        f"Series summary (over the requested range):\n{summary}\n\n"
        f"Data Source: Longbridge MCP (quant_run)"
    )

def _summarize_quant_payload(
    raw: Any,
    *,
    display_start: str | None = None,
    display_end: str | None = None,
) -> str:
    """
    Reduce MCP quant_run response to a "Series ... last=... range=... bars=..." block.

    Verified response shape (MCP 0.7.1):
        {
          "report_json": "null",         # not populated for this version
          "chart_json":  "<stringified JSON>",
          "events_json": "<stringified JSON list of bar events>",
        }

    chart_json parses to:
        { "background_color": null,
          "series_graphs": {
            "<idx>": { "Plot": { "series": [<v0>, <v1>, ...],
                                  "title": ... , "colors": [...], ... } },
            ...
          } }

    events_json is a stringified list of {BarStart: {...timestamp...}} events
    that index-align with the per-series value arrays.

    Series names are recovered from the script (we don't have them from the
    server) by counting plots in order: 1st plot → "RSI" if single, then
    MACD/Signal/Hist, etc. Heuristic: 1 series → use the requested indicator name
    (passed in via the caller's script); N series → use generic `series_<idx>`.
    """
    if not isinstance(raw, dict):
        return f"(unexpected raw: {type(raw).__name__})"

    def _parse_str(v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v

    chart = _parse_str(raw.get("chart_json"))
    events = _parse_str(raw.get("events_json"))

    if not isinstance(chart, dict):
        return f"(no chart_json; raw keys: {list(raw.keys())})"

    series_graphs = chart.get("series_graphs") or {}
    if not isinstance(series_graphs, dict) or not series_graphs:
        return f"(empty series_graphs; raw keys: {list(chart.keys())})"

    # Extract aligned per-bar timestamps in order from events.
    bar_times: list[str] = []
    if isinstance(events, list):
        for ev in events:
            if not isinstance(ev, dict):
                continue
            bar = ev.get("BarStart") or ev.get("bar_start")
            if isinstance(bar, dict):
                ts_ms = bar.get("timestamp")
                if ts_ms is not None:
                    bar_times.append(str(ts_ms))

    series_results: list[tuple[str, list[float], list[tuple[str, float]]]] = []
    items = sorted(series_graphs.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 999)
    for idx, body in items:
        plot = body.get("Plot") if isinstance(body, dict) else None
        if not isinstance(plot, dict):
            continue
        vals = plot.get("series")
        if not isinstance(vals, list) or not vals:
            continue
        float_vals: list[float] = []
        dated_values: list[tuple[str, float]] = []
        for value_index, v in enumerate(vals):
            try:
                numeric = float(v)
                if value_index < len(bar_times):
                    timestamp = float(bar_times[value_index])
                    if timestamp > 10_000_000_000:
                        timestamp /= 1000
                    date_text = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
                    if (
                        (display_start is None or date_text >= display_start)
                        and (display_end is None or date_text <= display_end)
                    ):
                        dated_values.append((date_text, numeric))
                        float_vals.append(numeric)
                elif display_start is None and display_end is None:
                    float_vals.append(numeric)
            except (TypeError, ValueError):
                # `None` (no-data slot) — drop the entry, don't abandon the whole series
                continue
        if not float_vals:
            continue
        title = plot.get("title")
        name = title if (isinstance(title, str) and title) else f"series_{idx}"
        series_results.append((name, float_vals, dated_values))

    if not series_results:
        return f"(no series extracted; series_graphs keys: {list(series_graphs.keys())[:5]})"

    # Render summary. If exactly one series, also surface its name (we lose the
    # indicator name when the script has no `indicator('NAME')` title); pick a
    # friendly default.
    lines = []
    for name, vals, dated_values in series_results:
        if not vals:
            continue
        try:
            lines.extend(f"{date_text}: {value}" for date_text, value in dated_values)
            lines.append(
                f"  {name}: last={vals[-1]:+.2f}  range=[{min(vals):+.2f}, {max(vals):+.2f}]  bars={len(vals)}"
            )
        except ValueError:
            continue
    return "\n".join(lines) if lines else "(empty after numeric coercion)"


# 3. fundamental_data — static_info / calc_indexes / financial_report

def get_fundamentals(
    symbol: Annotated[str, "ticker symbol"],
    curr_date: Annotated[Optional[str], "current date (unused, accepted for vendor-interface compat)"] = None,
) -> str:
    """Top-line reference + valuation ratios via MCP `static_info` + `calc_indexes`.

    Both tools take `symbols` (array) per schema.
    """
    sym = normalize_symbol(symbol)
    try:
        client = _client()
        s = client.call_tool(_resolve_tool(client, "static_info"), {"symbols": [sym]})
        i = client.call_tool(_resolve_tool(client, "valuation_index"), {"symbols": [sym]})
    except MCPAuthError:
        raise
    except MCPTransportError as e:
        raise MCPTransportError(f"Error fetching fundamentals for {sym}: {e}") from e

    from .longbridge_financial_adapter import adapt_longbridge_company_reference
    return adapt_longbridge_company_reference(
        s, i, sym, "longbridge_mcp"
    )


def _first_item(raw: Any) -> dict:
    """MCP list-shaped responses usually return a list of dicts; this picks the first."""
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return raw[0]
    if isinstance(raw, dict):
        return raw
    return {}


def _get_financial_statement(
    symbol: str,
    kind: str,
    freq: Optional[str] = None,
    curr_date: Optional[str] = None,
) -> str:
    """
    IS/BS/CF via MCP `financial_report` (verified v0.7.1).

    Server schema:
        required: symbol
        optional: kind (IS/BS/CF/ALL), report_type (af/saf/q1/q2/q3/qf)

    Note: MCP flattens `kind` to a JSON key in the response: `i_s` / `b_s` / `c_f`.
    The shared CLI-vendor flattener expects `IS` / `BS` / `CF`, so we rename the
    response's section key before calling it.

    `freq` and `curr_date` are accepted to match the TradingAgents vendor interface
    signature (3-arg form: ticker, freq, curr_date); the MCP report_type is fixed
    to `qf` (quarterly full) — good enough for the LLM context window.
    """
    sym = normalize_symbol(symbol)
    args = {
        "symbol": sym,
        "kind": kind,
        "report_type": "af" if str(freq).lower() == "annual" else "qf",
    }
    try:
        client = _client()
        raw = client.call_tool(_resolve_tool(client, "financial_report"), args)
    except MCPAuthError:
        raise
    except MCPTransportError as e:
        raise MCPTransportError(f"Error fetching {args['kind']} for {sym}: {e}") from e

    # Normalize MCP's lowercase-with-underscore key back to uppercase so the CLI
    # vendored flattener picks it up unchanged.
    kind = args["kind"]
    key_remap = {"i_s": "IS", "b_s": "BS", "c_f": "CF"}
    if isinstance(raw, dict):
        report_list = raw.get("list")
        if isinstance(report_list, dict):
            for src, dst in key_remap.items():
                if src in report_list and dst not in report_list:
                    report_list[dst] = report_list.pop(src)

    from .longbridge_financial_adapter import adapt_longbridge_financial_report
    return adapt_longbridge_financial_report(raw, kind, "longbridge_mcp", sym)


def get_income_statement(
    symbol: Annotated[str, "ticker symbol"],
    freq: Annotated[Optional[str], "vendor-interface arg; pass 'IS' from graph"] = None,
    curr_date: Annotated[Optional[str], "current date (unused)"] = None,
) -> str:
    return _get_financial_statement(symbol, "IS", freq, curr_date)


def get_balance_sheet(
    symbol: Annotated[str, "ticker symbol"],
    freq: Annotated[Optional[str], "vendor-interface arg; pass 'BS' from graph"] = None,
    curr_date: Annotated[Optional[str], "current date (unused)"] = None,
) -> str:
    return _get_financial_statement(symbol, "BS", freq, curr_date)


def get_cashflow(
    symbol: Annotated[str, "ticker symbol"],
    freq: Annotated[Optional[str], "vendor-interface arg; pass 'CF' from graph"] = None,
    curr_date: Annotated[Optional[str], "current date (unused)"] = None,
) -> str:
    return _get_financial_statement(symbol, "CF", freq, curr_date)


# ---- Diagnostics ----

def ping() -> dict:
    """Smoke check: load token, hit the service, print the tool inventory snapshot."""
    client = _client()
    tools = client.tools
    return {
        "endpoint": client.base_url,
        "tool_count": len(tools),
        "tool_names": sorted(tools)[:40],
        "capability_resolution": dict(_CAPABILITY_TO_TOOL),
    }


if __name__ == "__main__":
    try:
        info = ping()
        print(json.dumps(info, indent=2, default=str))
    except MCPAuthError as e:
        print(f"NOT ACTIVATED: {e}", file=sys.stderr)
        sys.exit(2)
