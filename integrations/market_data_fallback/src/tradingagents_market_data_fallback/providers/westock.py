"""Westock CLI adapters for OHLCV and locally calculated indicators."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import pandas as pd

from tradingagents.dataflows.errors import (
    NoMarketDataError,
    VendorNotConfiguredError,
    VendorUnavailableError,
)
from tradingagents.dataflows.symbols import normalize_symbol

_SUPPORTED_INDICATORS = {
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh", "rsi", "boll", "boll_ub", "boll_lb",
    "atr", "vwma", "mfi",
}


def _westock_executable() -> str:
    configured = os.getenv("WESTOCK_CLI", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise VendorNotConfiguredError(
                "Westock CLI is missing; check the WESTOCK_CLI project setting."
            )
        return str(path)
    executable = shutil.which("westock")
    if not executable:
        raise VendorNotConfiguredError(
            "Westock CLI is missing; install it and set WESTOCK_CLI or add it to PATH."
        )
    return executable


def _westock_code(symbol: str) -> str:
    value = normalize_symbol(symbol).upper().rstrip("+")
    if value.endswith(".HK"):
        return f"hk{value[:-3].zfill(5)}"
    for suffix, prefix in ((".SH", "sh"), (".SZ", "sz"), (".BJ", "bj")):
        if value.endswith(suffix):
            return prefix + value[:-len(suffix)]
    if value.isalpha():
        return "us" + value
    return value.lower()


def _run_westock(arguments: list[str]) -> Any:
    command = [_westock_executable(), *arguments]
    # The CLI is a separate third-party process. Do not inherit the complete
    # TradingAgents environment, which may include LLM and broker credentials.
    safe_env = {
        key: os.environ[key]
        for key in (
            "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR",
            "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS",
        )
        if os.environ.get(key)
    }
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=safe_env,
        )
    except FileNotFoundError:
        raise VendorNotConfiguredError("Westock CLI executable could not be started.") from None
    except subprocess.TimeoutExpired:
        raise VendorUnavailableError("Westock request timed out.") from None
    if result.returncode:
        raise VendorUnavailableError("Westock request failed.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # The documented CLI output is a Markdown table. Preserve it for the
        # adapter parser instead of treating valid data as a transport failure.
        return result.stdout


def _markdown_table_rows(value: str) -> list[dict[str, str]]:
    """Parse Westock's pipe-delimited Markdown table output."""
    headers: list[str] | None = None
    rows: list[dict[str, str]] = []
    pending = ""

    def consume(block: str) -> None:
        nonlocal headers
        line = block.replace("\n", " ").strip()
        if not line:
            return
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        cells = [cell.strip() for cell in re.split(r"\s*\|\s*", line)]
        if cells and all(cell and set(cell) <= {"-", ":"} for cell in cells):
            return
        if headers is None:
            headers = [cell.lower() for cell in cells]
        elif len(cells) == len(headers):
            rows.append(dict(zip(headers, cells, strict=True)))

    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            if pending:
                consume(pending)
            pending = stripped
        elif pending and stripped:
            # Profile descriptions can wrap over several physical lines inside
            # a single Markdown table row.
            pending += "\n" + stripped
    if pending:
        consume(pending)
    return rows


def _published_day(row: dict[str, Any]) -> str:
    raw = (
        row.get("published_at") or row.get("publish_time") or row.get("publishedtime")
        or row.get("发布时间") or row.get("发布日期") or row.get("time")
        or row.get("date") or row.get("日期")
    )
    if not raw:
        return ""
    try:
        if isinstance(raw, (int, float)) or str(raw).strip().replace(".", "", 1).isdigit():
            epoch = float(raw)
            if epoch > 10**12:
                epoch /= 1000
            stamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
        else:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return stamp.date().isoformat()
    except (ValueError, OverflowError, OSError):
        return ""


