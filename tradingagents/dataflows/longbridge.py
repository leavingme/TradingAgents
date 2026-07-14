"""
Longbridge data vendor — CLI subprocess implementation.

Single source of truth for Longbridge integration in TradingAgents.
Replaces the original longport SDK path (kept as `longbridge_sdk_legacy.py.bak`)
because the CLI (v0.24.0) is what we authenticated against and has more
capabilities (financial-report, calc-index, quant indicators) than the SDK.

Auth: relies on the user having run `longbridge auth login` (OAuth token at
~/.longbridge/openapi/tokens/<client_id>). No environment variables needed
at runtime — the CLI manages its own token. The .env LONGBRIDGE_*_* values
are kept for backward compatibility with the SDK path only.

Supported vendor slots (see interface.py):
    core_stock_apis       -> longbridge kline (OHLCV)
    technical_indicators  -> longbridge quant run (PineScript V6 server-side)
    fundamental_data      -> longbridge static + calc-index + financial-report
    news_data             -> longbridge news / news search

CLI subcommands used:
    kline <sym>                       -- daily OHLCV
    static <sym>                      -- name, EPS, BPS, shares, dividend
    calc-index <sym>                  -- PE / PB / PS / turnover_rate / mktcap
    financial-report <sym> --kind IS  -- income statement (also BS / CF)
    quant run <sym> ... --script ...  -- server-side indicator computation

Output format: all calls use `--format json` so we can parse JSON deterministically.
"""
from typing import Annotated, Optional
import ast
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from .errors import NoMarketDataError
from .evidence_models import NewsFeed, NewsItem, parse_external_datetime
from .indicator_requirements import (
    effective_indicator_lookback_days,
    indicator_calculation_lookback_days,
)


# ---- Symbol normalization (matches TradingAgents conventions) ----

def normalize_symbol(symbol: str) -> str:
    """
    Normalize a stock symbol to Longbridge's <CODE>.<MARKET> format.

    Examples:
        1810.HK        -> 1810.HK         (HK, kept as-is)
        0700.HK        -> 700.HK          (leading zero stripped — Longbridge convention)
        NVDA           -> NVDA.US
        AAPL.US        -> AAPL.US
        600519.SH      -> 600519.SH
        1810           -> 1810.HK         (pure digits default to HK)
    """
    s = symbol.upper().strip()
    if not s:
        return s

    # Already qualified — strip HK leading zeros (Longbridge convention)
    if "." in s:
        code, _, market = s.partition(".")
        if market.upper() == "HK":
            code = code.lstrip("0") or "0"
            return f"{code}.{market.upper()}"
        return s

    # Pure digits → HK
    if s.isdigit():
        return f"{s.lstrip('0') or '0'}.HK"

    # Letter code → US
    return f"{s}.US"


# ---- Subprocess helper ----

class LongbridgeCLIError(RuntimeError):
    """Raised when the longbridge CLI returns a non-zero exit, bad JSON,
    or a quota/auth error. route_to_vendor only falls back on
    AlphaVantageRateLimitError by default; this error type is for
    non-recoverable failures."""


def _run_cli(args: list[str], timeout: int = 30) -> str:
    """Run `longbridge <args>`, return stdout. Raise LongbridgeCLIError on failure."""
    cmd = ["longbridge", *args, "--format", "json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        raise LongbridgeCLIError(
            "`longbridge` CLI not found in PATH. Install: "
            "curl -sSL https://open.longbridge.com/longbridge/longbridge-terminal/install | sh"
        )
    except subprocess.TimeoutExpired:
        raise LongbridgeCLIError(f"longbridge timeout after {timeout}s: {' '.join(cmd)}")

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        # Common terminal errors worth surfacing raw
        raise LongbridgeCLIError(
            f"longbridge exited {proc.returncode}: {' '.join(cmd)}\nstderr: {stderr or '(empty)'}"
        )
    return proc.stdout


def _run_cli_json(args: list[str], timeout: int = 30) -> Any:
    """Run CLI and parse JSON stdout. Empty stdout → return []. Non-JSON → raise."""
    out = _run_cli(args, timeout=timeout)
    out = out.strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise LongbridgeCLIError(f"longbridge returned non-JSON output: {e}\nFirst 200 chars: {out[:200]}")


