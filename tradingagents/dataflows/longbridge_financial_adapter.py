"""Direct Longbridge financial-report JSON to domain-model adapter."""

from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dateutil.relativedelta import relativedelta
from typing import Any

from .financial_validation import (
    FinancialMetric,
    NormalizedFinancialData,
    UnverifiedFinancialFact,
    financial_period_type,
    is_derived_financial_metric,
)


def adapt_longbridge_financial_report(
    raw: Any,
    kind: str,
    vendor: str,
    symbol: str | None = None,
) -> NormalizedFinancialData:
    root = raw.get("list", {}).get(kind) if isinstance(raw, dict) else None
    indicators = root.get("indicators", []) if isinstance(root, dict) else []
    metrics: list[FinancialMetric] = []
    excluded: list[str] = []
    unverified: list[UnverifiedFinancialFact] = []
    report_type = str(raw.get("report") or "").lower() if isinstance(raw, dict) else ""
    duration_months = {"qf": 3, "q1": 3, "q2": 3, "q3": 3, "q4": 3,
                       "saf": 6, "3q": 9, "af": 12}.get(report_type)

    for indicator in indicators:
        if not isinstance(indicator, dict):
            continue
        accounts_raw = indicator.get("accounts")
        if isinstance(accounts_raw, str):
            try:
                accounts = ast.literal_eval(accounts_raw)
            except (ValueError, SyntaxError):
                continue
        elif isinstance(accounts_raw, list):
            accounts = accounts_raw
        else:
            accounts = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            source_name = str(account.get("name") or indicator.get("title") or "").strip()
            currency_match = re.search(r"\(([A-Z]{3})\)\s*$", source_name)
            currency = currency_match.group(1) if currency_match else None
            metric_name = re.sub(r"\([A-Z]{3}\)\s*$", "", source_name).strip()
            values = account.get("values")
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                period = str(item.get("period") or "").strip()
                try:
                    value = float(item.get("value"))
                except (TypeError, ValueError):
                    continue
                fp_end = item.get("fp_end")
                try:
                    market = (symbol or "").upper().rsplit(".", 1)[-1]
                    timezone_name = {
                        "HK": "Asia/Hong_Kong",
                        "US": "America/New_York",
                        "SH": "Asia/Shanghai",
                        "SZ": "Asia/Shanghai",
                        "SG": "Asia/Singapore",
                    }.get(market, "UTC")
                    end_date = datetime.fromtimestamp(
                        float(fp_end), tz=ZoneInfo(timezone_name)
                    ).date()
                    period_end = end_date.isoformat()
                except (TypeError, ValueError, OSError):
                    end_date = None
                    period_end = None
                if is_derived_financial_metric(metric_name):
                    unverified.append(UnverifiedFinancialFact(
                        metric=metric_name,
                        value=value,
                        currency=currency,
                        unit="percent" if account.get("percent") else (currency or "unknown"),
                        period=period or None,
                        period_type=financial_period_type(period),
                        period_end=period_end,
                        source=vendor,
                        source_field=str(account.get("field") or "") or None,
                        definition=str(account.get("tip") or "") or None,
                        reason="vendor-reported derived metric has not been independently recomputed",
                    ))
                    excluded.append(metric_name)
                    continue
                context_type = "instant" if kind == "BS" else "duration"
                period_start = (
                    (end_date - relativedelta(months=duration_months) + timedelta(days=1)).isoformat()
                    if end_date is not None and kind in {"IS", "CF"} and duration_months
                    else None
                )
                if (
                    currency is None
                    or period_end is None
                    or (context_type == "duration" and period_start is None)
                ):
                    missing = []
                    if currency is None:
                        missing.append("currency/unit")
                    if period_end is None:
                        missing.append("period_end")
                    if context_type == "duration" and period_start is None:
                        missing.append("period_start")
                    unverified.append(UnverifiedFinancialFact(
                        metric=metric_name,
                        value=value,
                        currency=currency,
                        unit=currency or "unknown",
                        period=period or None,
                        period_type=financial_period_type(period),
                        period_end=period_end,
                        source=vendor,
                        source_field=str(account.get("field") or "") or None,
                        definition=str(account.get("tip") or "") or None,
                        reason=f"missing required metadata: {', '.join(missing)}",
                    ))
                    excluded.append(metric_name)
                    continue
                metrics.append(FinancialMetric(
                    metric=metric_name,
                    value=value,
                    currency=currency,
                    unit=currency or "unknown",
                    period=period,
                    period_type=financial_period_type(period) or "unknown",
                    source=vendor,
                    period_start=period_start,
                    period_end=period_end,
                    context_type=context_type,
                    source_field=str(account.get("field") or "") or None,
                ))

    if kind == "BS":
        from .financial_validation import extract_metric
        temp_data = NormalizedFinancialData(metrics=tuple(metrics), source_text="")
        periods = {m.period for m in metrics if m.period}
        for p in periods:
            assets = extract_metric(temp_data, "total_assets", p)
            liabilities = extract_metric(temp_data, "total_liabilities", p)
            equity = extract_metric(temp_data, "total_equity", p)
            if assets is not None and liabilities is not None and equity is None:
                ref_m = next((m for m in metrics if m.period == p and ("assets" in m.metric.lower() or "liabilities" in m.metric.lower() or "资产" in m.metric or "负债" in m.metric)), None)
                if not ref_m:
                    ref_m = next(m for m in metrics if m.period == p)
                metrics.append(FinancialMetric(
                    metric="Total Equity",
                    value=assets - liabilities,
                    currency=ref_m.currency,
                    unit=ref_m.unit,
                    period=ref_m.period,
                    period_type=ref_m.period_type,
                    source=ref_m.source,
                    period_start=ref_m.period_start,
                    period_end=ref_m.period_end,
                    context_type=ref_m.context_type,
                    source_field="derived: assets - liabilities",
                ))

    return NormalizedFinancialData(
        metrics=tuple(metrics),
        source_text="",
        excluded_metrics=tuple(excluded),
        raw_payload=raw,
        unverified_facts=tuple(unverified),
    )


