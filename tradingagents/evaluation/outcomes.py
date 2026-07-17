"""Deterministic scoring and conservative architecture comparisons."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import sqrt
from statistics import fmean, stdev
from typing import Any


_EXPOSURE = {
    "buy": 1.0,
    "overweight": 0.5,
    "hold": 0.0,
    "underweight": -0.5,
    "sell": -1.0,
}


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


def score_outcome(
    rating: str,
    alpha_return: float,
    *,
    hold_band: float = 0.02,
) -> dict[str, float | bool]:
    """Score one fixed-horizon recommendation without an LLM.

    Directional ratings earn signed benchmark-relative return scaled by their
    intended exposure.  Hold earns a positive score only while absolute alpha
    remains inside the explicit no-action band.
    """
    normalized = rating.strip().lower()
    if normalized not in _EXPOSURE:
        raise ValueError(f"unsupported portfolio rating: {rating!r}")
    alpha = float(alpha_return)
    exposure = _EXPOSURE[normalized]
    if normalized == "hold":
        hit = abs(alpha) <= hold_band
        score = hold_band - abs(alpha)
    else:
        signed = exposure * alpha
        hit = signed > 0
        score = signed
    return {
        "exposure": exposure,
        "directional_hit": hit,
        "score": score,
    }


def architecture_rollups(evaluations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate immutable evaluation rows by architecture and horizon."""
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in evaluations:
        groups[(str(row["architecture_version"]), int(row["horizon_sessions"]))].append(row)
    output = []
    for (version, horizon), rows in sorted(groups.items()):
        output.append(
            {
                "architecture_version": version,
                "horizon_sessions": horizon,
                "sample_count": len(rows),
                "directional_hit_rate": fmean(bool(row["directional_hit"]) for row in rows),
                "mean_raw_return": fmean(float(row["raw_return"]) for row in rows),
                "mean_alpha_return": fmean(float(row["alpha_return"]) for row in rows),
                "mean_score": fmean(float(row["score"]) for row in rows),
            }
        )
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
) -> dict[str, Any]:
    """Return a conservative promotion gate, never an automatic mutation.

    Pairing uses identical ticker, analysis date, and horizon. Market outcomes
    must match across variants; ambiguous duplicates or mismatched outcomes are
    excluded. Even a positive paired result remains ``review_required`` so this
    function can never mutate or promote the production architecture.
    """
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
    if any(len(values) != 1 for values in fingerprints.values()):
        return {
            "status": "invalid_comparison",
            "reason": (
                "an architecture label contains multiple configuration fingerprints; "
                "split the cohorts before comparing"
            ),
            "architecture_fingerprints": fingerprints,
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
    paired_hit_deltas: list[float] = []
    ambiguous_pairs = 0
    outcome_mismatches = 0
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
        exact_fields = ("entry_date", "exit_date")
        numeric_outcome_fields = (
            "raw_return",
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
        paired_deltas.append(float(challenger_row["score"]) - float(base_row["score"]))
        paired_hit_deltas.append(
            float(bool(challenger_row["directional_hit"]))
            - float(bool(base_row["directional_hit"]))
        )

    paired_count = len(paired_deltas)
    paired_summary: dict[str, Any] = {
        "sample_count": paired_count,
        "minimum_required": minimum_paired_samples,
        "ambiguous_pairs_excluded": ambiguous_pairs,
        "outcome_mismatches_excluded": outcome_mismatches,
    }
    passes_paired_gate = False
    if paired_count:
        mean_delta = fmean(paired_deltas)
        standard_error = stdev(paired_deltas) / sqrt(paired_count) if paired_count > 1 else None
        lower_95 = (
            mean_delta - 1.96 * standard_error
            if standard_error is not None
            else None
        )
        paired_summary.update({
            "mean_score_delta": mean_delta,
            "mean_hit_rate_delta": fmean(paired_hit_deltas),
            "standard_error": standard_error,
            "lower_95_score_delta": lower_95,
        })
        passes_paired_gate = (
            paired_count >= minimum_paired_samples
            and lower_95 is not None
            and lower_95 >= minimum_score_improvement
        )

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
        "paired": paired_summary,
        "baseline": base,
        "challenger": challenge,
    }
