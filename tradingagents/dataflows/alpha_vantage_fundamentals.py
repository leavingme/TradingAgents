from __future__ import annotations

import json
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Any

from .alpha_vantage_common import _make_api_request
from .financial_validation import (
    FinancialMetric,
    NormalizedFinancialData,
    UnverifiedFinancialFact,
    financial_period_type,
    is_derived_financial_metric,
)
from .errors import NoMarketDataError


def _filter_reports_by_date(raw_str: str, curr_date: str | None) -> str:
    """Filter annualReports/quarterlyReports to exclude entries after curr_date.

    Prevents look-ahead bias by removing fiscal periods that end after
    the simulation's current date.
    """
    if not curr_date:
        return raw_str
    try:
        raw = json.loads(raw_str)
    except Exception:
        return raw_str

    if not isinstance(raw, dict):
        return raw_str

    for key in ("annualReports", "quarterlyReports"):
        if key in raw and isinstance(raw[key], list):
            raw[key] = [
                r for r in raw[key]
                if isinstance(r, dict) and r.get("fiscalDateEnding", "") <= curr_date
            ]
    return json.dumps(raw)


def adapt_alpha_vantage_report(
    raw_str: str,
    kind: str,
    vendor: str,
    symbol: str,
    freq: str = "quarterly",
) -> NormalizedFinancialData:
    try:
        raw = json.loads(raw_str)
    except Exception as e:
        raise NoMarketDataError(symbol, detail=f"Alpha Vantage returned invalid JSON: {e}") from e

    if not isinstance(raw, dict):
        raise NoMarketDataError(symbol, detail="Alpha Vantage response is not a JSON object")

    report_key = "quarterlyReports" if freq == "quarterly" else "annualReports"
    reports = raw.get(report_key, [])
    if not isinstance(reports, list):
        reports = []

    metrics: list[FinancialMetric] = []
    excluded: list[str] = []
    unverified: list[UnverifiedFinancialFact] = []

    # For Alpha Vantage, duration_months is 3 for quarterly, 12 for annual
    duration_months = 3 if freq == "quarterly" else 12

    for report in reports:
        if not isinstance(report, dict):
            continue
        period_end = report.get("fiscalDateEnding")
        currency = report.get("reportedCurrency")

        if not period_end:
            continue
        try:
            end_date = datetime.strptime(period_end, "%Y-%m-%d").date()
        except ValueError:
            continue

        if freq == "quarterly":
            month = end_date.month
            quarter = (month - 1) // 3 + 1
            period = f"Q{quarter} {end_date.year}"
            period_type = "quarterly"
        else:
            period = f"FY {end_date.year}"
            period_type = "annual"

        context_type = "instant" if kind == "BS" else "duration"
        period_start = (
            (end_date - relativedelta(months=duration_months) + timedelta(days=1)).isoformat()
            if kind in {"IS", "CF"}
            else None
        )

        for key, val_str in report.items():
            if key in ("fiscalDateEnding", "reportedCurrency"):
                continue
            try:
                if val_str == "None" or val_str is None:
                    continue
                value = float(val_str)
            except ValueError:
                continue

            metric_name = key
            if is_derived_financial_metric(metric_name):
                unverified.append(UnverifiedFinancialFact(
                    metric=metric_name,
                    value=value,
                    currency=currency,
                    unit="percent" if "margin" in metric_name.lower() or "ratio" in metric_name.lower() else (currency or "unknown"),
                    period=period,
                    period_type=period_type,
                    period_end=period_end,
                    source=vendor,
                    source_field=key,
                    definition=None,
                    reason="vendor-reported derived metric has not been independently recomputed",
                ))
                excluded.append(metric_name)
                continue

            metrics.append(FinancialMetric(
                metric=metric_name,
                value=value,
                currency=currency,
                unit=currency or "unknown",
                period=period,
                period_type=period_type,
                source=vendor,
                period_start=period_start,
                period_end=period_end,
                context_type=context_type,
                source_field=key,
            ))

    return NormalizedFinancialData(
        metrics=tuple(metrics),
        source_text=raw_str,
        excluded_metrics=tuple(excluded),
        raw_payload=raw,
        entity_metadata={"symbol": symbol, "vendor": vendor},
        unverified_facts=tuple(unverified),
    )


def adapt_alpha_vantage_overview(
    raw_str: str,
    vendor: str,
    symbol: str,
) -> NormalizedFinancialData:
    try:
        raw = json.loads(raw_str)
    except Exception as e:
        raise NoMarketDataError(symbol, detail=f"Alpha Vantage returned invalid JSON: {e}") from e

    if not isinstance(raw, dict):
        raise NoMarketDataError(symbol, detail="Alpha Vantage response is not a JSON object")

    entity = {
        "symbol": symbol,
        "name": raw.get("Name"),
        "exchange": raw.get("Exchange"),
        "quote_currency": raw.get("Currency"),
        "vendor": vendor,
    }

    unverified: list[UnverifiedFinancialFact] = []
    excluded: list[str] = []

    for key, val_str in raw.items():
        if key in ("Symbol", "AssetType", "Name", "Description", "Exchange", "Currency", "Country", "Sector", "Industry", "Address"):
            continue
        try:
            if val_str == "None" or val_str is None:
                continue
            value = float(val_str)
        except ValueError:
            continue

        unit = "ratio" if "PE" in key or "Ratio" in key or "EVTo" in key or "Beta" in key else str(raw.get("Currency") or "unknown")
        unverified.append(UnverifiedFinancialFact(
            metric=key,
            value=value,
            currency=raw.get("Currency") if unit != "ratio" else None,
            unit=unit,
            period=None,
            period_type=None,
            period_end=None,
            source=vendor,
            source_field=key,
            definition=None,
            reason="source does not provide a reporting period or as-of timestamp",
        ))
        excluded.append(key)

    return NormalizedFinancialData(
        metrics=(),
        source_text=raw_str,
        excluded_metrics=tuple(excluded),
        raw_payload=raw,
        entity_metadata=entity,
        unverified_facts=tuple(unverified),
    )


def get_fundamentals(ticker: str, curr_date: str = None) -> NormalizedFinancialData:
    """Retrieve comprehensive fundamental data for a given ticker symbol using Alpha Vantage."""
    params = {"symbol": ticker}
    raw_str = _make_api_request("OVERVIEW", params)
    return adapt_alpha_vantage_overview(raw_str, "alpha_vantage", ticker)


def get_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None) -> NormalizedFinancialData:
    """Retrieve balance sheet data for a given ticker symbol using Alpha Vantage."""
    raw_str = _make_api_request("BALANCE_SHEET", {"symbol": ticker})
    filtered = _filter_reports_by_date(raw_str, curr_date)
    return adapt_alpha_vantage_report(filtered, "BS", "alpha_vantage", ticker, freq)


def get_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None) -> NormalizedFinancialData:
    """Retrieve cash flow statement data for a given ticker symbol using Alpha Vantage."""
    raw_str = _make_api_request("CASH_FLOW", {"symbol": ticker})
    filtered = _filter_reports_by_date(raw_str, curr_date)
    return adapt_alpha_vantage_report(filtered, "CF", "alpha_vantage", ticker, freq)


def get_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None) -> NormalizedFinancialData:
    """Retrieve income statement data for a given ticker symbol using Alpha Vantage."""
    raw_str = _make_api_request("INCOME_STATEMENT", {"symbol": ticker})
    filtered = _filter_reports_by_date(raw_str, curr_date)
    return adapt_alpha_vantage_report(filtered, "IS", "alpha_vantage", ticker, freq)
