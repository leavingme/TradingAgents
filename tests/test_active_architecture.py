import pytest

from tradingagents.evaluation import (
    active_architecture_inventory_payload,
    observe_active_architectures,
)


def _identity(ticker="NVDA", version="production", fingerprint="a" * 64):
    return {
        "schema": "tradingagents/scheduled-architecture-identity/v1",
        "ticker": ticker,
        "asset_type": "stock",
        "architecture_version": version,
        "architecture_fingerprint": fingerprint,
        "architecture_manifest_schema": (
            "tradingagents/agent-architecture-manifest/v4"
        ),
        "selected_analysts": ["market", "news"],
        "research_depth": 1,
        "llm_provider": "minimax-cn",
        "quick_think_llm": "MiniMax-M3",
        "deep_think_llm": "MiniMax-M3",
        "longitudinal_context_mode": "research_and_portfolio",
        "secret": "must-not-survive",
    }


@pytest.mark.parametrize(
    (
        "runs",
        "evaluations",
        "expected_status",
        "continuity_status",
        "continuity_action",
    ),
    [
        (
            [],
            [],
            "awaiting_first_active_run",
            "awaiting_initial_run",
            "collect_first_active_run_without_decision_changes",
        ),
        (
            [{"status": "review_required", "decision_status": "review_required"}],
            [],
            "active_run_requires_attention",
            "repair_before_measurement",
            "repair_active_run_before_experiment",
        ),
        (
            [{"status": "completed", "decision_status": "validated"}],
            [],
            "awaiting_outcome_maturity",
            "outcome_collection_in_progress",
            "hold_architecture_for_outcome_maturity",
        ),
        (
            [{"status": "completed", "decision_status": "validated"}],
            [{"score": 0.01}],
            "active_outcome_observed",
            "outcome_collection_in_progress",
            "continue_active_outcome_collection",
        ),
        (
            [],
            [{"score": 0.01}],
            "active_outcome_observed",
            "outcome_collection_in_progress",
            "continue_active_outcome_collection",
        ),
    ],
)
def test_active_architecture_observation_states(
    runs,
    evaluations,
    expected_status,
    continuity_status,
    continuity_action,
):
    identity = _identity()
    key = {
        "ticker": "NVDA",
        "architecture_version": "production",
        "architecture_fingerprint": "a" * 64,
    }
    terminal_rows = [{**key, **row} for row in runs]
    outcome_rows = [{**key, **row} for row in evaluations]

    observed = observe_active_architectures(
        [identity],
        evaluations=outcome_rows,
        terminal_runs=terminal_rows,
    )[0]

    assert observed["observation_status"] == expected_status
    assert observed["terminal_run_count"] == len(runs)
    assert observed["outcome_sample_count"] == len(evaluations)
    continuity = observed["measurement_continuity"]
    assert continuity["status"] == continuity_status
    assert continuity["recommended_action"] == continuity_action
    assert continuity["minimum_outcome_samples"] == 20
    assert continuity["measurement_continuity_recommended"] is True
    assert continuity["safety_and_correctness_fixes_override_continuity"] is True
    assert continuity["automatic_architecture_mutation_allowed"] is False
    assert continuity["paired_shadow_authorization_required"] is True
    assert observed["automatic_architecture_mutation_allowed"] is False
    assert observed["paired_shadow_authorization_required"] is True
    assert "secret" not in observed
    assert identity["secret"] == "must-not-survive"


def test_active_architecture_reaches_review_only_after_minimum_outcomes():
    identity = _identity()
    key = {
        "ticker": "NVDA",
        "architecture_version": "production",
        "architecture_fingerprint": "a" * 64,
    }
    observed = observe_active_architectures(
        [identity],
        evaluations=[{**key, "score": 0.01} for _ in range(20)],
        terminal_runs=[
            {**key, "status": "completed", "decision_status": "validated"}
        ],
    )[0]

    continuity = observed["measurement_continuity"]
    assert continuity["status"] == "minimum_outcome_sample_reached"
    assert continuity["recommended_action"] == (
        "review_active_architecture_assessment"
    )
    assert continuity["measurement_continuity_recommended"] is False
    assert continuity["safety_and_correctness_fixes_override_continuity"] is True
    assert continuity["automatic_architecture_mutation_allowed"] is False


def test_active_architecture_matching_requires_ticker_version_and_fingerprint():
    key = {
        "architecture_version": "production",
        "architecture_fingerprint": "a" * 64,
        "status": "completed",
        "decision_status": "validated",
    }
    observed = observe_active_architectures(
        [_identity("NVDA"), _identity("AAPL")],
        evaluations=[{"ticker": "AAPL", **key}],
        terminal_runs=[
            {"ticker": "AAPL", **key},
            {"ticker": "NVDA", **key, "architecture_fingerprint": "b" * 64},
        ],
    )

    assert [(row["ticker"], row["observation_status"]) for row in observed] == [
        ("AAPL", "active_outcome_observed"),
        ("NVDA", "awaiting_first_active_run"),
    ]


def test_active_architecture_inventory_is_bounded_and_validated():
    with pytest.raises(ValueError, match="limited to 128"):
        observe_active_architectures(
            [_identity()] * 129,
            evaluations=[],
            terminal_runs=[],
        )
    invalid = _identity()
    invalid["architecture_fingerprint"] = "not-a-sha256"
    with pytest.raises(ValueError, match="invalid fingerprint"):
        observe_active_architectures(
            [invalid],
            evaluations=[],
            terminal_runs=[],
        )


def test_active_inventory_payload_filters_ticker_before_observation():
    inventory = {
        "schema": "tradingagents/scheduled-architecture-inventory/v1",
        "status": "loaded",
        "schedule_enabled": True,
        "paired_shadow_authorized": False,
        "architectures": [_identity("NVDA"), _identity("AAPL")],
    }

    payload = active_architecture_inventory_payload(
        inventory,
        evaluations=[],
        terminal_runs=[],
        ticker="nvda",
    )

    assert payload["ticker_scope"] == "NVDA"
    assert payload["evaluation_rows_scanned"] == 0
    assert payload["terminal_run_rows_scanned"] == 0
    assert [row["ticker"] for row in payload["architectures"]] == ["NVDA"]


def test_unavailable_active_inventory_exposes_only_error_type():
    payload = active_architecture_inventory_payload(
        {
            "status": "unavailable",
            "error_type": "FileNotFoundError",
            "detail": "/secret/path/schedule.json",
        },
        evaluations=[],
        terminal_runs=[],
    )

    assert payload["status"] == "unavailable"
    assert payload["architectures"] == []
    assert payload["error_type"] == "FileNotFoundError"
    assert "/secret/path" not in str(payload)