def _fetch(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    payload = _run_westock([
        "kline", _westock_code(symbol), "--period", "day",
        "--start", start_date, "--end", end_date,
    ])
    if isinstance(payload, str):
        payload = _markdown_table_rows(payload)
    if isinstance(payload, dict):
        for key in ("data", "klines", "items", "rows"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise VendorUnavailableError("Westock returned an unexpected kline response.")

    rows = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        lowered = {str(key).lower(): value for key, value in item.items()}
        raw_date = next(
            (lowered[key] for key in ("date", "time", "timestamp", "日期", "时间") if key in lowered),
            None,
        )
        try:
            day = str(raw_date)[:10]
            datetime.strptime(day, "%Y-%m-%d")
            def field(*names: str, default: Any = None) -> Any:
                return next((lowered[name] for name in names if name in lowered), default)

            row = {
                "Date": pd.Timestamp(day),
                "Open": float(field("open", "开盘", "开盘价")),
                "High": float(field("high", "最高", "最高价")),
                "Low": float(field("low", "最低", "最低价")),
                "Close": float(field("last", "close", "收盘", "收盘价")),
                "Volume": float(field("volume", "成交量", default=0) or 0),
            }
        except (TypeError, ValueError):
            continue
        if start_date <= day <= end_date:
            rows.append(row)
    if not rows:
        raise NoMarketDataError(symbol, normalize_symbol(symbol), "Westock returned no OHLCV rows")

    frame = pd.DataFrame(rows).drop_duplicates(subset=["Date"]).sort_values("Date")
    latest = frame["Date"].max().date()
    requested = datetime.strptime(end_date, "%Y-%m-%d").date()
    stale_days = (requested - latest).days
    if stale_days > 7:
        raise NoMarketDataError(
            symbol, normalize_symbol(symbol),
            f"Westock latest row is {latest}, {stale_days} days before the requested date (stale)",
        )
    return frame.reset_index(drop=True)


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    frame = _fetch(symbol, start_date, end_date)
    lines = [
        f"# Stock data for {normalize_symbol(symbol)} from {start_date} to {end_date}",
        f"# Total records: {len(frame)}",
        "",
        "Date,Open,High,Low,Close,Volume",
    ]
    for row in frame.itertuples(index=False):
        lines.append(
            f"{row.Date:%Y-%m-%d},{row.Open},{row.High},{row.Low},{row.Close},{row.Volume}"
        )
    return "\n".join(lines)


def get_indicators(symbol: str, indicator: str, as_of_date: str, look_back_days: int) -> str:
    key = indicator.lower().strip()
    if key not in _SUPPORTED_INDICATORS:
        raise VendorNotConfiguredError(f"Westock does not support indicator {key}.")
    end = datetime.strptime(as_of_date, "%Y-%m-%d")
    # Extra calendar days cover weekends and the calculation warm-up period.
    warmup_days = 500 if key in {"close_200_sma", "macd", "macds", "macdh"} else 120
    start = (end - timedelta(days=max(int(look_back_days), warmup_days) + 60)).strftime("%Y-%m-%d")
    frame = _fetch(symbol, start, as_of_date)
    try:
        from stockstats import wrap

        calculated = wrap(frame.copy())
        calculated[key]
    except Exception as exc:
        raise VendorUnavailableError(f"Westock could not calculate {key}.") from exc

    earliest = (end - timedelta(days=int(look_back_days))).date()
    values = []
    for _, row in calculated.iterrows():
        day = pd.Timestamp(row["Date"]).date()
        if earliest <= day <= end.date():
            value = row[key]
            rendered = "N/A" if pd.isna(value) else str(value)
            values.append(f"{day.isoformat()}: {rendered}")
    if not values:
        raise NoMarketDataError(symbol, normalize_symbol(symbol), "Westock indicator series is empty")
    return (
        f"## {key} values from {earliest} to {as_of_date}:\n\n"
        + "\n".join(values)
        + "\n\nData Source: Westock"
    )


def get_fundamentals(ticker: str, curr_date: str | None = None) -> str:
    result = _run_westock(["profile", _westock_code(ticker)])
    if isinstance(result, str):
        rows = _markdown_table_rows(result)
        result = rows[0] if len(rows) == 1 else rows or None
    if isinstance(result, dict) and isinstance(result.get("data"), dict):
        profile = result["data"]
    elif isinstance(result, (dict, list)):
        profile = result
    else:
        raise NoMarketDataError(ticker, normalize_symbol(ticker), "Westock profile is unavailable")
    return (
        f"## Company profile: {normalize_symbol(ticker)}\n"
        + json.dumps(profile, ensure_ascii=False, indent=2, default=str)
        + "\n\nData Source: Westock"
    )


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    result = _run_westock(["news", "list", _westock_code(ticker), "--limit", "30"])
    if isinstance(result, dict):
        result = result.get("items") or result.get("data") or result.get("news") or []
    if isinstance(result, str):
        result = _markdown_table_rows(result)
    if not isinstance(result, list):
        raise VendorUnavailableError("Westock returned an unexpected news response.")
    lines = [f"# News for {normalize_symbol(ticker)} from {start_date} to {end_date}"]
    for article in result:
        if not isinstance(article, dict):
            continue
        normalized_article = {str(key).lower(): value for key, value in article.items()}
        day = _published_day(normalized_article)
        if not day or not start_date <= day <= end_date:
            continue
        title = str(normalized_article.get("title") or normalized_article.get("news_title") or normalized_article.get("标题") or "No title").replace("\n", " ")
        source = str(normalized_article.get("source") or normalized_article.get("src") or "Westock")
        summary = str(normalized_article.get("summary") or normalized_article.get("digest") or "").replace("\n", " ")
        url = str(normalized_article.get("url") or normalized_article.get("news_url") or normalized_article.get("link") or "")
        lines.append(f"- {day} | {source} | {title}\n  {summary}\n  {url}")
    if len(lines) == 1:
        raise NoMarketDataError(ticker, normalize_symbol(ticker), "Westock returned no dated news in the requested window")
    return "\n".join(lines)


def get_global_news(as_of_date: str, look_back_days: int | None = None, limit: int | None = None) -> str:
    look_back_days = int(look_back_days or 7)
    limit = int(limit or 10)
    start = (datetime.strptime(as_of_date, "%Y-%m-%d") - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    result = _run_westock(["hot", "news", "--limit", str(limit)])
    if isinstance(result, str):
        result = _markdown_table_rows(result)
    if isinstance(result, dict):
        result = result.get("items") or result.get("data") or result.get("news") or []
    if not isinstance(result, list):
        raise VendorUnavailableError("Westock returned an unexpected global-news response.")
    lines = [f"## Global market news from {start} to {as_of_date}"]
    for article in result:
        if not isinstance(article, dict):
            continue
        normalized_article = {str(key).lower(): value for key, value in article.items()}
        day = _published_day(normalized_article)
        if not day or not start <= day <= as_of_date:
            continue
        title = str(normalized_article.get("news_title") or normalized_article.get("title") or normalized_article.get("标题") or "No title").replace("\n", " ")
        source = str(normalized_article.get("source") or "Westock")
        summary = str(normalized_article.get("summary") or normalized_article.get("digest") or "").replace("\n", " ")
        url = str(normalized_article.get("url") or normalized_article.get("news_url") or normalized_article.get("link") or "")
        lines.append(f"- {day} | {source} | {title}\n  {summary}\n  {url}")
    if len(lines) == 1:
        raise NoMarketDataError(as_of_date, detail="Westock returned no dated global news in the requested window")
    return "\n".join(lines)
