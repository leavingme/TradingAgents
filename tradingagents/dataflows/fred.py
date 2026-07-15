"""FRED (Federal Reserve Economic Data) macro vendor.

Fetches macroeconomic time series — policy rates, Treasury yields, inflation,
labor, growth — from the St. Louis Fed's free API. Used by the news analyst to
ground macro commentary in actual numbers rather than headlines alone.

A free API key (https://fred.stlouisfed.org/docs/api/api_key.html) is read from
``FRED_API_KEY``; if it is unset the vendor raises ``FredNotConfiguredError`` so
the routing layer treats it as "unavailable" rather than a hard crash.
"""
import logging
import math
import os
from datetime import datetime, timedelta, timezone

import requests

from .errors import NoMarketDataError, VendorNotConfiguredError
from .evidence_models import (
    MacroObservation,
    MacroSeries,
    macro_source_id,
)

logger = logging.getLogger(__name__)

FRED_API_BASE = "https://api.stlouisfed.org/fred"

# Network timeout (seconds) so a stalled request can't hang the agents,
# mirroring the Alpha Vantage client.
REQUEST_TIMEOUT = 30

# Default trailing window when the caller does not specify one. A year captures
# the trend and the year-over-year base for most monthly/quarterly series.
DEFAULT_LOOKBACK_DAYS = 365

# Rows cap for the rendered table: recent values matter most for a decision, and
# daily series (yields, VIX) over a long window would otherwise flood context.
MAX_ROWS = 40

# FRED rejects JSON observation requests spanning more than 2,000 vintage dates.
# A vintage date has day precision, so keeping each inclusive real-time window
# below that limit is deterministic even for daily series. The normal 365/1095
# day lookbacks fit in one request; this only adds calls for explicit long ranges.
MAX_VINTAGE_WINDOW_DAYS = 1800

# Curated human-friendly aliases -> FRED series IDs. Anything not listed is used
# verbatim as a raw FRED series ID, so power users are never limited to this set.
MACRO_SERIES = {
    # Policy rate & Treasury yields
    "fed_funds_rate": "FEDFUNDS",
    "federal_funds_rate": "FEDFUNDS",
    "fed_funds": "FEDFUNDS",
    "2y_treasury": "DGS2",
    "10y_treasury": "DGS10",
    "30y_treasury": "DGS30",
    "10y_2y_spread": "T10Y2Y",
    "yield_curve": "T10Y2Y",
    # Inflation
    "cpi": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "pce": "PCEPI",
    "core_pce": "PCEPILFE",
    "inflation_expectations": "T10YIE",
    # Growth & output
    "real_gdp": "GDPC1",
    "gdp": "GDP",
    "industrial_production": "INDPRO",
    # Labor
    "unemployment_rate": "UNRATE",
    "unemployment": "UNRATE",
    "nonfarm_payrolls": "PAYEMS",
    "payrolls": "PAYEMS",
    "initial_claims": "ICSA",
    # Money & markets
    "m2": "M2SL",
    "money_supply": "M2SL",
    "vix": "VIXCLS",
    "dollar_index": "DTWEXBGS",
    # Sentiment & housing
    "consumer_sentiment": "UMCSENT",
    "housing_starts": "HOUST",
    "retail_sales": "RSAFS",
    # Global / International Indicators (added for CN/HK support)
    "cn_cpi": "CHNCPIALLMINMEI",
    "cn_gdp": "NGDPXDCCNA",
    "cn_interest_rate": "INTDSRCNM193N",
    "hk_cpi": "FPCPITOTLZGHKG",
    "hk_gdp": "MKTGDPHKA646NWDB",
}


class FredNotConfiguredError(VendorNotConfiguredError):
    """Raised when FRED is selected but no API key is configured.

    A VendorNotConfiguredError (and thus still a ValueError), so the routing
    layer's "vendor unavailable" handling and existing ValueError callers both
    keep working.
    """


def get_api_key() -> str:
    """Retrieve the FRED API key from the environment."""
    api_key = os.getenv("FRED_API_KEY")
    if not api_key:
        raise FredNotConfiguredError(
            "FRED_API_KEY environment variable is not set. Get a free key at "
            "https://fred.stlouisfed.org/docs/api/api_key.html."
        )
    return api_key