def _run_cli_json_dict(args: list[str], timeout: int = 30) -> dict:
    """Variant of _run_cli_json that asserts a JSON object (dict) at the top level."""
    result = _run_cli_json(args, timeout=timeout)
    if not isinstance(result, dict):
        raise LongbridgeCLIError(f"Expected JSON object from: {' '.join(['longbridge', *args])}")
    return result


def _run_cli_json_list(args: list[str], timeout: int = 30) -> list:
    """Variant of _run_cli_json that asserts a JSON array (list) at the top level."""
    result = _run_cli_json(args, timeout=timeout)
    if not isinstance(result, list):
        raise LongbridgeCLIError(f"Expected JSON array from: {' '.join(['longbridge', *args])}")
    return result


# ---- Required env helper (kept for backward compat with test fixtures) ----

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# ---- news_data: structured latest/search results ----

def _news_rows_to_feed(
    rows: object,
    *,
    vendor: str,
    scope: str,
    start_date: str,
    end_date: str,
    query: str,
    symbol: str | None = None,
    load_missing_body: bool = False,
) -> NewsFeed:
    """Map Longbridge JSON rows directly into the auditable news model."""
    if not isinstance(rows, list):
        raise NoMarketDataError(query, detail="Longbridge news returned a non-list payload")
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
        requested_symbols = (str(symbol).upper(),) if symbol else ()
        symbols = tuple(dict.fromkeys((*requested_symbols, *related_symbols)))
        summary = str(
            row.get("description") or row.get("excerpt") or row.get("summary") or ""
        ).strip()
        if not summary and load_missing_body and row.get("id"):
            # The symbol-news list is structured JSON but currently omits body
            # text. `news detail` is the same Longbridge source/capability and
            # returns the full article as Markdown; keep a bounded excerpt as
            # untrusted evidence rather than treating a headline as a body.
            summary = _run_cli(
                ["news", "detail", str(row["id"])], timeout=30
            ).strip()[:4000]
        items.append(NewsItem(
            source_id="",
            title=str(row.get("title") or ""),
            publisher=str(
                row.get("source_name") or row.get("source") or "Longbridge"
            ),
            published_at=published_at,
            url=str(row.get("url") or ""),
            summary=summary,
            symbols=symbols,
            vendor=vendor,
        ))
    if not items:
        raise NoMarketDataError(query, detail="Longbridge returned no news articles")
    return NewsFeed(
        items=tuple(items),
        scope=scope,
        requested_start=start_date,
        requested_end=end_date,
        query=query,
    )


