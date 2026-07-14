"""Live OHLCV provider capability checks.

Run explicitly when you want to evaluate the real providers:

    RUN_OHLCV_PROVIDER_REQUIREMENTS=1 \
      venv/bin/python3.12 -m pytest tests/test_ohlcv_provider_requirements.py -q
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import StringIO
import json
import os
import subprocess
import time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from tradingagents.dataflows.interface import VENDOR_METHODS
from tradingagents.dataflows.ohlcv_cache import latest_completed_daily_bar_date
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.symbol_utils import to_westock_code

try:
    from tradingagents.dataflows.longbridge_mcp import _client as _longbridge_mcp_client
    from tradingagents.dataflows.longbridge_mcp import _resolve_tool as _resolve_longbridge_mcp_tool
except Exception:  # pragma: no cover - longbridge_mcp may be unavailable in some envs
    _longbridge_mcp_client = None
    _resolve_longbridge_mcp_tool = None


MARKET_PROBES = {
    "US": "NVDA",
    "CN": "000001.SZ",
    "HK": "0700.HK",
}
WINDOW_DAYS = 45
REQUIRED_FIELDS = {"Date", "Open", "High", "Low", "Close", "Volume"}
INDICATOR_BASKET = ("close_50_sma", "rsi", "macd", "boll")
MIN_ROW_COVERAGE = 0.75
MAX_OHLCV_LATENCY_MS = 15_000
MIN_INDICATOR_PASS_COUNT = 3


def _enabled_core_vendors() -> list[str]:
    override = os.environ.get("OHLCV_PROVIDER_REQUIREMENTS_VENDORS")
    chain = override or DEFAULT_CONFIG["data_vendors"]["core_stock_apis"]
    return [vendor.strip() for vendor in chain.split(",") if vendor.strip()]


def _start_end(
    cache_key: str,
    now: datetime | None = None,
) -> tuple[str, str, int]:
    end = latest_completed_daily_bar_date(cache_key, now).date()
    start = end - timedelta(days=WINDOW_DAYS)
    expected_rows = _weekday_count(start, end)
    return start.isoformat(), end.isoformat(), expected_rows


@pytest.mark.unit
def test_provider_window_excludes_a_still_forming_daily_bar():
    before_close = datetime(
        2026, 7, 10, 15, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")
    )
    start_iso, end_iso, expected_rows = _start_end("0700.HK", before_close)

    assert start_iso == "2026-05-25"
    assert end_iso == "2026-07-09"
    assert expected_rows == _weekday_count(date(2026, 5, 25), date(2026, 7, 9))


def _looks_transient(text: object) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "rate limit",
            "service limit",
            "服务限频",
            "timeout",
            "temporarily unavailable",
        )
    )


def _call_stock_data_with_retry(fn, symbol: str, start_iso: str, end_iso: str, attempts: int = 2):
    last_raw = None
    for attempt in range(attempts):
        raw = fn(symbol, start_iso, end_iso)
        last_raw = raw
        if not _looks_transient(raw):
            return raw
        if attempt + 1 < attempts:
            time.sleep(1.0)
    raise RuntimeError(str(last_raw))


def _parse_ohlcv_payload(raw: object) -> pd.DataFrame:
    if isinstance(raw, pd.DataFrame):
        return raw.reset_index() if "Date" not in raw.columns else raw

    text = str(raw or "").strip()
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    if lines and "," in lines[0]:
        return pd.read_csv(StringIO("\n".join(lines)))

    from tradingagents.dataflows.market_data_validator import _parse_vendor_csv

    return _parse_vendor_csv(raw)


def _latest_date(df: pd.DataFrame) -> str | None:
    if df.empty or "Date" not in df.columns:
        return None
    series = pd.to_datetime(df["Date"], errors="coerce")
    series = series.dropna()
    if series.empty:
        return None
    latest = series.max()
    return latest.strftime("%Y-%m-%d")


def _weekday_count(start: date, end: date) -> int:
    days = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def _indicator_result_ok(result: object) -> bool:
    text = str(result or "").strip()
    if not text:
        return False
    lowered = text[:500].lower()
    return not any(
        marker in lowered
        for marker in (
            "no ",
            "error",
            "rate limit",
            "premium endpoint",
            "not configured",
            "unavailable",
            "api key",
            "exception",
        )
    )


def _probe_longbridge_cli_minute(symbol: str) -> bool:
    proc = subprocess.run(
        ["longbridge", "kline", symbol, "--period", "1m", "--count", "1", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    if proc.returncode != 0:
        return False
    try:
        payload = json.loads(proc.stdout or "null")
    except Exception:
        return False
    return isinstance(payload, list) and bool(payload)


def _probe_westock_minute(symbol: str) -> bool:
    w_code = to_westock_code(symbol)
    proc = subprocess.run(
        [
            "node",
            "/data/hermes/skills/westock-data/scripts/index.js",
            "kline",
            w_code,
            "--period",
            "m1",
            "--start",
            date.today().isoformat(),
            "--end",
            date.today().isoformat(),
            "--limit",
            "1",
            "--raw",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    try:
        raw = json.loads(proc.stdout or "null")
    except Exception:
        return False
    if isinstance(raw, list) and raw:
        return True
    return False


def _probe_longbridge_mcp_minute(symbol: str) -> bool:
    if _longbridge_mcp_client is None or _resolve_longbridge_mcp_tool is None:
        return False
    try:
        client = _longbridge_mcp_client()
        tool = _resolve_longbridge_mcp_tool(client, "stock_recent")
        out = client.call_tool(tool, {"symbol": symbol, "period": "1m", "count": 1})
        return isinstance(out, list) and bool(out)
    except Exception:  # noqa: BLE001 - live capability probe should degrade cleanly
        return False


@pytest.mark.integration
def test_configured_ohlcv_providers_meet_data_requirements():
    if os.environ.get("RUN_OHLCV_PROVIDER_REQUIREMENTS") != "1":
        pytest.skip("set RUN_OHLCV_PROVIDER_REQUIREMENTS=1 to run live provider checks")

    failures = []

    for vendor in _enabled_core_vendors():
        stock_fn = VENDOR_METHODS["get_stock_data"].get(vendor)
        indicator_fn = VENDOR_METHODS["get_indicators"].get(vendor)
        if not callable(stock_fn):
            failures.append(f"{vendor}: missing get_stock_data implementation")
            continue
        if not callable(indicator_fn):
            failures.append(f"{vendor}: missing get_indicators implementation")
            continue

        for market, symbol in MARKET_PROBES.items():
            start_iso, end_iso, expected_rows = _start_end(symbol)
            started = time.perf_counter()
            try:
                raw = _call_stock_data_with_retry(stock_fn, symbol, start_iso, end_iso)
                duration_ms = round((time.perf_counter() - started) * 1000)
                df = _parse_ohlcv_payload(raw)
            except Exception as exc:  # noqa: BLE001 - live diagnostics should surface provider errors
                failures.append(f"{vendor} {market}: OHLCV call failed: {type(exc).__name__}: {exc}")
                continue

            normalized_fields = {str(column).strip().lower() for column in df.columns}
            missing = {field for field in REQUIRED_FIELDS if field.lower() not in normalized_fields}
            row_coverage = len(df) / max(expected_rows, 1)
            latest = _latest_date(df)
            if missing:
                failures.append(f"{vendor} {market}: missing OHLCV fields {sorted(missing)}")
            if row_coverage < MIN_ROW_COVERAGE:
                failures.append(
                    f"{vendor} {market}: row coverage {len(df)}/{expected_rows} below {MIN_ROW_COVERAGE:.0%}"
                )
            if duration_ms > MAX_OHLCV_LATENCY_MS:
                failures.append(
                    f"{vendor} {market}: OHLCV latency {duration_ms}ms above {MAX_OHLCV_LATENCY_MS}ms"
                )
            if not latest:
                failures.append(f"{vendor} {market}: could not determine latest OHLCV date")
            elif latest > end_iso:
                failures.append(f"{vendor} {market}: latest OHLCV date {latest} is after request end {end_iso}")

            if vendor == "westock":
                minute_supported = _probe_westock_minute(symbol) if market == "CN" else False
                if market == "CN" and not minute_supported:
                    failures.append(f"{vendor} {market}: minute probe unexpectedly failed")
            elif vendor == "longbridge":
                minute_supported = _probe_longbridge_cli_minute(
                    {"US": "NVDA.US", "CN": "000001.SZ", "HK": "0700.HK"}[market]
                )
                if not minute_supported:
                    failures.append(f"{vendor} {market}: minute probe unexpectedly failed")
            elif vendor == "longbridge_mcp":
                minute_supported = _probe_longbridge_mcp_minute(
                    {"US": "NVDA.US", "CN": "000001.SZ", "HK": "0700.HK"}[market]
                )
                if not minute_supported:
                    failures.append(f"{vendor} {market}: minute probe unexpectedly failed")

        indicator_end = latest_completed_daily_bar_date("NVDA").strftime("%Y-%m-%d")
        indicator_pass = 0
        indicator_errors = {}
        for indicator in INDICATOR_BASKET:
            try:
                if _indicator_result_ok(indicator_fn("NVDA", indicator, indicator_end, 30)):
                    indicator_pass += 1
                else:
                    indicator_errors[indicator] = "empty/unavailable result"
            except Exception as exc:  # noqa: BLE001
                indicator_errors[indicator] = f"{type(exc).__name__}: {exc}"
        if indicator_pass < MIN_INDICATOR_PASS_COUNT:
            failures.append(
                f"{vendor}: indicator diversity {indicator_pass}/{len(INDICATOR_BASKET)} "
                f"below {MIN_INDICATOR_PASS_COUNT}; errors={indicator_errors}"
            )

    assert not failures, "\n".join(failures)
