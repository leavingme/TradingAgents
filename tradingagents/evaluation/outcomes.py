"""Deterministic scoring and conservative architecture comparisons."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import fmean, stdev
from typing import Any


_EXPOSURE = {
    "buy": 1.0,
    "overweight": 0.5,
    "hold": 0.0,
    "underweight": -0.5,
    "sell": -1.0,
}

OUTCOME_SCORING_VERSION = "alpha-exposure-v1"
OUTCOME_MEASUREMENT_VERSION = "post-decision-day-close-v1"
LEGACY_OUTCOME_MEASUREMENT_VERSION = "decision-close-v1"
DEFAULT_HOLD_BAND = 0.02

_RUNTIME_COST_FIELDS = (
    "runtime_seconds",
    "llm_calls",
    "tool_calls",
    "tokens_in",
    "tokens_out",
)

_T_975_BY_DF = (
    0.0,
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
    2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101,
    2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052,
    2.048, 2.045, 2.042,
)


def _student_t_critical_95(sample_count: int) -> float | None:
    """Two-sided 95% Student-t critical value for a paired mean.

    Exact tabulated values cover the small cohorts used by the promotion gate.
    A Cornish-Fisher expansion is sufficiently accurate above thirty degrees
    of freedom and avoids adding a heavy statistics dependency.
    """
    if sample_count < 2:
        return None
    degrees_of_freedom = sample_count - 1
    if degrees_of_freedom <= 30:
        return _T_975_BY_DF[degrees_of_freedom]
    z = 1.959963984540054
    df = float(degrees_of_freedom)
    return (
        z
        + (z**3 + z) / (4 * df)
        + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)
        + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * df**3)
    )


def _paired_cost_summary(values: list[float], total_pairs: int) -> dict[str, Any]:
    sample_count = len(values)
    summary: dict[str, Any] = {
        "sample_count": sample_count,
        "missing_pairs_excluded": total_pairs - sample_count,
        "delta_convention": "challenger_minus_baseline",
    }
    if not values:
        return summary
    mean_delta = fmean(values)
    standard_error = stdev(values) / sqrt(sample_count) if sample_count > 1 else None
    critical_value = _student_t_critical_95(sample_count)
    margin = (
        critical_value * standard_error
        if critical_value is not None and standard_error is not None
        else None
    )
    summary.update({
        "mean_delta": mean_delta,
        "mean_reduction": -mean_delta,
        "standard_error": standard_error,
        "critical_value": critical_value,
        "lower_95_delta": mean_delta - margin if margin is not None else None,
        "upper_95_delta": mean_delta + margin if margin is not None else None,
    })
    return summary


def _runtime_cost_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) and numeric >= 0 else None


def _utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _overlap_adjusted_standard_error(
    series_by_ticker: dict[str, list[tuple[str, str, str, float]]],
    *,
    horizon_sessions: int,
) -> dict[str, Any]:
    """Estimate paired-mean uncertainty without treating overlapping outcomes as IID.

    Consecutive daily evaluations of a multi-session horizon reuse market-return
    observations.  We therefore calculate an overlap-aware Bartlett/Newey-West
    estimate within each ticker and conservatively retain the larger of it and
    the ordinary IID standard error.  Cross-ticker covariance is intentionally
    not invented.  The stored entry/exit dates decide whether two windows
    actually overlap, so gaps in a schedule do not create synthetic covariance.
    """
    ordered = {
        ticker: sorted(rows, key=lambda row: (row[1], row[0]))
        for ticker, rows in series_by_ticker.items()
    }
    values = [row[3] for rows in ordered.values() for row in rows]
    sample_count = len(values)
    if sample_count < 2:
        return {
            "standard_error": None,
            "iid_standard_error": None,
            "overlap_adjusted_standard_error": None,
            "overlap_effective_sample_size": float(sample_count),
            "autocorrelation_lags": 0,
            "overlap_pairs_used": 0,
            "standard_error_method": "max(iid, overlap-aware-newey-west)",
        }

    mean_delta = fmean(values)
    iid_standard_error = stdev(values) / sqrt(sample_count)
    max_sequence_lag = max((len(rows) - 1 for rows in ordered.values()), default=0)
    autocorrelation_lags = min(max(int(horizon_sessions) - 1, 0), max_sequence_lag)
    long_run_sum = sum((value - mean_delta) ** 2 for value in values)
    overlap_pairs_used = 0
    if autocorrelation_lags:
        for rows in ordered.values():
            for lag in range(1, min(autocorrelation_lags, len(rows) - 1) + 1):
                weight = 1.0 - lag / (autocorrelation_lags + 1.0)
                covariance_sum = 0.0
                for index in range(lag, len(rows)):
                    older = rows[index - lag]
                    newer = rows[index]
                    if newer[1] > older[2]:
                        continue
                    covariance_sum += (
                        (newer[3] - mean_delta) * (older[3] - mean_delta)
                    )
                    overlap_pairs_used += 1
                long_run_sum += 2.0 * weight * covariance_sum

    overlap_variance = max(long_run_sum, 0.0) / (
        sample_count * (sample_count - 1)
    )
    overlap_standard_error = sqrt(overlap_variance)
    selected_standard_error = max(iid_standard_error, overlap_standard_error)
    effective_sample_size = (
        float(sample_count)
        if selected_standard_error == 0.0
        else min(
            float(sample_count),
            sample_count * (iid_standard_error / selected_standard_error) ** 2,
        )
    )
    return {
        "standard_error": selected_standard_error,
        "iid_standard_error": iid_standard_error,
        "overlap_adjusted_standard_error": overlap_standard_error,
        "overlap_effective_sample_size": effective_sample_size,
        "autocorrelation_lags": autocorrelation_lags,
        "overlap_pairs_used": overlap_pairs_used,
        "standard_error_method": "max(iid, overlap-aware-newey-west)",
    }


def _scoring_policy(row: dict[str, Any]) -> tuple[str, float]:
    version = str(row.get("scoring_version") or OUTCOME_SCORING_VERSION)
    hold_band = float(row.get("hold_band", DEFAULT_HOLD_BAND))
    if not version or not isfinite(hold_band) or hold_band <= 0:
        raise ValueError("evaluation has an invalid scoring policy")
    return version, hold_band


def _measurement_policy(row: dict[str, Any]) -> str:
    version = str(
        row.get("measurement_version") or LEGACY_OUTCOME_MEASUREMENT_VERSION
    ).strip()
    if not version:
        raise ValueError("evaluation has an invalid measurement policy")
    return version


@dataclass(frozen=True)
class OutcomeMeasurement:
    raw_return: float
    benchmark_return: float
    alpha_return: float
    horizon_sessions: int
    entry_date: str
    exit_date: str
    stock_entry_close: float
    stock_exit_close: float
    benchmark_entry_close: float
    benchmark_exit_close: float
    stock_entry_source_id: str
    stock_exit_source_id: str
    benchmark_entry_source_id: str
    benchmark_exit_source_id: str
    decision_as_of: str
    decision_timezone: str
    entry_cutoff_date: str
    measurement_version: str = OUTCOME_MEASUREMENT_VERSION


def score_outcome(
    rating: str,
    alpha_return: float,
    *,
    hold_band: float = DEFAULT_HOLD_BAND,
) -> dict[str, float | bool | str]:
    """Score one fixed-horizon recommendation without an LLM.

    Directional ratings earn signed benchmark-relative return scaled by their
    intended exposure.  Hold earns a positive score only while absolute alpha
    remains inside the explicit no-action band.
    """
    normalized = rating.strip().lower()
    if normalized not in _EXPOSURE:
        raise ValueError(f"unsupported portfolio rating: {rating!r}")
    alpha = float(alpha_return)
    band = float(hold_band)
    if not isfinite(alpha):
        raise ValueError("alpha_return must be finite")
    if not isfinite(band) or band <= 0:
        raise ValueError("hold_band must be finite and positive")
    exposure = _EXPOSURE[normalized]
    if normalized == "hold":
        hit = abs(alpha) <= band
        score = band - abs(alpha)
    else:
        signed = exposure * alpha
        hit = signed > 0
        score = signed
    return {
        "exposure": exposure,
        "directional_hit": hit,
        "score": score,
        "scoring_version": OUTCOME_SCORING_VERSION,
        "hold_band": band,
    }


def architecture_rollups(
    evaluations: list[dict[str, Any]],
    *,
    include_runtime_costs: bool = True,
) -> list[dict[str, Any]]:
    """Aggregate immutable evaluations without mixing architecture fingerprints.

    Runtime cost metrics belong in operator-facing optimization views. Callers
    constructing investment-agent context can exclude them explicitly.
    """
    groups: dict[
        tuple[str, str, str, str, float, int], list[dict[str, Any]]
    ] = defaultdict(list)
    for row in evaluations:
        scoring_version, hold_band = _scoring_policy(row)
        groups[(
            str(row["architecture_version"]),
            str(row.get("architecture_fingerprint", "legacy-unspecified")),
            _measurement_policy(row),
            scoring_version,
            hold_band,
            int(row["horizon_sessions"]),
        )].append(row)
    output = []
    for (
        version,
        fingerprint,
        measurement_version,
        scoring_version,
        hold_band,
        horizon,
    ), rows in sorted(groups.items()):
        rollup = {
            "architecture_version": version,
            "architecture_fingerprint": fingerprint,
            "measurement_version": measurement_version,
            "scoring_version": scoring_version,
            "hold_band": hold_band,
            "horizon_sessions": horizon,
            "sample_count": len(rows),
            "directional_hit_rate": fmean(bool(row["directional_hit"]) for row in rows),
            "mean_raw_return": fmean(float(row["raw_return"]) for row in rows),
            "mean_alpha_return": fmean(float(row["alpha_return"]) for row in rows),
            "mean_score": fmean(float(row["score"]) for row in rows),
            "analysis_data_status_counts": {
                status: sum(
                    1
                    for row in rows
                    if str(row.get("analysis_data_status") or "not_observed")
                    == status
                )
                for status in sorted({
                    str(row.get("analysis_data_status") or "not_observed")
                    for row in rows
                })
            },
            "analysis_evidence_complete_count": sum(
                bool(row.get("analysis_evidence_complete")) for row in rows
            ),
            "architecture_input_complete_count": sum(
                bool(row.get("architecture_input_complete")) for row in rows
            ),
        }
        if include_runtime_costs:
            for field in _RUNTIME_COST_FIELDS:
                values = [
                    value
                    for row in rows
                    if (value := _runtime_cost_value(row.get(field))) is not None
                ]
                rollup[f"{field}_sample_count"] = len(values)
                if values:
                    rollup[f"mean_{field}"] = fmean(values)
        output.append(rollup)
    return output


def compare_architectures(
    evaluations: list[dict[str, Any]],
    *,
    baseline: str,
    challenger: str,
    horizon_sessions: int = 5,
    minimum_samples: int = 20,
    minimum_paired_samples: int = 20,
    minimum_score_improvement: float = 0.002,
    maximum_pair_start_gap_seconds: float = 3600.0,
) -> dict[str, Any]:
    """Return a conservative promotion gate, never an automatic mutation.

    Pairing uses identical ticker, analysis date, and horizon. Market outcomes
    must match across variants and both runs must start within the configured
    shadow window; ambiguous duplicates or mismatched outcomes are excluded.
    Even a positive paired result remains ``review_required`` so this function
    can never mutate or promote the production architecture.
    """
    if (
        not isfinite(float(maximum_pair_start_gap_seconds))
        or float(maximum_pair_start_gap_seconds) <= 0
    ):
        raise ValueError("maximum_pair_start_gap_seconds must be finite and positive")
    rollups = {
        row["architecture_version"]: row
        for row in architecture_rollups(evaluations)
        if row["horizon_sessions"] == horizon_sessions
    }
    base = rollups.get(baseline)
    challenge = rollups.get(challenger)
    if not base or not challenge:
        return {
            "status": "insufficient_data",
            "reason": "both baseline and challenger require evaluated samples",
        }
    fingerprints = {
        version: sorted({
            str(row.get("architecture_fingerprint", "legacy-unspecified"))
            for row in evaluations
            if str(row.get("architecture_version")) == version
            and int(row.get("horizon_sessions", -1)) == horizon_sessions
        })
        for version in (baseline, challenger)
    }
    scoring_policies = {
        version: sorted({
            _scoring_policy(row)
            for row in evaluations
            if str(row.get("architecture_version")) == version
            and int(row.get("horizon_sessions", -1)) == horizon_sessions
        })
        for version in (baseline, challenger)
    }
    measurement_policies = {
        version: sorted({
            _measurement_policy(row)
            for row in evaluations
            if str(row.get("architecture_version")) == version
            and int(row.get("horizon_sessions", -1)) == horizon_sessions
        })
        for version in (baseline, challenger)
    }
    if any(len(values) != 1 for values in fingerprints.values()):
        return {
            "status": "invalid_comparison",
            "reason": (
                "an architecture label contains multiple configuration fingerprints; "
                "split the cohorts before comparing"
            ),
            "architecture_fingerprints": fingerprints,
            "measurement_policies": measurement_policies,
            "scoring_policies": scoring_policies,
            "baseline": base,
            "challenger": challenge,
        }
    if (
        any(len(values) != 1 for values in measurement_policies.values())
        or measurement_policies[baseline] != measurement_policies[challenger]
    ):
        return {
            "status": "invalid_comparison",
            "reason": (
                "baseline and challenger must each use one identical measurement policy"
            ),
            "architecture_fingerprints": fingerprints,
            "measurement_policies": measurement_policies,
            "scoring_policies": scoring_policies,
            "baseline": base,
            "challenger": challenge,
        }
    if (
        any(len(values) != 1 for values in scoring_policies.values())
        or scoring_policies[baseline] != scoring_policies[challenger]
    ):
        return {
            "status": "invalid_comparison",
            "reason": (
                "baseline and challenger must each use one identical scoring policy"
            ),
            "architecture_fingerprints": fingerprints,
            "measurement_policies": measurement_policies,
            "scoring_policies": scoring_policies,
            "baseline": base,
            "challenger": challenge,
        }
    if min(base["sample_count"], challenge["sample_count"]) < minimum_samples:
        return {
            "status": "insufficient_data",
            "reason": f"each architecture requires at least {minimum_samples} samples",
            "baseline": base,
            "challenger": challenge,
        }
    improvement = challenge["mean_score"] - base["mean_score"]

    grouped: dict[tuple[str, str, int], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in evaluations:
        if int(row.get("horizon_sessions", -1)) != horizon_sessions:
            continue
        version = str(row.get("architecture_version"))
        if version not in {baseline, challenger}:
            continue
        ticker = row.get("ticker")
        analysis_date = row.get("analysis_date")
        if not ticker or not analysis_date:
            continue
        grouped[(str(ticker).upper(), str(analysis_date), horizon_sessions)][version].append(row)

    paired_deltas: list[float] = []
    paired_delta_series: dict[
        str, list[tuple[str, str, str, float]]
    ] = defaultdict(list)
    paired_hit_deltas: list[float] = []
    ambiguous_pairs = 0
    outcome_mismatches = 0
    provenance_mismatches = 0
    evidence_mismatches = 0
    architecture_input_mismatches = 0
    temporal_mismatches = 0
    execution_order_counts = {
        "baseline_first": 0,
        "challenger_first": 0,
        "missing_or_tied": 0,
    }
    paired_start_gaps: list[float] = []
    paired_cost_deltas: dict[str, list[float]] = {
        field: [] for field in _RUNTIME_COST_FIELDS
    }
    ordered_cost_deltas: dict[str, dict[str, list[float]]] = {
        order: {field: [] for field in _RUNTIME_COST_FIELDS}
        for order in ("baseline_first", "challenger_first")
    }
    for variants in grouped.values():
        base_rows = variants.get(baseline, [])
        challenger_rows = variants.get(challenger, [])
        if not base_rows or not challenger_rows:
            continue
        if len(base_rows) != 1 or len(challenger_rows) != 1:
            ambiguous_pairs += 1
            continue
        base_row = base_rows[0]
        challenger_row = challenger_rows[0]
        base_architecture_input = base_row.get("architecture_input_fingerprint")
        challenger_architecture_input = challenger_row.get(
            "architecture_input_fingerprint"
        )
        if (
            not bool(base_row.get("architecture_input_complete"))
            or not bool(challenger_row.get("architecture_input_complete"))
            or not base_architecture_input
            or not challenger_architecture_input
            or base_architecture_input != challenger_architecture_input
            or not base_row.get("architecture_input_schema")
            or base_row.get("architecture_input_schema")
            != challenger_row.get("architecture_input_schema")
        ):
            architecture_input_mismatches += 1
            continue
        base_evidence = base_row.get("analysis_evidence_fingerprint")
        challenger_evidence = challenger_row.get("analysis_evidence_fingerprint")
        if (
            not bool(base_row.get("analysis_evidence_complete"))
            or not bool(challenger_row.get("analysis_evidence_complete"))
            or not base_evidence
            or not challenger_evidence
            or base_evidence != challenger_evidence
            or base_row.get("analysis_data_status")
            != challenger_row.get("analysis_data_status")
        ):
            evidence_mismatches += 1
            continue
        exact_fields = ("market_data_date", "entry_date", "exit_date")
        if any(
            not base_row.get(field) or not challenger_row.get(field)
            for field in exact_fields
        ):
            outcome_mismatches += 1
            continue
        provenance_fields = (
            "stock_entry_source_id",
            "stock_exit_source_id",
            "benchmark_entry_source_id",
            "benchmark_exit_source_id",
        )
        numeric_outcome_fields = (
            "raw_return",
            "benchmark_return",
            "alpha_return",
            "stock_entry_close",
            "stock_exit_close",
            "benchmark_entry_close",
            "benchmark_exit_close",
        )
        if (
            any(
                base_row.get(field) is None or challenger_row.get(field) is None
                for field in (*exact_fields, *numeric_outcome_fields)
            )
            or any(base_row.get(field) != challenger_row.get(field) for field in exact_fields)
            or any(
                abs(float(base_row[field]) - float(challenger_row[field])) > 1e-12
                for field in numeric_outcome_fields
            )
        ):
            outcome_mismatches += 1
            continue
        if (
            any(
                not base_row.get(field) or not challenger_row.get(field)
                for field in provenance_fields
            )
            or any(
                base_row.get(field) != challenger_row.get(field)
                for field in provenance_fields
            )
        ):
            provenance_mismatches += 1
            continue
        base_started = _utc_timestamp(base_row.get("run_started_at"))
        challenger_started = _utc_timestamp(challenger_row.get("run_started_at"))
        if base_started is None or challenger_started is None:
            temporal_mismatches += 1
            continue
        start_gap = abs((challenger_started - base_started).total_seconds())
        if start_gap > maximum_pair_start_gap_seconds:
            temporal_mismatches += 1
            continue
        paired_start_gaps.append(start_gap)
        if base_started < challenger_started:
            execution_order = "baseline_first"
        elif challenger_started < base_started:
            execution_order = "challenger_first"
        else:
            execution_order = "missing_or_tied"
        execution_order_counts[execution_order] += 1
        score_delta = float(challenger_row["score"]) - float(base_row["score"])
        paired_deltas.append(score_delta)
        paired_delta_series[str(base_row["ticker"]).upper()].append(
            (
                str(base_row["analysis_date"]),
                str(base_row["entry_date"]),
                str(base_row["exit_date"]),
                score_delta,
            )
        )
        paired_hit_deltas.append(
            float(bool(challenger_row["directional_hit"]))
            - float(bool(base_row["directional_hit"]))
        )
        for field in _RUNTIME_COST_FIELDS:
            base_value = _runtime_cost_value(base_row.get(field))
            challenger_value = _runtime_cost_value(challenger_row.get(field))
            if base_value is None or challenger_value is None:
                continue
            delta = challenger_value - base_value
            if isfinite(delta):
                paired_cost_deltas[field].append(delta)
                if execution_order in ordered_cost_deltas:
                    ordered_cost_deltas[execution_order][field].append(delta)

    paired_count = len(paired_deltas)
    paired_summary: dict[str, Any] = {
        "sample_count": paired_count,
        "minimum_required": minimum_paired_samples,
        "minimum_score_improvement": minimum_score_improvement,
        "horizon_sessions": horizon_sessions,
        "ambiguous_pairs_excluded": ambiguous_pairs,
        "outcome_mismatches_excluded": outcome_mismatches,
        "provenance_mismatches_excluded": provenance_mismatches,
        "evidence_mismatches_excluded": evidence_mismatches,
        "architecture_input_mismatches_excluded": architecture_input_mismatches,
        "temporal_mismatches_excluded": temporal_mismatches,
        "maximum_pair_start_gap_seconds": maximum_pair_start_gap_seconds,
    }
    passes_paired_gate = False
    if paired_count:
        mean_delta = fmean(paired_deltas)
        uncertainty = _overlap_adjusted_standard_error(
            paired_delta_series,
            horizon_sessions=horizon_sessions,
        )
        standard_error = uncertainty["standard_error"]
        effective_sample_count = (
            max(
                2,
                min(
                    paired_count,
                    int(uncertainty["overlap_effective_sample_size"] + 1e-12),
                ),
            )
            if paired_count > 1
            else paired_count
        )
        critical_value = _student_t_critical_95(effective_sample_count)
        lower_95 = (
            mean_delta - critical_value * standard_error
            if standard_error is not None and critical_value is not None
            else None
        )
        paired_summary.update({
            "mean_score_delta": mean_delta,
            "mean_hit_rate_delta": fmean(paired_hit_deltas),
            "critical_value": critical_value,
            "critical_effective_sample_count": effective_sample_count,
            "lower_95_score_delta": lower_95,
            **uncertainty,
        })
        passes_paired_gate = (
            paired_count >= minimum_paired_samples
            and lower_95 is not None
            and lower_95 >= minimum_score_improvement
        )

    known_order_pairs = (
        execution_order_counts["baseline_first"]
        + execution_order_counts["challenger_first"]
    )
    order_imbalance = abs(
        execution_order_counts["baseline_first"]
        - execution_order_counts["challenger_first"]
    )
    if execution_order_counts["missing_or_tied"]:
        cost_comparison_status = "unverifiable_order"
    elif known_order_pairs < 2:
        cost_comparison_status = "insufficient_order_samples"
    elif order_imbalance <= 1:
        cost_comparison_status = "counterbalanced"
    else:
        cost_comparison_status = "order_confounded"

    return {
        "status": "review_required",
        "reason": (
            "human review is always required; paired shadow evidence is sufficient "
            "for consideration" if passes_paired_gate else
            "paired shadow evidence is insufficient; sequential cohorts are regime-confounded"
        ),
        "passes_point_estimate": improvement >= minimum_score_improvement,
        "passes_paired_gate": passes_paired_gate,
        "score_improvement": improvement,
        "architecture_fingerprints": fingerprints,
        "measurement_policies": measurement_policies,
        "scoring_policies": scoring_policies,
        "paired": paired_summary,
        "execution_order": {
            **execution_order_counts,
            "imbalance": order_imbalance,
            "cost_comparison_status": cost_comparison_status,
            "mean_start_gap_seconds": (
                fmean(paired_start_gaps) if paired_start_gaps else None
            ),
            "max_start_gap_seconds": max(paired_start_gaps, default=None),
        },
        "paired_costs": {
            field: _paired_cost_summary(values, paired_count)
            for field, values in paired_cost_deltas.items()
        },
        "paired_costs_by_execution_order": {
            order: {
                field: _paired_cost_summary(
                    values,
                    execution_order_counts[order],
                )
                for field, values in fields.items()
            }
            for order, fields in ordered_cost_deltas.items()
        },
        "baseline": base,
        "challenger": challenge,
    }
