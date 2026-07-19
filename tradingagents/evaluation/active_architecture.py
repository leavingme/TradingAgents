"""Operator inventory for currently scheduled architecture identities."""

from __future__ import annotations

import re
from typing import Any

from .outcomes import (
    DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES,
    DEFAULT_ARCHITECTURE_MINIMUM_SCORE_IMPROVEMENT,
)


ACTIVE_ARCHITECTURE_OBSERVATION_SCHEMA = (
    "tradingagents/active-architecture-observation/v1"
)
ARCHITECTURE_MEASUREMENT_CONTINUITY_SCHEMA = (
    "tradingagents/architecture-measurement-continuity/v1"
)
MAX_ACTIVE_ARCHITECTURES = 128
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
_IDENTITY_FIELDS = (
    "schema",
    "ticker",
    "asset_type",
    "architecture_version",
    "architecture_fingerprint",
    "architecture_manifest_schema",
    "selected_analysts",
    "research_depth",
    "llm_provider",
    "quick_think_llm",
    "deep_think_llm",
    "longitudinal_context_mode",
)


def _validated_experiment_plan(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("architecture experiment plan must be an object")
    experiment_id = str(value.get("experiment_id") or "")
    fingerprint = str(value.get("fingerprint") or "")
    schema = str(value.get("schema") or "")
    treatment = str(value.get("treatment") or "")
    primary_metric = str(value.get("primary_metric") or "")
    if schema != "tradingagents/architecture-experiment-plan/v1":
        raise ValueError("architecture experiment plan has invalid schema")
    if not _EXPERIMENT_ID_RE.fullmatch(experiment_id):
        raise ValueError("architecture experiment plan has invalid experiment_id")
    if not _SHA256_RE.fullmatch(fingerprint):
        raise ValueError("architecture experiment plan has invalid fingerprint")
    if treatment != "research_manager_longitudinal_context":
        raise ValueError("architecture experiment plan has invalid treatment")
    if primary_metric != "mean_score_delta":
        raise ValueError("architecture experiment plan has invalid primary metric")
    raw_arms = value.get("arms")
    if not isinstance(raw_arms, list) or len(raw_arms) != 2:
        raise ValueError("architecture experiment plan must have exactly two arms")
    arms = []
    for row in raw_arms:
        if not isinstance(row, dict):
            raise ValueError("architecture experiment arm must be an object")
        version = str(row.get("architecture_version") or "")
        arm_fingerprint = str(row.get("architecture_fingerprint") or "")
        mode = str(row.get("longitudinal_context_mode") or "")
        if (
            not _EXPERIMENT_ID_RE.fullmatch(version)
            or not _SHA256_RE.fullmatch(arm_fingerprint)
        ):
            raise ValueError("architecture experiment arm has invalid identity")
        if mode not in {"portfolio_only", "research_and_portfolio"}:
            raise ValueError("architecture experiment arm has invalid treatment mode")
        arms.append({
            "architecture_version": version,
            "architecture_fingerprint": arm_fingerprint,
            "longitudinal_context_mode": mode,
        })
    minimum_samples = int(value.get("minimum_paired_samples") or 0)
    maximum_samples = int(value.get("maximum_paired_samples") or 0)
    minimum_improvement = float(value.get("minimum_score_improvement") or 0)
    pilot_samples = int(value.get("pilot_paired_samples") or 0)
    pilot_match_rate = float(value.get("pilot_required_match_rate") or 0)
    if (
        minimum_samples != DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES
        or maximum_samples < minimum_samples
        or maximum_samples > 200
        or minimum_improvement != DEFAULT_ARCHITECTURE_MINIMUM_SCORE_IMPROVEMENT
        or pilot_samples < 1
        or pilot_samples > 5
        or pilot_match_rate != 1.0
    ):
        raise ValueError("architecture experiment plan has invalid policy")
    return {
        "schema": schema,
        "experiment_id": experiment_id,
        "fingerprint": fingerprint,
        "treatment": treatment,
        "primary_metric": primary_metric,
        "minimum_paired_samples": minimum_samples,
        "maximum_paired_samples": maximum_samples,
        "minimum_score_improvement": minimum_improvement,
        "pilot_paired_samples": pilot_samples,
        "pilot_required_match_rate": pilot_match_rate,
        "arms": arms,
    }


def _validated_experiment_pilot(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("architecture experiment pilot must be an object")
    schema = str(value.get("schema") or "")
    if schema != "tradingagents/architecture-experiment-pilot/v1":
        raise ValueError("architecture experiment pilot has invalid schema")
    status = str(value.get("status") or "")
    action = str(value.get("recommended_action") or "")
    if status not in {"collecting", "passed", "failed"}:
        raise ValueError("architecture experiment pilot has invalid status")
    if action not in {
        "collect_pilot_pairs",
        "continue_preregistered_experiment",
        "implement_shared_pre_treatment_replay",
    }:
        raise ValueError("architecture experiment pilot has invalid action")
    count_fields = (
        "required_paired_samples",
        "observed_paired_samples",
        "eligible_paired_samples",
        "excluded_paired_samples",
        "ambiguous_pairs_excluded",
        "decision_unusable_pairs_excluded",
        "market_date_mismatches_excluded",
        "architecture_input_mismatches_excluded",
        "evidence_mismatches_excluded",
    )
    counts = {field: int(value.get(field) or 0) for field in count_fields}
    if any(count < 0 or count > 10_000 for count in counts.values()):
        raise ValueError("architecture experiment pilot has invalid count")
    required_match_rate = float(value.get("required_match_rate") or 0)
    if required_match_rate != 1.0 or not 1 <= counts["required_paired_samples"] <= 5:
        raise ValueError("architecture experiment pilot has invalid policy")
    return {
        "schema": schema,
        "status": status,
        "recommended_action": action,
        "required_match_rate": required_match_rate,
        **counts,
        "automatic_architecture_mutation_allowed": False,
    }


def _validated_identity(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("scheduled architecture identity must be an object")
    ticker = str(row.get("ticker") or "").strip().upper()
    version = str(row.get("architecture_version") or "").strip()
    fingerprint = str(row.get("architecture_fingerprint") or "").strip()
    if not ticker or len(ticker) > 32:
        raise ValueError("scheduled architecture identity has invalid ticker")
    if not version or len(version) > 80:
        raise ValueError("scheduled architecture identity has invalid version")
    if not _SHA256_RE.fullmatch(fingerprint):
        raise ValueError("scheduled architecture identity has invalid fingerprint")
    clean = {field: row.get(field) for field in _IDENTITY_FIELDS}
    clean["ticker"] = ticker
    clean["architecture_version"] = version
    clean["architecture_fingerprint"] = fingerprint
    analysts = clean.get("selected_analysts")
    clean["selected_analysts"] = (
        [str(item) for item in analysts[:8]]
        if isinstance(analysts, list)
        else []
    )
    return clean


def observe_active_architectures(
    identities: list[dict[str, Any]],
    *,
    evaluations: list[dict[str, Any]],
    terminal_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach current-run and mature-outcome coverage to safe identities.

    Raw run/evaluation rows remain immutable.  Matching always includes ticker,
    version, and fingerprint so a historical cohort cannot be presented as the
    architecture that the next natural schedule invocation will execute.
    """
    if len(identities) > MAX_ACTIVE_ARCHITECTURES:
        raise ValueError(
            f"active architecture inventory is limited to {MAX_ACTIVE_ARCHITECTURES} rows"
        )
    output: list[dict[str, Any]] = []
    for raw_identity in identities:
        identity = _validated_identity(raw_identity)
        key = (
            identity["ticker"],
            identity["architecture_version"],
            identity["architecture_fingerprint"],
        )

        def matches(row: Any) -> bool:
            return isinstance(row, dict) and (
                str(row.get("ticker") or "").strip().upper(),
                str(row.get("architecture_version") or "").strip(),
                str(row.get("architecture_fingerprint") or "").strip(),
            ) == key

        matched_runs = [row for row in terminal_runs if matches(row)]
        outcome_sample_count = sum(matches(row) for row in evaluations)
        validated_run_count = sum(
            str(row.get("decision_status") or "") == "validated"
            for row in matched_runs
        )
        attention_run_count = len(matched_runs) - validated_run_count
        if outcome_sample_count:
            status = "active_outcome_observed"
        elif validated_run_count:
            status = "awaiting_outcome_maturity"
        elif matched_runs:
            status = "active_run_requires_attention"
        else:
            status = "awaiting_first_active_run"
        if (
            outcome_sample_count
            >= DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES
        ):
            continuity_status = "minimum_outcome_sample_reached"
            continuity_action = "review_active_architecture_assessment"
        elif outcome_sample_count:
            continuity_status = "outcome_collection_in_progress"
            continuity_action = "continue_active_outcome_collection"
        elif not matched_runs:
            continuity_status = "awaiting_initial_run"
            continuity_action = (
                "collect_first_active_run_without_decision_changes"
            )
        elif not validated_run_count:
            continuity_status = "repair_before_measurement"
            continuity_action = "repair_active_run_before_experiment"
        else:
            continuity_status = "outcome_collection_in_progress"
            continuity_action = "hold_architecture_for_outcome_maturity"
        output.append(
            {
                **identity,
                "observation_schema": ACTIVE_ARCHITECTURE_OBSERVATION_SCHEMA,
                "active": True,
                "observation_status": status,
                "terminal_run_count": len(matched_runs),
                "validated_run_count": validated_run_count,
                "attention_run_count": attention_run_count,
                "outcome_sample_count": outcome_sample_count,
                "measurement_continuity": {
                    "schema": ARCHITECTURE_MEASUREMENT_CONTINUITY_SCHEMA,
                    "status": continuity_status,
                    "recommended_action": continuity_action,
                    "minimum_outcome_samples": (
                        DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES
                    ),
                    "measurement_continuity_recommended": (
                        outcome_sample_count
                        < DEFAULT_ARCHITECTURE_EVALUATION_MINIMUM_SAMPLES
                    ),
                    "safety_and_correctness_fixes_override_continuity": True,
                    "automatic_architecture_mutation_allowed": False,
                    "paired_shadow_authorization_required": True,
                },
                "automatic_architecture_mutation_allowed": False,
                "paired_shadow_authorization_required": True,
            }
        )
    return sorted(
        output,
        key=lambda row: (
            row["ticker"],
            row["architecture_version"],
            row["architecture_fingerprint"],
        ),
    )


def active_architecture_inventory_payload(
    inventory: dict[str, Any],
    *,
    evaluations: list[dict[str, Any]],
    terminal_runs: list[dict[str, Any]],
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return a bounded, observed copy of a scheduled inventory."""
    if not isinstance(inventory, dict):
        raise ValueError("scheduled architecture inventory must be an object")
    status = str(inventory.get("status") or "unavailable")
    ticker_scope = (
        ticker.strip().upper()
        if isinstance(ticker, str) and ticker.strip()
        else None
    )
    raw_identities = inventory.get("architectures")
    identities = raw_identities if isinstance(raw_identities, list) else []
    if ticker_scope:
        identities = [
            row
            for row in identities
            if isinstance(row, dict)
            and str(row.get("ticker") or "").strip().upper() == ticker_scope
        ]
    observed = (
        observe_active_architectures(
            identities,
            evaluations=evaluations,
            terminal_runs=terminal_runs,
        )
        if status == "loaded"
        else []
    )
    payload = {
        "schema": str(
            inventory.get("schema")
            or "tradingagents/scheduled-architecture-inventory/v1"
        ),
        "status": status,
        "schedule_enabled": inventory.get("schedule_enabled"),
        "paired_shadow_authorized": bool(
            inventory.get("paired_shadow_authorized")
        ),
        "ticker_scope": ticker_scope,
        "evaluation_rows_scanned": len(evaluations),
        "terminal_run_rows_scanned": len(terminal_runs),
        "architectures": observed,
    }
    experiment_plan = _validated_experiment_plan(inventory.get("experiment_plan"))
    experiment_pilot = _validated_experiment_pilot(
        inventory.get("experiment_pilot")
    )
    if experiment_plan is not None:
        payload["experiment_plan"] = experiment_plan
    if experiment_pilot is not None:
        payload["experiment_pilot"] = experiment_pilot
    if status == "unavailable" and inventory.get("error_type"):
        payload["error_type"] = str(inventory["error_type"])
    return payload