def _resolve_series_id(indicator: str) -> str:
    """Map a friendly alias to a FRED series ID, or pass a raw ID through.

    Raises ``ValueError`` when the input is neither a known alias nor a plausible
    series ID — typically a descriptive phrase the LLM passed instead (e.g.
    "bank of japan rate"). FRED IDs are short and alphanumeric, so this rejects
    it up front with guidance rather than letting it 400 the API.
    """
    key = indicator.strip().lower().replace(" ", "_").replace("-", "_")
    if key in MACRO_SERIES:
        return MACRO_SERIES[key]
    candidate = indicator.strip().upper()
    # FRED series IDs never contain whitespace and are short; reject anything
    # else (a descriptive phrase the LLM passed) rather than 400ing the API.
    if not candidate or len(candidate) > 30 or any(c.isspace() for c in candidate):
        raise ValueError(
            f"'{indicator}' is not a known macro alias or a valid FRED series ID. "
            f"Use an alias (e.g. 'cpi', 'unemployment', '10y_treasury') or a raw "
            f"FRED series ID (e.g. 'CPIAUCSL')."
        )
    return candidate


def _request(path: str, params: dict) -> dict:
    """GET a FRED endpoint, surfacing FRED's JSON error body on a bad request."""
    api_params = {**params, "api_key": get_api_key(), "file_type": "json"}
    response = requests.get(
        f"{FRED_API_BASE}/{path}", params=api_params, timeout=REQUEST_TIMEOUT
    )
    # FRED returns 400 with a JSON {"error_message": ...} for unknown series IDs
    # or malformed params; turn that into a clear, actionable error.
    if response.status_code == 400:
        try:
            message = response.json().get("error_message", response.text)
        except ValueError:
            message = response.text
        raise ValueError(f"FRED request failed: {message}")
    response.raise_for_status()
    return response.json()


