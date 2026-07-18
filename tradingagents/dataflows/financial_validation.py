"""Normalization and deterministic validation for financial vendor data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .data_validation import ValidationResult, ValidationStatus


FINANCIAL_EVIDENCE_SCHEMA = "tradingagents/reconciled-financial-evidence/v1"


@dataclass(frozen=True)
class FinancialMetric:
    metric: str
    value: float
    currency: str | None
    unit: str
    period: str
    period_type: str
    source: str
    period_start: str | None = None
    period_end: str | None = None
    context_type: str | None = None
    source_field: str | None = None


@dataclass(frozen=True)
class NormalizedFinancialData:
    metrics: tuple[FinancialMetric, ...]
    source_text: str
    excluded_metrics: tuple[str, ...] = ()
    raw_payload: object | None = None
    entity_metadata: dict[str, object] | None = None
    unverified_facts: tuple["UnverifiedFinancialFact", ...] = ()


@dataclass(frozen=True)
class DerivedFinancialMetric:
    metric: str
    value: float
    unit: str
    period: str
    period_type: str
    formula: str
    inputs: dict[str, float]
    status: str = "verified"


@dataclass(frozen=True)
class UnverifiedFinancialFact:
    metric: str
    value: float
    currency: str | None
    unit: str
    period: str | None
    period_type: str | None
    period_end: str | None
    source: str
    source_field: str | None
    definition: str | None
    reason: str
    status: str = "unverified"


_RATIO_WORDS = ("roe", "roa", "margin", "rate", "ratio", "yield", "pe", "pb", "ps")
_AMBIGUOUS_DERIVED_MARKERS = ("/", "若按", "可能意味着")


def _is_derived_ratio(metric: str) -> bool:
    lowered = metric.lower()
    return "率" in metric or "比率" in metric or any(
        re.search(rf"\b{word}\b", lowered) for word in _RATIO_WORDS
    )


def is_derived_financial_metric(metric: str) -> bool:
    return _is_derived_ratio(metric) or any(
        marker in metric for marker in _AMBIGUOUS_DERIVED_MARKERS
    )


def financial_period_type(period: str) -> str | None:
    normalized = period.strip().upper()
    if re.search(r"\bQ[1-4]\b", normalized):
        return "quarterly"
    if re.search(r"\b(FY|ANNUAL|YEAR)\b", normalized) or re.fullmatch(r"\d{4}", normalized):
        return "annual"
    return None


def normalize_financial_result(payload: object, source: str) -> NormalizedFinancialData:
    """Parse flattened vendor statements into one vendor-neutral metric schema."""
    text = str(payload)
    metrics: list[FinancialMetric] = []
    excluded_metrics: list[str] = []
    pattern = re.compile(
        r"^\s{2,}(?P<metric>[^:\n]+?)(?:\((?P<currency>[A-Z]{3})\))?:\s*"
        r"(?P<value>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
        r"\s*\[(?P<period>[^\]]+)\](?:\s+yoy=[-+]?\d+(?:\.\d+)?)?\s*$"
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        metric = match.group("metric").strip()
        currency = match.group("currency")
        is_ratio = _is_derived_ratio(metric)
        if is_derived_financial_metric(metric):
            excluded_metrics.append(metric)
            continue
        unit = "percent" if is_ratio else (currency or "unknown")
        period = match.group("period").strip()
        metrics.append(FinancialMetric(
            metric=metric,
            value=float(match.group("value")),
            currency=currency,
            unit=unit,
            period=period,
            period_type=financial_period_type(period) or "unknown",
            source=source,
        ))
    return NormalizedFinancialData(
        metrics=tuple(metrics),
        source_text=text,
        excluded_metrics=tuple(excluded_metrics),
    )


def validate_financial_result(
    data: NormalizedFinancialData,
    analysis_date: str | None = None,
) -> ValidationResult:
    if not isinstance(data, NormalizedFinancialData):
        raise TypeError("validate_financial_result only accepts NormalizedFinancialData")

    if not data.metrics:
        if data.entity_metadata and data.entity_metadata.get("symbol"):
            return ValidationResult(ValidationStatus.VERIFIED)
        return ValidationResult(ValidationStatus.INVALID, "financial payload has no structured metrics")
    for metric in data.metrics:
        if not metric.period or metric.period_type == "unknown":
            return ValidationResult(
                ValidationStatus.INVALID,
                f"financial metric {metric.metric!r} has no valid period metadata",
            )
        if not metric.currency:
            return ValidationResult(
                ValidationStatus.INVALID,
                f"financial metric {metric.metric!r} has no currency metadata",
            )
        if metric.unit == "unknown":
            return ValidationResult(
                ValidationStatus.INVALID,
                f"financial metric {metric.metric!r} has no unit metadata",
            )
        if not metric.period_end or metric.context_type not in {"instant", "duration"}:
            return ValidationResult(
                ValidationStatus.INVALID,
                f"financial metric {metric.metric!r} has no complete XBRL-style context",
            )
        if metric.context_type == "duration" and not metric.period_start:
            return ValidationResult(
                ValidationStatus.INVALID,
                f"financial metric {metric.metric!r} has no period start",
            )
        if analysis_date and date.fromisoformat(metric.period_end) > date.fromisoformat(analysis_date):
            return ValidationResult(
                ValidationStatus.INVALID,
                f"financial metric {metric.metric!r} is after the analysis date",
            )
    return ValidationResult(ValidationStatus.VERIFIED)


_METRIC_ALIASES = {
    "revenue": ("revenue", "营业收入", "營業收入"),
    "gross_profit": ("gross profit", "毛利润", "毛利潤"),
    "operating_profit": ("operating profit", "营业利润", "營業利潤"),
    "net_income": ("net income", "净利润", "淨利潤"),
    "operating_cash_flow": ("operating cash flow", "经营现金流", "經營現金流"),
}


def _canonical_metric(name: str) -> str | None:
    lowered = name.lower()
    for canonical, aliases in _METRIC_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return canonical
    return None


def derive_financial_metrics(data: NormalizedFinancialData) -> tuple[DerivedFinancialMetric, ...]:
    """Compute only auditable same-period, same-currency derived metrics."""
    grouped: dict[tuple[str, str, str], dict[str, float]] = {}
    for metric in data.metrics:
        canonical = _canonical_metric(metric.metric)
        if canonical is None or metric.currency is None:
            continue
        key = (metric.period, metric.period_type, metric.currency)
        grouped.setdefault(key, {})[canonical] = metric.value

    derived: list[DerivedFinancialMetric] = []
    formulas = (
        ("gross_margin", "gross_profit", "gross_profit / revenue * 100"),
        ("operating_margin", "operating_profit", "operating_profit / revenue * 100"),
        ("net_margin", "net_income", "net_income / revenue * 100"),
    )
    for (period, period_type, _currency), values in grouped.items():
        revenue = values.get("revenue")
        if revenue is None or revenue == 0:
            continue
        for name, numerator_name, formula in formulas:
            numerator = values.get(numerator_name)
            if numerator is None:
                continue
            derived.append(DerivedFinancialMetric(
                metric=name,
                value=numerator / revenue * 100,
                unit="percent",
                period=period,
                period_type=period_type,
                formula=formula,
                inputs={numerator_name: numerator, "revenue": revenue},
            ))
    return tuple(derived)


def render_financial_data(
    data: NormalizedFinancialData,
    derived_override: list[DerivedFinancialMetric] | tuple[DerivedFinancialMetric, ...] | None = None,
) -> str:
    derived = derived_override if derived_override is not None else derive_financial_metrics(data)
    return json.dumps(
        {
            "status": "verified",
            "entity": data.entity_metadata,
            "metrics": [asdict(metric) for metric in data.metrics],
            "derived_metrics": [asdict(metric) for metric in derived],
            "unverified_fact_count": len(data.unverified_facts),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _compact_financial_statement(data: NormalizedFinancialData) -> dict[str, Any]:
    """Group a validated statement without dropping any verified metric value."""
    grouped: dict[
        tuple[str, str | None, str, str, str | None, str | None],
        list[list[object]],
    ] = {}
    for metric in data.metrics:
        identity = (
            metric.metric,
            metric.currency,
            metric.unit,
            metric.source,
            metric.context_type,
            metric.source_field,
        )
        grouped.setdefault(identity, []).append([
            metric.period,
            metric.period_type,
            metric.period_start,
            metric.period_end,
            metric.value,
        ])
    series = []
    for identity, observations in sorted(
        grouped.items(),
        key=lambda item: tuple(str(value or "") for value in item[0]),
    ):
        observations.sort(key=lambda row: (str(row[3] or ""), str(row[0])))
        series.append([*identity, observations])
    return {
        "series_columns": [
            "metric",
            "currency",
            "unit",
            "source",
            "context_type",
            "source_field",
            "observations",
        ],
        "observation_columns": [
            "period",
            "period_type",
            "period_start",
            "period_end",
            "value",
        ],
        "verified_metric_count": len(data.metrics),
        "excluded_metric_count": len(data.excluded_metrics),
        "unverified_fact_count": len(data.unverified_facts),
        "series": series,
    }


def render_financial_evidence(
    *,
    income_statement: NormalizedFinancialData,
    balance_sheet: NormalizedFinancialData,
    cashflow: NormalizedFinancialData,
    fundamentals: NormalizedFinancialData | None,
    derived_metrics: list[DerivedFinancialMetric]
    | tuple[DerivedFinancialMetric, ...],
) -> str:
    """Render one lossless compact LLM view after validation/reconciliation."""
    return json.dumps(
        {
            "schema": FINANCIAL_EVIDENCE_SCHEMA,
            "status": "verified_and_reconciled",
            "entity": fundamentals.entity_metadata if fundamentals else None,
            "entity_unverified_fact_count": (
                len(fundamentals.unverified_facts) if fundamentals else 0
            ),
            "statements": {
                "income_statement": _compact_financial_statement(income_statement),
                "balance_sheet": _compact_financial_statement(balance_sheet),
                "cashflow": _compact_financial_statement(cashflow),
            },
            "derived_metrics": [asdict(metric) for metric in derived_metrics],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


# --- Section 3 & 4: Cross-statement reconciliation and deterministic derived calculations ---

CANONICAL_METRICS = {
    "revenue": ("revenue", "营业收入", "營業收入", "营业总收入", "營業總收入", "total revenue", "total_revenue"),
    "gross_profit": ("gross profit", "毛利润", "毛利潤", "gross profit", "gross_profit"),
    "operating_profit": ("operating profit", "营业利润", "營業利潤", "operating income", "operating_profit"),
    "net_income": ("net income", "净利润", "淨利潤", "净收益", "淨收益", "net profit", "net_profit", "net_income"),
    "operating_cash_flow": ("operating cash flow", "经营现金流", "經營現金流", "经营活动产生的现金流量净额", "經營活動產生的現金流量淨額", "经营活动现金流量", "operating_cash_flow"),
    "total_assets": ("total assets", "资产总额", "資產總額", "资产总计", "資產總計", "总资产", "total_assets"),
    "total_liabilities": ("total liabilities", "负债总额", "負膽總額", "负债合计", "負債合計", "总负债", "total_liabilities"),
    "total_equity": ("total shareholder's equity", "total equity", "股东权益总额", "股東權益總額", "所有者权益", "所有者權益", "所有者权益合计", "所有者權益合計", "股东权益合计", "total_equity"),
    "cash_and_equivalents": ("cash and cash equivalents", "cash and equivalents", "现金及现金等价物", "現金及現金等價物", "货币资金", "貨幣資金", "期末现金及现金等价物余额", "期末現金及現金等價物餘額", "ending cash balance", "cash_and_equivalents"),
    "net_change_in_cash": ("net change in cash", "net increase in cash", "现金及现金等价物净增加额", "現金及現金等價物淨增加額", "现金净流出额", "net_change_in_cash"),
    "short_term_debt": ("short-term debt", "short term debt", "short-term borrowings", "短期借款", "短期借貸", "short_term_debt", "short term borrowings"),
    "long_term_debt": ("long-term debt", "long term debt", "long-term borrowings", "长期借款", "長期借貸", "long_term_debt", "long term borrowings"),
    "depreciation_amortization": ("depreciation and amortization", "depreciation & amortization", "depreciation", "amortization", "折旧与摊销", "折舊與攤銷", "折旧和摊销", "depreciation_amortization"),
    "shares_outstanding": ("shares outstanding", "total shares", "total shares outstanding", "股票总数", "總股本", "总股本", "shares_outstanding", "total_shares"),
    "eps": ("eps", "diluted eps", "diluted_eps", "每股收益", "每股盈餘", "基本每股收益", "稀释每股收益"),
}


def extract_metric(data: NormalizedFinancialData | None, canonical_key: str, period: str) -> float | None:
    if not data or not data.metrics:
        return None
    aliases = CANONICAL_METRICS.get(canonical_key, (canonical_key,))
    for m in data.metrics:
        if m.period.strip().upper() == period.strip().upper():
            name_lower = m.metric.strip().lower()
            if any(alias.lower() in name_lower for alias in aliases):
                return m.value
    return None


def reconcile_financials(
    symbol: str,
    period: str,
    is_data: NormalizedFinancialData | None,
    bs_data: NormalizedFinancialData | None,
    cf_data: NormalizedFinancialData | None,
) -> tuple[bool, str | None]:
    """Perform cross-statement reconciliation for the given period.

    Returns (is_valid, error_detail).
    """
    if not is_data or not bs_data or not cf_data:
        return True, None  # Skip check if statements are missing (we validate presence elsewhere)

    # 1. Balance sheet check: Assets = Liabilities + Equity
    assets = extract_metric(bs_data, "total_assets", period)
    liabilities = extract_metric(bs_data, "total_liabilities", period)
    equity = extract_metric(bs_data, "total_equity", period)

    if assets is not None and liabilities is not None and equity is not None:
        diff = abs(assets - (liabilities + equity))
        tolerance = max(1000.0, assets * 0.01)
        if diff > tolerance:
            return False, f"Balance sheet equation failed: Total Assets ({assets}) != Liabilities ({liabilities}) + Equity ({equity}), diff={diff}"
    elif assets is not None or liabilities is not None or equity is not None:
        missing = []
        if assets is None: missing.append("total_assets")
        if liabilities is None: missing.append("total_liabilities")
        if equity is None: missing.append("total_equity")
        return False, f"Balance sheet incomplete for period {period}. Missing fields: {', '.join(missing)}"

    # 2. Net Income check: IS Net Income == CF Net Income
    is_net_income = extract_metric(is_data, "net_income", period)
    cf_net_income = extract_metric(cf_data, "net_income", period)
    if is_net_income is not None and cf_net_income is not None:
        diff = abs(is_net_income - cf_net_income)
        tolerance = max(1000.0, abs(is_net_income) * 0.01)
        if diff > tolerance:
            return False, f"Net income mismatch: Income Statement Net Income ({is_net_income}) != Cash Flow Statement Net Income ({cf_net_income}), diff={diff}"

    # 3. Cash check: CF Ending Cash == BS Cash and Equivalents
    cf_ending_cash = extract_metric(cf_data, "cash_and_equivalents", period)
    bs_cash = extract_metric(bs_data, "cash_and_equivalents", period)
    if cf_ending_cash is not None and bs_cash is not None:
        diff = abs(cf_ending_cash - bs_cash)
        tolerance = max(1000.0, bs_cash * 0.01)
        if diff > tolerance:
            return False, f"Cash balance mismatch: Cash Flow Statement Ending Cash ({cf_ending_cash}) != Balance Sheet Cash and Equivalents ({bs_cash}), diff={diff}"

    return True, None


def compute_derived_metrics(
    period: str,
    period_type: str,
    is_data: NormalizedFinancialData | None,
    bs_data: NormalizedFinancialData | None,
    cf_data: NormalizedFinancialData | None,
    fundamentals_data: NormalizedFinancialData | None = None,
    share_price: float | None = None,
) -> list[DerivedFinancialMetric]:
    derived = []

    # 1. ROE = Net Income / Total Equity * 100
    net_income = extract_metric(is_data, "net_income", period)
    total_equity = extract_metric(bs_data, "total_equity", period)
    if net_income is not None and total_equity and total_equity != 0:
        derived.append(DerivedFinancialMetric(
            metric="ROE",
            value=(net_income / total_equity) * 100,
            unit="percent",
            period=period,
            period_type=period_type,
            formula="Net Income / Total Equity * 100",
            inputs={"net_income": net_income, "total_equity": total_equity},
        ))

    # 2. ROA = Net Income / Total Assets * 100
    total_assets = extract_metric(bs_data, "total_assets", period)
    if net_income is not None and total_assets and total_assets != 0:
        derived.append(DerivedFinancialMetric(
            metric="ROA",
            value=(net_income / total_assets) * 100,
            unit="percent",
            period=period,
            period_type=period_type,
            formula="Net Income / Total Assets * 100",
            inputs={"net_income": net_income, "total_assets": total_assets},
        ))

    # 3. Net Cash = Cash and Equivalents - (Short-term Debt + Long-term Debt)
    cash = extract_metric(bs_data, "cash_and_equivalents", period)
    st_debt = extract_metric(bs_data, "short_term_debt", period) or 0.0
    lt_debt = extract_metric(bs_data, "long_term_debt", period) or 0.0
    if cash is not None:
        derived.append(DerivedFinancialMetric(
            metric="Net Cash",
            value=cash - (st_debt + lt_debt),
            unit="currency",
            period=period,
            period_type=period_type,
            formula="Cash and Equivalents - (Short-term Debt + Long-term Debt)",
            inputs={"cash_and_equivalents": cash, "short_term_debt": st_debt, "long_term_debt": lt_debt},
        ))

    # 4. EV/EBITDA
    # EBITDA = Operating Profit + Depreciation & Amortization
    op_profit = extract_metric(is_data, "operating_profit", period)
    dep_amort = extract_metric(cf_data, "depreciation_amortization", period) or 0.0

    mktcap = None
    if fundamentals_data and fundamentals_data.entity_metadata:
        mktcap = fundamentals_data.entity_metadata.get("mktcap") or fundamentals_data.entity_metadata.get("total_market_value")

    if mktcap is None and fundamentals_data:
        for fact in fundamentals_data.unverified_facts:
            if fact.metric in ("mktcap", "total_market_value"):
                mktcap = fact.value
                break

    shares = None
    if fundamentals_data:
        for fact in fundamentals_data.unverified_facts:
            if fact.metric in ("total_shares", "shares_outstanding"):
                shares = fact.value
                break
    if shares is None:
        shares = extract_metric(bs_data, "shares_outstanding", period)

    if mktcap is None and shares is not None and share_price is not None:
        mktcap = shares * share_price

    if op_profit is not None and cash is not None:
        ebitda = op_profit + dep_amort
        if ebitda > 0 and mktcap is not None:
            ev = mktcap + (st_debt + lt_debt) - cash
            derived.append(DerivedFinancialMetric(
                metric="EV/EBITDA",
                value=ev / ebitda,
                unit="ratio",
                period=period,
                period_type=period_type,
                formula="(Market Cap + Short-term Debt + Long-term Debt - Cash) / (Operating Profit + Depreciation & Amortization)",
                inputs={
                    "market_cap": mktcap,
                    "short_term_debt": st_debt,
                    "long_term_debt": lt_debt,
                    "cash_and_equivalents": cash,
                    "operating_profit": op_profit,
                    "depreciation_amortization": dep_amort
                },
            ))

    # 5. TTM EPS & PE
    eps = None
    if period_type == "annual":
        eps = extract_metric(is_data, "eps", period)
        if eps is not None:
            derived.append(DerivedFinancialMetric(
                metric="TTM EPS",
                value=eps,
                unit="currency",
                period=period,
                period_type=period_type,
                formula="Annual EPS",
                inputs={"eps": eps},
            ))
    elif period_type == "quarterly" and is_data:
        # Sum last 4 quarters EPS
        eps_list = []
        periods_found = set(m.period for m in is_data.metrics if m.period_type == "quarterly")

        def parse_q_period(p_str):
            m = re.search(r"Q([1-4])\s+(\d{4})", p_str, re.IGNORECASE)
            if m:
                return int(m.group(2)), int(m.group(1))
            return 0, 0

        target_y, target_q = parse_q_period(period)
        if target_y > 0:
            required_qs = []
            curr_y, curr_q = target_y, target_q
            for _ in range(4):
                required_qs.append((curr_y, curr_q))
                curr_q -= 1
                if curr_q == 0:
                    curr_q = 4
                    curr_y -= 1

            for ry, rq in required_qs:
                found_p = None
                for p in periods_found:
                    py, pq = parse_q_period(p)
                    if py == ry and pq == rq:
                        found_p = p
                        break
                if found_p:
                    q_eps = extract_metric(is_data, "eps", found_p)
                    if q_eps is not None:
                        eps_list.append((found_p, q_eps))

            if len(eps_list) == 4:
                sum_eps = sum(val for _, val in eps_list)
                inputs = {f"eps_{p}": val for p, val in eps_list}
                derived.append(DerivedFinancialMetric(
                    metric="TTM EPS",
                    value=sum_eps,
                    unit="currency",
                    period=period,
                    period_type=period_type,
                    formula="Sum of last 4 quarters EPS",
                    inputs=inputs,
                ))
                eps = sum_eps

    # 6. PE = Share Price / TTM EPS
    if eps is not None and share_price is not None and eps > 0:
        derived.append(DerivedFinancialMetric(
            metric="PE",
            value=share_price / eps,
            unit="ratio",
            period=period,
            period_type=period_type,
            formula="Share Price / TTM EPS",
            inputs={"share_price": share_price, "ttm_eps": eps},
        ))

    return derived


# --- Section 2: Audit recording logic ---

def log_financial_audit(
    symbol: str,
    vendor: str,
    method: str,
    status: str,
    normalized_data: NormalizedFinancialData,
    detail: str | None = None,
) -> None:
    """Log raw_payload and unverified_facts to financial_audit.jsonl."""
    import datetime

    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "symbol": symbol,
        "vendor": vendor,
        "method": method,
        "status": status,
        "detail": detail,
        "raw_payload": normalized_data.raw_payload,
        "unverified_facts": [asdict(f) for f in normalized_data.unverified_facts],
        "metrics": [asdict(m) for m in normalized_data.metrics],
        "excluded_metrics": list(normalized_data.excluded_metrics),
        "entity_metadata": normalized_data.entity_metadata,
    }

    home_path = Path.home() / ".tradingagents" / "financial_audit.jsonl"
    fallback_path = Path.cwd() / ".tradingagents" / "financial_audit.jsonl"

    for path in (home_path, fallback_path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            break
        except Exception:
            continue