def adapt_longbridge_company_reference(
    static_raw: Any,
    valuation_raw: Any,
    symbol: str,
    vendor: str,
) -> NormalizedFinancialData:
    """Keep entity metadata; quarantine unperiodized valuation metrics."""
    static = static_raw[0] if isinstance(static_raw, list) and static_raw else static_raw
    valuation = valuation_raw[0] if isinstance(valuation_raw, list) and valuation_raw else valuation_raw
    static = static if isinstance(static, dict) else {}
    valuation = valuation if isinstance(valuation, dict) else {}
    entity = {
        "symbol": symbol,
        "name": static.get("name"),
        "exchange": static.get("exchange"),
        "quote_currency": static.get("currency"),
        "vendor": vendor,
    }
    excluded = tuple(
        key for key in (
            "eps", "eps_ttm", "bps", "dividend", "total_shares",
            "pe", "pe_ttm_ratio", "pb", "pb_ratio", "ps", "ps_ratio",
            "mktcap", "total_market_value",
        )
        if key in static or key in valuation
    )
    unverified: list[UnverifiedFinancialFact] = []
    for field in excluded:
        raw_value = static.get(field, valuation.get(field))
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if field in {"pe", "pe_ttm_ratio", "pb", "pb_ratio", "ps", "ps_ratio"}:
            unit = "ratio"
        elif field in {"total_shares"}:
            unit = "shares"
        else:
            unit = str(static.get("currency") or "unknown")
        unverified.append(UnverifiedFinancialFact(
            metric=field,
            value=value,
            currency=static.get("currency") if unit not in {"ratio", "shares"} else None,
            unit=unit,
            period=None,
            period_type=None,
            period_end=None,
            source=vendor,
            source_field=field,
            definition="TTM" if "ttm" in field else None,
            reason="source does not provide a reporting period or as-of timestamp",
        ))
    return NormalizedFinancialData(
        metrics=(),
        source_text="",
        excluded_metrics=excluded,
        raw_payload={"static": static_raw, "valuation": valuation_raw},
        entity_metadata=entity,
        unverified_facts=tuple(unverified),
    )
