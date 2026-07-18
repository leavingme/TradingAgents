"""Deterministic scoring and conservative architecture comparisons."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import fmean, median, stdev
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
DEFAULT_OUTCOME_HORIZON_SESSIONS = 5
DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES = 20
LONGITUDINAL_CONTEXT_SCHEMA = "tradingagents/audited-longitudinal-outcomes/v8"
ARCHITECTURE_OUTCOME_ASSESSMENT_SCHEMA = (
    "tradingagents/architecture-outcome-assessment/v2"
)
ROLLING_OUTCOME_MONITORING_SCHEMA = (
    "tradingagents/rolling-outcome-monitoring/v1"
)
ROLLING_OUTCOME_WINDOW_SIZES = (5, 10, 20)

_RUNTIME_COST_FIELDS = (
    "runtime_seconds",
    "llm_calls",
    "tool_calls",
    "tokens_in",
    "tokens_out",
)
_AGENT_COST_FIELDS = ("llm_calls", "tool_calls", "tokens_in", "tokens_out")
ARCHITECTURE_OPTIMIZATION_ASSESSMENT_SCHEMA = (
    "tradingagents/architecture-optimization-assessment/v1"
)

_T_975_BY_DF = (
    0.0,
    12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262,
    2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101,
    2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052,
    2.048, 2.045, 2.042,
)


def longitudinal_evaluation_policy() -> dict[str, Any]:
    """Return the deterministic outcome policy that can enter agent context."""
    return {
        "measurement_version": OUTCOME_MEASUREMENT_VERSION,
        "scoring_version": OUTCOME_SCORING_VERSION,
        "hold_band": DEFAULT_HOLD_BAND,
        "horizon_sessions": DEFAULT_OUTCOME_HORIZON_SESSIONS,
        "context_schema": LONGITUDINAL_CONTEXT_SCHEMA,
    }


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


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _agent_cost_mapping(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or len(value) > 13:
        return {}
    return {
        agent: fields
        for agent, fields in value.items()
        if isinstance(agent, str)
        and 0 < len(agent) <= 64
        and isinstance(fields, dict)
    }


def _architecture_optimization_assessment(
    comparison: dict[str, Any],
) -> dict[str, Any]:
    """Translate comparison statistics into a conservative operator action.

    This layer is deliberately deterministic and advisory.  It keeps outcome,
    experiment-integrity, and cost evidence separate so a cheaper challenger
    cannot be mistaken for a better investment architecture.
    """
    paired = comparison.get("paired")
    paired = paired if isinstance(paired, dict) else {}
    comparison_policy = comparison.get("comparison_policy")
    comparison_policy = (
        comparison_policy if isinstance(comparison_policy, dict) else {}
    )
    sample_progress = comparison.get("sample_progress")
    sample_progress = sample_progress if isinstance(sample_progress, dict) else {}
    paired_count = int(paired.get("sample_count") or 0)
    paired_minimum = int(
        paired.get("minimum_required")
        or comparison_policy.get("minimum_paired_samples")
        or 0
    )
    minimum_score_improvement = _runtime_cost_value(
        paired.get("minimum_score_improvement")
        if paired.get("minimum_score_improvement") is not None
        else comparison_policy.get("minimum_score_improvement")
    )
    exclusion_fields = (
        "ambiguous_pairs_excluded",
        "outcome_mismatches_excluded",
        "provenance_mismatches_excluded",
        "evidence_mismatches_excluded",
        "architecture_input_mismatches_excluded",
        "temporal_mismatches_excluded",
    )
    exclusions = {
        field: max(int(paired.get(field) or 0), 0)
        for field in exclusion_fields
    }
    excluded_count = sum(exclusions.values())
    comparison_status = str(comparison.get("status") or "invalid_comparison")

    if comparison_status == "invalid_comparison":
        integrity_status = "invalid_comparison"
    elif paired_count == 0 and excluded_count == 0:
        integrity_status = "not_observed"
    elif excluded_count and paired_count == 0:
        integrity_status = "failing"
    elif excluded_count > paired_count:
        integrity_status = "degraded"
    else:
        integrity_status = "usable"

    lower_score = paired.get("lower_95_score_delta")
    upper_score = paired.get("upper_95_score_delta")
    if comparison_status == "invalid_comparison":
        outcome_status = "invalid_comparison"
    elif not bool(sample_progress.get("sufficient")) or paired_count < paired_minimum:
        outcome_status = "insufficient_paired_samples"
    elif bool(comparison.get("passes_paired_gate")):
        outcome_status = "paired_improvement_supported"
    elif (
        upper_score is not None
        and minimum_score_improvement is not None
        and float(upper_score) < minimum_score_improvement
    ):
        outcome_status = "minimum_improvement_not_supported"
    else:
        outcome_status = "inconclusive"

    paired_costs = comparison.get("paired_costs")
    paired_costs = paired_costs if isinstance(paired_costs, dict) else {}
    token_cost = paired_costs.get("tokens_in")
    token_cost = token_cost if isinstance(token_cost, dict) else {}
    token_cost_count = int(token_cost.get("sample_count") or 0)
    execution_order = comparison.get("execution_order")
    execution_order = execution_order if isinstance(execution_order, dict) else {}
    order_status = str(execution_order.get("cost_comparison_status") or "not_observed")
    lower_cost = token_cost.get("lower_95_delta")
    upper_cost = token_cost.get("upper_95_delta")
    if token_cost_count < paired_minimum or paired_minimum <= 0:
        cost_status = "insufficient_paired_cost_samples"
    elif order_status != "counterbalanced":
        cost_status = "execution_order_confounded"
    elif upper_cost is not None and float(upper_cost) < 0:
        cost_status = "input_token_reduction_supported"
    elif lower_cost is not None and float(lower_cost) > 0:
        cost_status = "input_token_increase_supported"
    else:
        cost_status = "inconclusive"

    baseline = comparison.get("baseline")
    challenger = comparison.get("challenger")
    baseline = baseline if isinstance(baseline, dict) else {}
    challenger = challenger if isinstance(challenger, dict) else {}
    baseline_agents = _agent_cost_mapping(baseline.get("agent_costs"))
    challenger_agents = _agent_cost_mapping(challenger.get("agent_costs"))
    paired_agents = comparison.get("paired_agent_costs")
    paired_agents = paired_agents if isinstance(paired_agents, dict) else {}
    ranked_agents = sorted(
        (
            (agent, _runtime_cost_value(fields.get("mean_tokens_in")))
            for agent, fields in baseline_agents.items()
        ),
        key=lambda item: (
            -(item[1] if item[1] is not None else -1.0),
            item[0],
        ),
    )
    hotspots = []
    for agent, baseline_tokens in ranked_agents[:3]:
        challenger_tokens = _runtime_cost_value(
            challenger_agents.get(agent, {}).get("mean_tokens_in")
        )
        agent_pair = paired_agents.get(agent)
        agent_pair = agent_pair if isinstance(agent_pair, dict) else {}
        token_pair = agent_pair.get("tokens_in")
        token_pair = token_pair if isinstance(token_pair, dict) else {}
        hotspots.append({
            "agent": agent,
            "baseline_mean_tokens_in": baseline_tokens,
            "challenger_mean_tokens_in": challenger_tokens,
            "paired_sample_count": int(token_pair.get("sample_count") or 0),
            "mean_delta": token_pair.get("mean_delta"),
            "lower_95_delta": token_pair.get("lower_95_delta"),
            "upper_95_delta": token_pair.get("upper_95_delta"),
        })

    if comparison_status == "invalid_comparison":
        recommended_action = "repair_comparison_definition"
    elif integrity_status in {"failing", "degraded"}:
        recommended_action = "repair_pair_integrity"
    elif outcome_status == "insufficient_paired_samples":
        recommended_action = "continue_sample_collection"
    elif outcome_status == "minimum_improvement_not_supported":
        recommended_action = "retain_baseline"
    elif outcome_status == "paired_improvement_supported":
        recommended_action = (
            "human_review_cost_tradeoff"
            if cost_status == "input_token_increase_supported"
            else "human_review_challenger"
        )
    else:
        recommended_action = "continue_sample_collection"

    return {
        "schema": ARCHITECTURE_OPTIMIZATION_ASSESSMENT_SCHEMA,
        "automatic_mutation_allowed": False,
        "recommended_action": recommended_action,
        "experiment_integrity": {
            "status": integrity_status,
            "valid_pair_count": paired_count,
            "excluded_pair_count": excluded_count,
            "exclusions": exclusions,
        },
        "outcome_evidence": {
            "status": outcome_status,
            "paired_sample_count": paired_count,
            "minimum_required": paired_minimum,
            "minimum_score_improvement": minimum_score_improvement,
            "mean_score_delta": paired.get("mean_score_delta"),
            "lower_95_score_delta": lower_score,
            "upper_95_score_delta": upper_score,
        },
        "cost_evidence": {
            "status": cost_status,
            "primary_metric": "tokens_in",
            "paired_sample_count": token_cost_count,
            "execution_order_status": order_status,
            "mean_delta": token_cost.get("mean_delta"),
            "lower_95_delta": lower_cost,
            "upper_95_delta": upper_cost,
        },
        "agent_hotspots": hotspots,
    }


def _with_optimization_assessment(result: dict[str, Any]) -> dict[str, Any]:
    result["optimization_assessment"] = _architecture_optimization_assessment(result)
    return result


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


def _outcome_window_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [float(row["score"]) for row in rows]
    alpha_returns = [float(row["alpha_return"]) for row in rows]
    return {
        "sample_count": len(rows),
        "from_analysis_date": rows[0]["analysis_date"] if rows else None,
        "through_analysis_date": rows[-1]["analysis_date"] if rows else None,
        "mean_score": fmean(scores) if scores else None,
        "median_score": median(scores) if scores else None,
        "mean_alpha_return": fmean(alpha_returns) if alpha_returns else None,
        "directional_hit_rate": (
            fmean(bool(row["directional_hit"]) for row in rows) if rows else None
        ),
        "negative_score_rate": (
            fmean(score < 0 for score in scores) if scores else None
        ),
    }


def _rolling_outcome_monitoring(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe recent outcome drift without treating it as causal evidence.

    A single architecture can have retries or remediation runs on the same
    ticker/date. Those dates are ambiguous for a longitudinal sequence and are
    excluded instead of being allowed to overweight one market day.
    """
    by_ticker_date: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    invalid_rows = 0
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        analysis_date = str(row.get("analysis_date") or "").strip()
        score = _finite_number(row.get("score"))
        alpha_return = _finite_number(row.get("alpha_return"))
        try:
            parsed_date = datetime.fromisoformat(analysis_date).date()
        except (TypeError, ValueError):
            invalid_rows += 1
            continue
        if (
            not ticker
            or score is None
            or alpha_return is None
            or "directional_hit" not in row
        ):
            invalid_rows += 1
            continue
        normalized = dict(row)
        normalized["ticker"] = ticker
        normalized["analysis_date"] = parsed_date.isoformat()
        normalized["score"] = score
        normalized["alpha_return"] = alpha_return
        by_ticker_date[ticker][parsed_date.isoformat()].append(normalized)

    ticker_payloads: dict[str, Any] = {}
    for ticker, dated_rows in sorted(by_ticker_date.items()):
        ambiguous_dates = sorted(
            analysis_date
            for analysis_date, variants in dated_rows.items()
            if len(variants) != 1
        )
        eligible = sorted(
            (
                variants[0]
                for analysis_date, variants in dated_rows.items()
                if len(variants) == 1
            ),
            key=lambda row: str(row["analysis_date"]),
        )
        windows: dict[str, Any] = {}
        for window_size in ROLLING_OUTCOME_WINDOW_SIZES:
            current = eligible[-window_size:]
            previous = eligible[-2 * window_size : -window_size]
            current_summary = _outcome_window_summary(current)
            previous_summary = _outcome_window_summary(previous)
            comparison_ready = (
                len(current) == window_size and len(previous) == window_size
            )
            windows[str(window_size)] = {
                "status": (
                    "comparison_ready" if comparison_ready else "insufficient_history"
                ),
                "required_samples": 2 * window_size,
                "current": current_summary,
                "previous": previous_summary,
                "current_minus_previous": (
                    {
                        field: current_summary[field] - previous_summary[field]
                        for field in (
                            "mean_score",
                            "mean_alpha_return",
                            "directional_hit_rate",
                            "negative_score_rate",
                        )
                    }
                    if comparison_ready
                    else None
                ),
            }
        ticker_payloads[ticker] = {
            "distinct_analysis_date_count": len(eligible),
            "ambiguous_analysis_date_count": len(ambiguous_dates),
            "ambiguous_rows_excluded": sum(
                len(dated_rows[analysis_date]) for analysis_date in ambiguous_dates
            ),
            "windows": windows,
        }

    return {
        "schema": ROLLING_OUTCOME_MONITORING_SCHEMA,
        "interpretation": (
            "Descriptive recent-versus-previous monitoring only. Sequential windows "
            "can overlap in return exposure and remain regime-confounded."
        ),
        "automatic_architecture_mutation_allowed": False,
        "causal_claim_allowed": False,
        "ordering": "ticker_then_analysis_date",
        "window_sizes": list(ROLLING_OUTCOME_WINDOW_SIZES),
        "invalid_rows_excluded": invalid_rows,
        "tickers": ticker_payloads,
    }


