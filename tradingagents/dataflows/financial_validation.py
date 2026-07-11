"""Normalization and deterministic validation for financial vendor data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from datetime import date

from .data_validation import ValidationResult, ValidationStatus


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


def render_financial_data(data: NormalizedFinancialData) -> str:
    derived = derive_financial_metrics(data)
    return json.dumps(
        {
            "status": "verified",
            "entity": data.entity_metadata,
            "metrics": [asdict(metric) for metric in data.metrics],
            "derived_metrics": [asdict(metric) for metric in derived],
            "unverified_fact_count": len(data.unverified_facts),
        },
        ensure_ascii=False,
        indent=2,
    )