def _initial_release_rows(
    observation_params: dict,
    realtime_start: str,
    realtime_end: str,
) -> list[dict]:
    """Return each observation's earliest release without exceeding FRED limits.

    ``output_type=4`` returns every new or revised value in the requested
    real-time range. Restrict that range to the observation window (an
    observation cannot be released before its own period starts), split long
    ranges below FRED's 2,000-vintage JSON cap, and retain the earliest
    ``realtime_start`` when later revisions repeat an observation date.
    """
    window_start = datetime.strptime(realtime_start, "%Y-%m-%d").date()
    window_end = datetime.strptime(realtime_end, "%Y-%m-%d").date()
    if window_start > window_end:
        return []

    earliest_by_date: dict[str, dict] = {}
    cursor = window_start
    while cursor <= window_end:
        chunk_end = min(
            cursor + timedelta(days=MAX_VINTAGE_WINDOW_DAYS - 1),
            window_end,
        )
        rows = _request(
            "series/observations",
            {
                **observation_params,
                "output_type": 4,
                "realtime_start": cursor.isoformat(),
                "realtime_end": chunk_end.isoformat(),
            },
        ).get("observations", [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            observed_at = str(row.get("date") or "")
            published_at = str(row.get("realtime_start") or "")
            if not observed_at or not published_at:
                continue
            previous = earliest_by_date.get(observed_at)
            if previous is None or published_at < str(previous["realtime_start"]):
                earliest_by_date[observed_at] = row
        cursor = chunk_end + timedelta(days=1)

    return [earliest_by_date[key] for key in sorted(earliest_by_date)]


def get_macro_data(
    indicator: str,
    curr_date: str,
    look_back_days: int | None = None,
) -> MacroSeries:
    """Fetch a FRED macroeconomic series as a formatted markdown report.

    Args:
        indicator: A friendly alias (e.g. "cpi", "unemployment", "10y_treasury")
            or a raw FRED series ID (e.g. "CPIAUCSL", "DGS10").
        curr_date: End of the window (yyyy-mm-dd); no later observations are
            returned, so a past date never leaks future data.
        look_back_days: Trailing window length; ``None`` uses DEFAULT_LOOKBACK_DAYS.

    Returns:
        A markdown report with the series title, units, frequency, the latest
        value, the change over the window, and a recent observation table.
    """
    try:
        series_id = _resolve_series_id(indicator)
    except ValueError as e:
        raise NoMarketDataError(indicator, detail=str(e)) from e

    # Force a minimum lookback period (e.g. 1095 days) for lagging non-US series
    # to prevent "no observations in window" errors due to reporting lag.
    is_lagging = (
        indicator in ("cn_cpi", "cn_gdp", "cn_interest_rate", "hk_cpi", "hk_gdp")
        or series_id in ("CHNCPIALLMINMEI", "NGDPXDCCNA", "INTDSRCNM193N", "FPCPITOTLZGHKG", "MKTGDPHKA646NWDB")
    )

    if look_back_days is None:
        look_back_days = 1095 if is_lagging else DEFAULT_LOOKBACK_DAYS
    elif is_lagging and look_back_days < 730:
        look_back_days = 1095

    end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    from tradingagents.runtime.audit_context import (
        current_analysis_mode,
        current_information_cutoff,
        current_run_id,
    )

    if current_run_id() and current_analysis_mode() == "point_in_time":
        cutoff_date = datetime.fromisoformat(
            str(current_information_cutoff()).replace("Z", "+00:00")
        ).date()
        # FRED vintages have date precision, not release-time precision. Use
        # the prior date so a value released later on the cutoff date cannot
        # leak into an intraday historical decision.
        vintage_date = (cutoff_date - timedelta(days=1)).isoformat()
        revision_policy = "fred_vintage_before_cutoff_date"
    elif current_run_id():
        vintage_date = datetime.now(timezone.utc).date().isoformat()
        revision_policy = "fred_latest_vintage_at_call_time"
    else:
        vintage_date = curr_date
        revision_policy = "fred_explicit_vintage"

    meta = _request("series", {
        "series_id": series_id,
        "realtime_start": vintage_date,
        "realtime_end": vintage_date,
    }).get("seriess") or []
    if not meta:
        raise NoMarketDataError(
            indicator,
            series_id,
            "FRED series was not found",
        )
    info = meta[0]
    title = info.get("title", series_id)
    units = info.get("units_short") or info.get("units", "")
    frequency = info.get("frequency", "")
    seasonal = info.get("seasonal_adjustment_short", "")

    observation_params = {
        "series_id": series_id,
        "observation_start": start_date,
        "observation_end": curr_date,
        "sort_order": "asc",
    }
    observations = _request(
        "series/observations",
        {**observation_params, "vintage_dates": vintage_date},
    ).get("observations", [])

    initial_release_rows = _initial_release_rows(
        observation_params,
        start_date,
        vintage_date,
    )
    initial_by_date = {
        str(row.get("date")): row
        for row in initial_release_rows
        if isinstance(row, dict) and row.get("date") and row.get("realtime_start")
    }

    # FRED encodes a missing observation as ".".
    points = [
        (o["date"], o["value"], initial_by_date.get(str(o["date"])))
        for o in observations
        if o.get("value") not in (".", None, "")
        and initial_by_date.get(str(o.get("date"))) is not None
    ]

    if not points:
        raise NoMarketDataError(
            indicator,
            series_id,
            "no observations in the requested window",
        )

    structured = []
    for observed_at, raw_value, initial_row in points:
        try:
            value = float(raw_value)
            initial_value = float(initial_row["value"])
            published_at = str(initial_row["realtime_start"])
        except (TypeError, ValueError):
            continue
        structured.append(MacroObservation(
            source_id=macro_source_id(
                series_id, observed_at, vendor="fred", vintage_date=vintage_date
            ),
            series_id=series_id,
            title=title,
            units=units,
            frequency=frequency + (f" ({seasonal})" if seasonal else ""),
            observed_at=observed_at,
            value=value,
            vendor="fred",
            published_at=published_at,
            vintage_date=vintage_date,
            revision_status=(
                "initial" if math.isclose(value, initial_value) else "revised"
            ),
        ))
    if not structured:
        raise NoMarketDataError(indicator, series_id, "no numeric observations")
    return MacroSeries(
        series_id=series_id, title=title, units=units,
        frequency=frequency + (f" ({seasonal})" if seasonal else ""),
        requested_start=start_date, requested_end=curr_date,
        observations=tuple(structured),
        vendor="fred", vintage_date=vintage_date,
        revision_policy=revision_policy,
        requested_indicator=indicator,
    )
