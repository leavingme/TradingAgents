"""Live technical-indicator provider capability checks.

Run explicitly when you want to evaluate real provider capability:

    RUN_TECHNICAL_INDICATOR_PROVIDER_REQUIREMENTS=1 \
      venv/bin/python3.12 -m pytest tests/test_technical_indicator_provider_requirements.py -q -s
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date, datetime
import os
import re
import time

import pytest

import tradingagents.dataflows.config as config_module
from tradingagents.dataflows.config import get_config, set_config
from tradingagents.dataflows.interface import VENDOR_METHODS
from tradingagents.default_config import DEFAULT_CONFIG


MARKET_PROBES = {
    "US stocks": "NVDA",
    "China A-shares": "000001.SZ",
    "Hong Kong stocks": "0700.HK",
}

INDICATOR_BASKET = {
    "trend": "close_50_sma",
    "momentum": "rsi",
    "momentum_cross": "macd",
    "volatility": "boll",
    "volume_price": "vwma",
}

MAX_INDICATOR_LATENCY_MS = 45_000
MAX_LATEST_NUMERIC_STALE_DAYS = 10
MIN_MARKET_PASS_RATE = 0.80

ERROR_MARKERS = (
    "api key",
    "exception",
    "not configured",
    "premium endpoint",
    "rate limit",
    "temporarily unavailable",
    "traceback",
    "unsupported indicator",
)


@dataclass
class IndicatorProbe:
    vendor: str
    market: str
    symbol: str
    category: str
    indicator: str
    passed: bool
    latency_ms: int
    date_evidence: str | None
    reason: str


def _enabled_indicator_vendors() -> list[str]:
    override = os.environ.get("TECHNICAL_INDICATOR_PROVIDER_REQUIREMENTS_VENDORS")
    chain = override or DEFAULT_CONFIG["data_vendors"]["technical_indicators"]
    return [vendor.strip() for vendor in chain.split(",") if vendor.strip()]


def _enabled_markets() -> dict[str, str]:
    override = os.environ.get("TECHNICAL_INDICATOR_REQUIREMENTS_MARKETS")
    if not override:
        return MARKET_PROBES
    wanted = {name.strip() for name in override.split(",") if name.strip()}
    return {name: symbol for name, symbol in MARKET_PROBES.items() if name in wanted}


def _enabled_indicators() -> dict[str, str]:
    override = os.environ.get("TECHNICAL_INDICATOR_REQUIREMENTS_INDICATORS")
    if not override:
        return INDICATOR_BASKET
    wanted = {name.strip() for name in override.split(",") if name.strip()}
    selected = {
        category: indicator
        for category, indicator in INDICATOR_BASKET.items()
        if indicator in wanted or category in wanted
    }
    selected_values = set(selected.values())
    for indicator in sorted(wanted - selected_values - set(selected)):
        selected[indicator] = indicator
    return selected


def _looks_like_error(text: str) -> bool:
    lowered = text[:1200].lower()
    return any(marker in lowered for marker in ERROR_MARKERS)


def _numeric_tokens(text: str) -> list[float]:
    values: list[float] = []
    for token in re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?![A-Za-z])", text):
        try:
            values.append(float(token))
        except ValueError:
            continue
    return values


def _latest_numeric_date(text: str) -> str | None:
    latest: datetime | None = None
    for line in text.splitlines():
        if not re.match(r"^\d{4}-\d{2}-\d{2}\s*:", line.strip()):
            continue
        if "N/A" in line:
            continue
        if not _numeric_tokens(line.partition(":")[2]):
            continue
        try:
            parsed = datetime.strptime(line[:10], "%Y-%m-%d")
        except ValueError:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest.strftime("%Y-%m-%d") if latest else None


def _result_ok(text: str, curr_date: str) -> tuple[bool, str, str | None]:
    stripped = text.strip()
    if not stripped:
        return False, "empty result", None
    if _looks_like_error(stripped):
        return False, "error marker in result", None
    if not _numeric_tokens(stripped):
        return False, "no numeric indicator values", None

    latest = _latest_numeric_date(stripped)
    if latest:
        stale_days = (datetime.strptime(curr_date, "%Y-%m-%d") - datetime.strptime(latest, "%Y-%m-%d")).days
        if stale_days > MAX_LATEST_NUMERIC_STALE_DAYS:
            return False, f"latest numeric value is stale ({latest})", latest
        return True, "ok", latest

    report_date = re.search(r"Report Date:\s*(\d{4}-\d{2}-\d{2})", stripped)
    if report_date:
        return True, "ok", f"report {report_date.group(1)}"

    if curr_date not in stripped:
        return False, "no dated value or report date", None

    return True, "ok", curr_date


def _format_summary(rows: list[IndicatorProbe]) -> str:
    lines = [
        "",
        "Technical indicator provider capability summary:",
        "| Vendor | Market | Indicator | Category | Result | Latency | Date evidence |",
        "|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        result = "PASS" if row.passed else f"FAIL: {row.reason}"
        lines.append(
            f"| {row.vendor} | {row.market} | {row.indicator} | {row.category} | "
            f"{result} | {row.latency_ms}ms | {row.date_evidence or '-'} |"
        )
    return "\n".join(lines)


@pytest.mark.integration
def test_configured_technical_indicator_providers_meet_capability_requirements(tmp_path):
    if os.environ.get("RUN_TECHNICAL_INDICATOR_PROVIDER_REQUIREMENTS") != "1":
        pytest.skip("set RUN_TECHNICAL_INDICATOR_PROVIDER_REQUIREMENTS=1 to run live provider checks")

    saved_config = get_config()
    test_config = copy.deepcopy(saved_config)
    test_config["data_cache_dir"] = str(tmp_path / "indicator-cache")
    config_module._config = None
    set_config(test_config)

    curr_date = date.today().isoformat()
    markets = _enabled_markets()
    indicators = _enabled_indicators()
    rows: list[IndicatorProbe] = []
    failures: list[str] = []

    assert markets, "no markets selected for technical indicator capability checks"
    assert indicators, "no indicators selected for technical indicator capability checks"

    try:
        for vendor in _enabled_indicator_vendors():
            indicator_fn = VENDOR_METHODS["get_indicators"].get(vendor)
            if not callable(indicator_fn):
                failures.append(f"{vendor}: missing get_indicators implementation")
                continue

            vendor_market_results: dict[str, list[bool]] = {market: [] for market in markets}
            for market, symbol in markets.items():
                for category, indicator in indicators.items():
                    started = time.perf_counter()
                    date_evidence = None
                    try:
                        result = indicator_fn(symbol, indicator, curr_date, 60)
                        latency_ms = round((time.perf_counter() - started) * 1000)
                        ok, reason, date_evidence = _result_ok(str(result), curr_date)
                        if latency_ms > MAX_INDICATOR_LATENCY_MS:
                            ok = False
                            reason = f"latency {latency_ms}ms above {MAX_INDICATOR_LATENCY_MS}ms"
                    except Exception as exc:  # noqa: BLE001 - live diagnostics should surface provider errors
                        latency_ms = round((time.perf_counter() - started) * 1000)
                        ok = False
                        reason = f"{type(exc).__name__}: {exc}"

                    vendor_market_results[market].append(ok)
                    rows.append(
                        IndicatorProbe(
                            vendor=vendor,
                            market=market,
                            symbol=symbol,
                            category=category,
                            indicator=indicator,
                            passed=ok,
                            latency_ms=latency_ms,
                            date_evidence=date_evidence,
                            reason=reason,
                        )
                    )

            for market, results in vendor_market_results.items():
                pass_rate = sum(results) / max(len(results), 1)
                if pass_rate < MIN_MARKET_PASS_RATE:
                    failures.append(
                        f"{vendor} {market}: indicator pass rate {sum(results)}/{len(results)} "
                        f"below {MIN_MARKET_PASS_RATE:.0%}"
                    )
    finally:
        config_module._config = copy.deepcopy(saved_config)

    summary = _format_summary(rows)
    print(summary)
    assert not failures, "\n".join(failures) + summary