def _architecture_outcome_assessment(
    rows: list[dict[str, Any]],
    *,
    horizon_sessions: int,
) -> dict[str, Any]:
    """Describe one architecture cohort without claiming causal improvement."""
    score_rows = [
        (row, score)
        for row in rows
        if (score := _finite_number(row.get("score"))) is not None
    ]
    scores = [score for _, score in score_rows]
    alpha_returns = [
        value
        for row in rows
        if (value := _finite_number(row.get("alpha_return"))) is not None
    ]
    raw_returns = [
        value
        for row in rows
        if (value := _finite_number(row.get("raw_return"))) is not None
    ]
    negative_scores = [value for value in scores if value < 0]

    series_by_ticker: dict[str, list[tuple[str, str, str, float]]] = defaultdict(list)
    for row, score in score_rows:
        ticker = row.get("ticker")
        analysis_date = row.get("analysis_date")
        entry_date = row.get("entry_date")
        exit_date = row.get("exit_date")
        if not all(
            isinstance(value, str) and value
            for value in (ticker, analysis_date, entry_date, exit_date)
        ):
            continue
        series_by_ticker[str(ticker).upper()].append(
            (str(analysis_date), str(entry_date), str(exit_date), score)
        )
    temporal_sample_count = sum(len(values) for values in series_by_ticker.values())
    uncertainty = _overlap_adjusted_standard_error(
        series_by_ticker,
        horizon_sessions=horizon_sessions,
    )
    effective_sample_count = (
        max(
            2,
            min(
                temporal_sample_count,
                int(uncertainty["overlap_effective_sample_size"] + 1e-12),
            ),
        )
        if temporal_sample_count > 1
        else temporal_sample_count
    )
    critical_value = _student_t_critical_95(effective_sample_count)
    standard_error = uncertainty["standard_error"]
    score_mean = fmean(scores) if scores else None
    margin = (
        critical_value * standard_error
        if critical_value is not None
        and standard_error is not None
        and temporal_sample_count == len(scores)
        else None
    )

    rating_groups: dict[str, list[tuple[dict[str, Any], float]]] = defaultdict(list)
    for row, score in score_rows:
        rating = str(row.get("rating") or "unknown").strip().lower()
        if rating not in _EXPOSURE:
            rating = "unknown"
        rating_groups[rating].append((row, score))
    rating_breakdown = {}
    for rating, group in sorted(rating_groups.items()):
        group_alpha = [
            value
            for row, _ in group
            if (value := _finite_number(row.get("alpha_return"))) is not None
        ]
        rating_breakdown[rating] = {
            "sample_count": len(group),
            "directional_hit_rate": fmean(
                bool(row.get("directional_hit")) for row, _ in group
            ),
            "mean_alpha_return": fmean(group_alpha) if group_alpha else None,
            "mean_score": fmean(score for _, score in group),
        }

    if len(scores) < DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES:
        status = "insufficient_samples"
    elif temporal_sample_count != len(scores):
        status = "incomplete_temporal_evidence"
    else:
        status = "uncertainty_ready"
    return {
        "schema": ARCHITECTURE_OUTCOME_ASSESSMENT_SCHEMA,
        "status": status,
        "minimum_samples": DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES,
        "score_sample_count": len(scores),
        "temporal_sample_count": temporal_sample_count,
        "missing_temporal_windows": len(scores) - temporal_sample_count,
        "mean_score": score_mean,
        "median_score": median(scores) if scores else None,
        "score_standard_deviation": stdev(scores) if len(scores) > 1 else None,
        "negative_score_rate": (
            len(negative_scores) / len(scores) if scores else None
        ),
        "worst_score": min(scores) if scores else None,
        "mean_negative_score": (
            fmean(negative_scores) if negative_scores else None
        ),
        "median_alpha_return": median(alpha_returns) if alpha_returns else None,
        "median_raw_return": median(raw_returns) if raw_returns else None,
        "lower_95_mean_score": (
            score_mean - margin
            if score_mean is not None and margin is not None
            else None
        ),
        "upper_95_mean_score": (
            score_mean + margin
            if score_mean is not None and margin is not None
            else None
        ),
        "critical_value": critical_value,
        "critical_effective_sample_count": effective_sample_count,
        **uncertainty,
        "rating_breakdown": rating_breakdown,
        "rolling_monitoring": _rolling_outcome_monitoring(rows),
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

    Runtime cost metrics and descriptive uncertainty assessments belong in
    operator-facing optimization views. Callers constructing investment-agent
    context exclude both through ``include_runtime_costs=False``.
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
            rollup["outcome_assessment"] = _architecture_outcome_assessment(
                rows,
                horizon_sessions=horizon,
            )
            for field in _RUNTIME_COST_FIELDS:
                values = [
                    value
                    for row in rows
                    if (value := _runtime_cost_value(row.get(field))) is not None
                ]
                rollup[f"{field}_sample_count"] = len(values)
                if values:
                    rollup[f"mean_{field}"] = fmean(values)
            agent_names = sorted({
                agent
                for row in rows
                for agent in _agent_cost_mapping(row.get("agent_costs"))
            })
            if agent_names:
                rollup["agent_costs"] = {}
                for agent in agent_names:
                    agent_rollup: dict[str, Any] = {}
                    for field in _AGENT_COST_FIELDS:
                        values = [
                            value
                            for row in rows
                            if (
                                value := _runtime_cost_value(
                                    _agent_cost_mapping(row.get("agent_costs"))
                                    .get(agent, {})
                                    .get(field)
                                )
                            ) is not None
                        ]
                        agent_rollup[f"{field}_sample_count"] = len(values)
                        if values:
                            agent_rollup[f"mean_{field}"] = fmean(values)
                    rollup["agent_costs"][agent] = agent_rollup
        output.append(rollup)
    return output


def compare_architectures(
    evaluations: list[dict[str, Any]],
    *,
    baseline: str,
    challenger: str,
    baseline_fingerprint: str | None = None,
    challenger_fingerprint: str | None = None,
    horizon_sessions: int = DEFAULT_OUTCOME_HORIZON_SESSIONS,
    minimum_samples: int = DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES,
    minimum_paired_samples: int = DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES,
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
        not isinstance(baseline, str)
        or not baseline.strip()
        or not isinstance(challenger, str)
        or not challenger.strip()
        or baseline != baseline.strip()
        or challenger != challenger.strip()
        or len(baseline) > 128
        or len(challenger) > 128
        or baseline == challenger
    ):
        raise ValueError("baseline and challenger must be distinct nonempty labels")
    if bool(baseline_fingerprint) != bool(challenger_fingerprint):
        raise ValueError(
            "baseline_fingerprint and challenger_fingerprint must be provided together"
        )
    for label, fingerprint in (
        ("baseline_fingerprint", baseline_fingerprint),
        ("challenger_fingerprint", challenger_fingerprint),
    ):
        if fingerprint is not None and (
            not isinstance(fingerprint, str)
            or not fingerprint.strip()
            or fingerprint != fingerprint.strip()
            or len(fingerprint) > 128
        ):
            raise ValueError(
                f"{label} must be a nonempty string of at most 128 characters"
            )
    if (
        isinstance(minimum_samples, bool)
        or not isinstance(minimum_samples, int)
        or minimum_samples < 1
    ):
        raise ValueError("minimum_samples must be a positive integer")
    if (
        isinstance(minimum_paired_samples, bool)
        or not isinstance(minimum_paired_samples, int)
        or minimum_paired_samples < 2
    ):
        raise ValueError("minimum_paired_samples must be an integer of at least two")
    if (
        not isfinite(float(minimum_score_improvement))
        or float(minimum_score_improvement) < 0
    ):
        raise ValueError("minimum_score_improvement must be finite and nonnegative")
    if (
        not isfinite(float(maximum_pair_start_gap_seconds))
        or float(maximum_pair_start_gap_seconds) <= 0
    ):
        raise ValueError("maximum_pair_start_gap_seconds must be finite and positive")
    selected_fingerprints = (
        {
            baseline: str(baseline_fingerprint),
            challenger: str(challenger_fingerprint),
        }
        if baseline_fingerprint and challenger_fingerprint
        else None
    )
    evaluations = [
        row
        for row in evaluations
        if str(row.get("architecture_version")) in {baseline, challenger}
        and (
            selected_fingerprints is None
            or str(row.get("architecture_fingerprint", "legacy-unspecified"))
            == selected_fingerprints[str(row.get("architecture_version"))]
        )
    ]
    selection_payload = {
        "selected_architecture_fingerprints": selected_fingerprints,
        "comparison_policy": {
            "horizon_sessions": horizon_sessions,
            "minimum_samples": minimum_samples,
            "minimum_paired_samples": minimum_paired_samples,
            "minimum_score_improvement": float(minimum_score_improvement),
            "maximum_pair_start_gap_seconds": float(
                maximum_pair_start_gap_seconds
            ),
        },
    }
    rollups = {
        row["architecture_version"]: row
        for row in architecture_rollups(evaluations)
        if row["horizon_sessions"] == horizon_sessions
    }
    base = rollups.get(baseline)
    challenge = rollups.get(challenger)
    if not base or not challenge:
        baseline_count = int(base["sample_count"]) if base else 0
        challenger_count = int(challenge["sample_count"]) if challenge else 0
        return _with_optimization_assessment({
            **selection_payload,
            "status": "insufficient_data",
            "reason": "both baseline and challenger require evaluated samples",
            "sample_progress": {
                "baseline": baseline_count,
                "challenger": challenger_count,
                "minimum_required_each": minimum_samples,
                "sufficient": False,
            },
            "missing_architectures": [
                version
                for version, row in ((baseline, base), (challenger, challenge))
                if row is None
            ],
            "baseline": base,
            "challenger": challenge,
        })
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
        return _with_optimization_assessment({
            **selection_payload,
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
        })
    if (
        any(len(values) != 1 for values in measurement_policies.values())
        or measurement_policies[baseline] != measurement_policies[challenger]
    ):
        return _with_optimization_assessment({
            **selection_payload,
            "status": "invalid_comparison",
            "reason": (
                "baseline and challenger must each use one identical measurement policy"
            ),
            "architecture_fingerprints": fingerprints,
            "measurement_policies": measurement_policies,
            "scoring_policies": scoring_policies,
            "baseline": base,
            "challenger": challenge,
        })
    if (
        any(len(values) != 1 for values in scoring_policies.values())
        or scoring_policies[baseline] != scoring_policies[challenger]
    ):
        return _with_optimization_assessment({
            **selection_payload,
            "status": "invalid_comparison",
            "reason": (
                "baseline and challenger must each use one identical scoring policy"
            ),
            "architecture_fingerprints": fingerprints,
            "measurement_policies": measurement_policies,
            "scoring_policies": scoring_policies,
            "baseline": base,
            "challenger": challenge,
        })
    sequential_sample_sufficient = (
        min(base["sample_count"], challenge["sample_count"]) >= minimum_samples
    )
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
    paired_agent_cost_deltas: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {field: [] for field in _AGENT_COST_FIELDS}
    )
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
        base_agent_costs = _agent_cost_mapping(base_row.get("agent_costs"))
        challenger_agent_costs = _agent_cost_mapping(
            challenger_row.get("agent_costs")
        )
        for agent in sorted(set(base_agent_costs) | set(challenger_agent_costs)):
            for field in _AGENT_COST_FIELDS:
                base_value = _runtime_cost_value(
                    base_agent_costs.get(agent, {}).get(field)
                )
                challenger_value = _runtime_cost_value(
                    challenger_agent_costs.get(agent, {}).get(field)
                )
                if base_value is None or challenger_value is None:
                    continue
                delta = challenger_value - base_value
                if isfinite(delta):
                    paired_agent_cost_deltas[agent][field].append(delta)

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
        upper_95 = (
            mean_delta + critical_value * standard_error
            if standard_error is not None and critical_value is not None
            else None
        )
        paired_summary.update({
            "mean_score_delta": mean_delta,
            "mean_hit_rate_delta": fmean(paired_hit_deltas),
            "critical_value": critical_value,
            "critical_effective_sample_count": effective_sample_count,
            "lower_95_score_delta": lower_95,
            "upper_95_score_delta": upper_95,
            **uncertainty,
        })
        passes_paired_gate = (
            sequential_sample_sufficient
            and paired_count >= minimum_paired_samples
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

    if not sequential_sample_sufficient:
        status = "insufficient_data"
        reason = (
            f"each architecture requires at least {minimum_samples} samples; "
            "early paired diagnostics are reported for cost control"
        )
    elif passes_paired_gate:
        status = "review_required"
        reason = (
            "human review is always required; paired shadow evidence is sufficient "
            "for consideration"
        )
    else:
        status = "review_required"
        reason = (
            "paired shadow evidence is insufficient; sequential cohorts are "
            "regime-confounded"
        )

    return _with_optimization_assessment({
        **selection_payload,
        "status": status,
        "reason": reason,
        "sample_progress": {
            "baseline": base["sample_count"],
            "challenger": challenge["sample_count"],
            "minimum_required_each": minimum_samples,
            "sufficient": sequential_sample_sufficient,
        },
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
        "paired_agent_costs": {
            agent: {
                field: _paired_cost_summary(values, paired_count)
                for field, values in fields.items()
            }
            for agent, fields in sorted(paired_agent_cost_deltas.items())
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
    })