def get_news(
    ticker: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> NewsFeed:
    """Fetch latest symbol news; the router enforces the requested date window."""
    from .config import get_config

    rows = _run_cli_json_list([
        "news", normalize_symbol(ticker), "--count",
        str(get_config()["news_article_limit"]),
    ])
    return _news_rows_to_feed(
        rows, vendor="longbridge", scope="ticker", start_date=start_date,
        end_date=end_date, query=ticker, symbol=ticker, load_missing_body=True,
    )


def get_global_news(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> NewsFeed:
    """Search Longbridge's structured news index for current macro headlines."""
    from .config import get_config

    config = get_config()
    look_back_days = int(look_back_days or config["global_news_lookback_days"])
    limit = int(limit or config["global_news_article_limit"])
    end = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (end - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    query = " ".join(config.get("global_news_queries") or []).strip()
    if not query:
        query = "Federal Reserve inflation GDP market outlook"
    rows = _run_cli_json_list(["news", "search", query, "--count", str(limit)])
    return _news_rows_to_feed(
        rows, vendor="longbridge", scope="global", start_date=start_date,
        end_date=curr_date, query=query,
    )


# ---- core_stock_apis: OHLCV via `longbridge kline` ----

def get_stock_data(
    symbol: Annotated[str, "ticker symbol (e.g. NVDA, 1810.HK, 700.HK)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Fetch daily OHLCV data via `longbridge kline`, then filter to [start_date, end_date].

    Results are cached to ~/.tradingagents/cache/{SYMBOL}.csv (one file per
    symbol, accumulated over time).  Repeated calls for overlapping windows
    skip the subprocess round-trip; the cache is refreshed only when the latest
    row is more than MAX_STALE_DAYS before end_date.

    Returns a CSV string with the same shape TradingAgents expects (Date, Open,
    High, Low, Close, Volume), prefixed with a # comment header for LLM context.
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
    cached = read_cached_ohlcv(cache_dir, cache_key, start_date, end_date)
    if cached is not None:
        cached = cached.set_index("Date")
        return (
            f"# Stock data for {sym} from {start_date} to {end_date}\n"
            f"# Total records: {len(cached)}\n"
            f"# Data retrieved from local cache on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + cached.to_csv()
        )

    # --- fetch from CLI ---
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"invalid date format (need yyyy-mm-dd): {e}") from e

    span_days = max((end - start).days + 1, 30)
    count = min(max(span_days + 5, 30), 500)

    try:
        raw = _run_cli_json_list(["kline", sym, "--period", "day", "--count", str(count)])
    except LongbridgeCLIError as e:
        raise LongbridgeCLIError(f"Error fetching data for {sym}: {e}") from e

    if not raw:
        raise NoMarketDataError(symbol, sym, f"no rows between {start_date} and {end_date}")

    rows = []
    for k in raw:
        ts = k.get("time", "")
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        rows.append({
            "Date": d,
            "Open": float(k.get("open", 0)),
            "High": float(k.get("high", 0)),
            "Low": float(k.get("low", 0)),
            "Close": float(k.get("close", 0)),
            "Volume": int(float(k.get("volume", 0))),
            "RawTimestamp": str(ts),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        raise NoMarketDataError(symbol, sym, "no parseable OHLCV rows")

    df = normalize_ohlcv_dates(df, cache_key)
    df = df[(df["Date"] >= pd.to_datetime(start_date)) & (df["Date"] <= pd.to_datetime(end_date))]
    df = filter_completed_daily_bars(df, cache_key)
    df = df.sort_values("Date")
    if df.empty:
        raise NoMarketDataError(symbol, sym, f"no completed rows between {start_date} and {end_date}")

    # --- cache write ---
    batch = batch_from_frame(
        df,
        symbol=sym,
        vendor="longbridge",
        adapter_version="longbridge_cli_ohlcv_v1",
        timezone_semantics="utc_instant_to_exchange_trading_date",
        raw_timestamps=df["RawTimestamp"].astype(str).tolist(),
    )
    merge_and_write_ohlcv(cache_dir, cache_key, batch)

    df = df.drop(columns=["RawTimestamp"])
    df = df.set_index("Date")
    header = (
        f"# Stock data for {sym} from {start_date} to {end_date}\n"
        f"# Total records: {len(df)}\n"
        f"# Data retrieved from Longbridge CLI on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    return header + df.to_csv()


# ---- technical_indicators: via `longbridge quant run` (PineScript V6) ----
#
# PineScript V6 indicator scripts we use server-side. longbridge CLI executes them
# against its own K-line data and returns plot values. This is remote server
# computation: published OpenAPI/quant service limits still apply; it is not a
# local or unlimited path and has no stockstats dependency.
#
# Each script is intentionally minimal: it emits a single `plot(...)` whose value
# is the indicator we want. The CLI returns the last value in the date range.

_PINE_TEMPLATES = {
    "rsi": """
//@version=6
indicator("RSI")
length = input.int(14, "Length")
plot(ta.rsi(close, length), "rsi")
""",
    "macd": """
//@version=6
indicator("MACD")
[macd, signal, hist] = ta.macd(close, 12, 26, 9)
plot(macd, "macd")
plot(signal, "signal")
plot(hist, "hist")
""",
    "sma": """
//@version=6
indicator("SMA20")
plot(ta.sma(close, 20), "sma20")
""",
    "sma50": """
//@version=6
indicator("SMA50")
plot(ta.sma(close, 50), "sma50")
""",
    "boll": """
//@version=6
indicator("BOLL")
[mid, up, low] = ta.bb(close, 20, 2)
plot(mid, "mid")
plot(up, "up")
plot(low, "low")
""",
    "atr": """
//@version=6
indicator("ATR")
plot(ta.atr(14), "atr")
""",
    "vwma": """
//@version=6
indicator("VWMA")
plot(ta.vwma(close, 20), "vwma")
""",
    "close_10_ema": """
//@version=6
indicator("EMA10")
plot(ta.ema(close, 10), "ema10")
""",
    "close_50_sma": """
//@version=6
indicator("SMA50")
plot(ta.sma(close, 50), "sma50")
""",
    "close_200_sma": """
//@version=6
indicator("SMA200")
plot(ta.sma(close, 200), "sma200")
""",
}

_INDICATOR_ALIASES = {
    "macds": "macd",
    "macdh": "macd",
    "boll_ub": "boll",
    "boll_lb": "boll",
}


def _run_quant(symbol: str, start_date: str, end_date: str, indicator: str) -> dict:
    """
    Submit a PineScript to `longbridge quant run` and parse the default
    `pretty` summary (Series / First / Last / Min / Max). NOTE: the CLI
    currently returns an impoverished JSON payload (`chart_json=""`,
    `report_json="null"`) even when the indicator has computed values — we
    therefore ask the CLI for the `pretty` summary it renders correctly, and
    parse the Series/First/Last/Min/Max row back into a dict.

    Returned dict shape:
        {
          "series_name": {
            "bars": <int>,
            "first": <float>,
            "last":  <float>,
            "min":   <float>,
            "max":   <float>,
          },
          ...
        }
    """
    key = _INDICATOR_ALIASES.get(indicator.lower().strip(), indicator.lower().strip())
    script = _PINE_TEMPLATES.get(key)
    if script is None:
        raise LongbridgeCLIError(
            f"Unsupported indicator '{indicator}'. Supported: {sorted(_PINE_TEMPLATES)}"
        )
    args = [
        "quant", "run", symbol,
        "--period", "day",
        "--start", start_date,
        "--end", end_date,
        "--script", script,
        # NOTE: no --format json — that path drops the computed values; we
        # rely on the default `pretty` summary instead.
    ]
    proc = subprocess.run(
        ["longbridge", *args],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    if proc.returncode != 0:
        raise LongbridgeCLIError(
            f"longbridge quant run exited {proc.returncode}: stderr={proc.stderr.strip()}"
        )
    out = proc.stdout

    # Strip ANSI escape codes (the Series row is colored) before parsing.
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    out = ansi_re.sub("", out)

    # Lines look like:
    #   Series                │    20│   +100.00│    +37.94│    +22.17│   +100.00 ⠀⣀⣤...
    # We parse line-by-line (instead of finditer across the whole string) because
    # the separator row `─────...` and the actual Series row are adjacent and can
    # get merged into a single match when MULTILINE is used.
    line_re = re.compile(
        r"^\s*(\S+(?:\s\S+)*?)\s*│\s*(\d+)\s*│\s*([+\-]?\d+\.?\d*)\s*│\s*"
        r"([+\-]?\d+\.?\d*)\s*│\s*([+\-]?\d+\.?\d*)\s*│\s*([+\-]?\d+\.?\d*)"
    )
    parsed: dict = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or set(line) <= {"─", " ", "-", "\u2500"}:
            continue
        m = line_re.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        if name.lower().startswith("series"):
            # header row `Series   │  Bars│     First│...`
            continue
        parsed[name] = {
            "bars": int(m.group(2)),
            "first": float(m.group(3)),
            "last": float(m.group(4)),
            "min": float(m.group(5)),
            "max": float(m.group(6)),
        }
    if not parsed:
        raise LongbridgeCLIError(
            f"quant run returned no parseable series for {symbol} (indicator={indicator}):\n{out[:500]}"
        )
    return parsed


def get_indicators(
    symbol: Annotated[str, "ticker symbol"],
    indicator: Annotated[str, "technical indicator (rsi / macd / sma / sma50 / boll / atr / vwma)"],
    curr_date: Annotated[str, "current trading date YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """
    Fetch a technical indicator for `symbol` over the past `look_back_days` days
    ending at `curr_date`, by running a PineScript via `longbridge quant run`.

    Returned as a structured text report that mirrors what the legacy
    longbridge.py / alpha_vantage / westock paths produce, so downstream agents
    don't need to know which vendor answered.
    """
    sym = normalize_symbol(symbol)
    try:
        end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"invalid curr_date {curr_date!r}: {e}") from e
    indicator_key = _INDICATOR_ALIASES.get(indicator.lower().strip(), indicator.lower().strip())
    output_lookback = effective_indicator_lookback_days(
        indicator_key, look_back_days
    )
    calculation_lookback = indicator_calculation_lookback_days(
        indicator_key, output_lookback
    )
    start_dt = end_dt - timedelta(days=calculation_lookback)
    start_iso = start_dt.strftime("%Y-%m-%d")
    # Longbridge quant treats `end` as an exclusive boundary.
    end_iso = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        result = _run_quant(sym, start_iso, end_iso, indicator)
    except LongbridgeCLIError as e:
        raise LongbridgeCLIError(f"Error calculating {indicator} for {sym}: {e}") from e

    # The CLI returns a JSON object whose top level is {"list": {kind: {...}}, "report": {...}}.
    # The actual indicator series is at report.list[kind].indicators[] where each has
    # `title` (the group name e.g. 每股收益), `accounts` (a STRINGIFIED Python literal
    # list — the inner dicts each carry `name` (e.g. 每股收益(USD)), `values` (list of
    # period dicts)). We flatten each group's most recent value.
    series_data = result  # rename for clarity: this is the parsed quant pretty summary
    if not series_data:
        return f"No {indicator} data returned for {sym} between {start_iso} and {end_iso}"

    lines = [
        f"Technical Indicator Report for {sym}",
        f"Indicator: {indicator.upper()}",
        f"Report Date: {curr_date}",
        f"Lookback Period: {output_lookback} days",
        f"Calculation History: {calculation_lookback} days",
        "",
        "Series summary (over the requested range):",
    ]
    for series_name, stats in series_data.items():
        lines.append(
            f"  {series_name}: last={stats['last']:+.2f}  "
            f"range=[{stats['min']:+.2f}, {stats['max']:+.2f}]  bars={stats['bars']}"
        )

    lines.append("")
    lines.append("Data Source: Longbridge CLI (quant run, PineScript V6)")
    return "\n".join(lines)


# ---- fundamental_data: combine static + calc-index + financial-report ----
#
# TradingAgents splits fundamentals into 5 tools: get_fundamentals,
# get_balance_sheet, get_cashflow, get_income_statement, get_insider_transactions.
# The CLI's `static` returns the OVERVIEW-style top-line (EPS, BPS, dividend),
# `calc-index` returns PE/PB/PS/turnover/mktcap, and `financial-report`
# returns the full IS/BS/CF tree in one call. We expose all 5 entry points so
# the router can route each one correctly.

def get_fundamentals(
    symbol: Annotated[str, "ticker symbol"],
    curr_date: str | None = None,
) -> object:
    """
    Top-line fundamentals summary (name, EPS, BPS, shares, dividend)
    plus valuation ratios (PE / PB / PS / turnover_rate / mktcap).
    """
    sym = normalize_symbol(symbol)
    static_raw = _run_cli_json_list(["static", sym])
    idx_raw = _run_cli_json_list(["calc-index", sym])
    from .longbridge_financial_adapter import adapt_longbridge_company_reference
    return adapt_longbridge_company_reference(
        static_raw, idx_raw, sym, "longbridge"
    )


def _flatten_financial(report: dict, kind: str, sym: str) -> str:
    """
    Flatten a `financial-report` JSON into a compact key=value report.

    Real CLI schema (verified on v0.24.0):
        report.list[kind].indicators[i] = {
            "title":   "每股收益",          # group name (the line item group)
            "accounts": "[{...}, ...]",  # STRINGIFIED Python literal of a list;
                                         # each dict has name='每股收益(USD)', values=[...]
        }
    We flatten each account's most-recent period value.
    """
    if not report:
        return f"No {kind} data for {sym}"

    root = report.get("list", {}).get(kind)
    if not isinstance(root, dict):
        return f"No {kind} section for {sym}"

    indicators = root.get("indicators", [])
    if not indicators:
        return f"No {kind} indicators for {sym}"

    lines = [f"# {kind} (Income/BS/CF) for {sym}", ""]
    for ind in indicators:
        group = ind.get("title") or ind.get("short_title") or "(group)"
        accounts_raw = ind.get("accounts")
        if isinstance(accounts_raw, str):
            try:
                accounts = ast.literal_eval(accounts_raw)
            except (ValueError, SyntaxError) as e:
                lines.append(f"## {group}  (parse error: {e})")
                continue
        elif isinstance(accounts_raw, list):
            accounts = accounts_raw
        else:
            accounts = []

        if not accounts:
            lines.append(f"## {group}")
            lines.append("  (no values)")
            continue

        lines.append(f"## {group}")
        for acct in accounts:
            if not isinstance(acct, dict):
                continue
            name = acct.get("name", "(item)")
            values = acct.get("values", [])
            if not values:
                lines.append(f"  {name}: n/a")
                continue
            first = values[0]
            val = first.get("value", "n/a")
            period = first.get("period", "")
            yoy = first.get("yoy", "")
            yoy_str = f"  yoy={yoy}" if yoy not in ("", None) else ""
            period_str = f"  [{period}]" if period else ""
            lines.append(f"  {name}: {val}{period_str}{yoy_str}")

    lines.append("")
    lines.append(f"Data retrieved from Longbridge CLI on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)


def get_income_statement(
    symbol: Annotated[str, "ticker symbol"],
    freq: str | None = None,
    curr_date: str | None = None,
) -> str:
    sym = normalize_symbol(symbol)
    try:
        raw = _run_cli_json_dict(["financial-report", sym, "--kind", "IS"])
    except LongbridgeCLIError as e:
        raise LongbridgeCLIError(f"Error fetching IS for {sym}: {e}") from e
    from .longbridge_financial_adapter import adapt_longbridge_financial_report
    return adapt_longbridge_financial_report(raw, "IS", "longbridge", sym)


def get_balance_sheet(
    symbol: Annotated[str, "ticker symbol"],
    freq: str | None = None,
    curr_date: str | None = None,
) -> str:
    sym = normalize_symbol(symbol)
    try:
        raw = _run_cli_json_dict(["financial-report", sym, "--kind", "BS"])
    except LongbridgeCLIError as e:
        raise LongbridgeCLIError(f"Error fetching BS for {sym}: {e}") from e
    from .longbridge_financial_adapter import adapt_longbridge_financial_report
    return adapt_longbridge_financial_report(raw, "BS", "longbridge", sym)


def get_cashflow(
    symbol: Annotated[str, "ticker symbol"],
    freq: str | None = None,
    curr_date: str | None = None,
) -> str:
    sym = normalize_symbol(symbol)
    try:
        raw = _run_cli_json_dict(["financial-report", sym, "--kind", "CF"])
    except LongbridgeCLIError as e:
        raise LongbridgeCLIError(f"Error fetching CF for {sym}: {e}") from e
    from .longbridge_financial_adapter import adapt_longbridge_financial_report
    return adapt_longbridge_financial_report(raw, "CF", "longbridge", sym)


# ---- Compat aliases (legacy SDK path exposed the same names) ----

# Keep the old names alive for any caller that imports them directly.
get_longbridge_stock_data = get_stock_data
get_longbridge_indicators = get_indicators


# ---- CLI self-check (used by tests) ----

def ping() -> dict:
    """
    Cheap connectivity check: run `longbridge check` and `longbridge quote NVDA.US`.
    Returns dict with status / version / quote fields. Raises LongbridgeCLIError on failure.
    """
    version_proc = subprocess.run(
        ["longbridge", "--version"], capture_output=True, text=True, timeout=10
    )
    version = (version_proc.stdout or "").strip()
    quote_raw = _run_cli_json_list(["quote", "NVDA.US"])
    quote_first = quote_raw[0] if isinstance(quote_raw[0], dict) else {}
    return {
        "version": version,
        "symbol": quote_first.get("symbol"),
        "last": quote_first.get("last"),
    }


if __name__ == "__main__":
    # Lightweight manual smoke: `python tradingagents/dataflows/longbridge.py NVDA`
    arg = sys.argv[1] if len(sys.argv) > 1 else "NVDA.US"
    sym = normalize_symbol(arg)
    print(f"== longbridge vendor smoke ({sym}) ==")
    print("-- ping --")
    print(ping())
    print("-- get_stock_data (last 5 trading days) --")
    end = datetime.now().date()
    start = end - timedelta(days=10)
    print(get_stock_data(sym, start.isoformat(), end.isoformat()))
    print("-- get_indicators (rsi, 20d) --")
    print(get_indicators(sym, "rsi", end.isoformat(), 20))
    print("-- get_fundamentals --")
    print(get_fundamentals(sym))
