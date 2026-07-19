import pytest

from tradingagents.evaluation import (
    architecture_run_cost_rollups,
    attach_operator_cost_metrics,
    load_operator_run_costs,
)


class FakeStore:
    def __init__(self):
        self.calls = []

    def get_run(self, run_id):
        self.calls.append(run_id)
        if run_id == "missing":
            return None
        return {
            "events": [{
                "type": "stats",
                "content": {
                    "by_tool": {
                        "get_news": {
                            "tool_calls": 2,
                            "input_chars": 20,
                            "output_chars": 80000,
                            "errors": 0,
                            "by_agent": {"News Analyst": {"result": "secret"}},
                        },
                        "attacker-tool": {
                            "tool_calls": 1,
                            "input_chars": 1,
                            "output_chars": 999999,
                            "errors": 0,
                            "payload": "credential=sentinel-secret",
                        },
                    },
                },
            }],
        }


def test_operator_cost_enrichment_is_sanitized_cached_and_non_mutating():
    evaluations = [
        {"run_id": "shared", "score": 0.01},
        {"run_id": "shared", "score": 0.02},
        {"run_id": "missing", "score": 0.03},
        {"score": 0.04},
    ]
    store = FakeStore()

    enriched = attach_operator_cost_metrics(evaluations, store=store)

    assert evaluations[0] == {"run_id": "shared", "score": 0.01}
    assert store.calls == ["shared", "missing"]
    assert enriched[0]["tool_context_status"] == "observed"
    assert enriched[0]["tool_context"] == {
        "get_news": {
            "tool_calls": 2,
            "input_chars": 20,
            "output_chars": 80000,
            "errors": 0,
        },
    }
    assert enriched[1]["tool_context"] == enriched[0]["tool_context"]
    assert enriched[2]["tool_context_status"] == "not_observed"
    assert enriched[3]["tool_context_status"] == "not_observed"
    assert "sentinel-secret" not in str(enriched)
    assert "attacker-tool" not in str(enriched)


def test_operator_cost_enrichment_rejects_unbounded_queries():
    with pytest.raises(ValueError, match="limited to 5000 rows"):
        attach_operator_cost_metrics(
            [{"run_id": "same"}] * 5001,
            store=FakeStore(),
        )


class RunCostStore:
    def __init__(self):
        self.rows = [
            {
                "run_id": "run-1",
                "ticker": "NVDA",
                "analysis_date": "2026-07-17",
                "status": "completed",
                "decision_status": "validated",
                "architecture_version": "production",
                "architecture_fingerprint": "fp",
                "started_at": "2026-07-17T20:00:00+00:00",
                "finished_at": "2026-07-17T20:02:00+00:00",
            },
            {
                "run_id": "run-2",
                "ticker": "NVDA",
                "analysis_date": "2026-07-18",
                "status": "review_required",
                "decision_status": "review_required",
                "architecture_version": "production",
                "architecture_fingerprint": "fp",
                "started_at": "2026-07-18T20:00:00+00:00",
                "finished_at": "2026-07-18T20:03:00+00:00",
            },
            {
                "run_id": "running",
                "ticker": "NVDA",
                "status": "running",
                "architecture_version": "production",
                "architecture_fingerprint": "fp",
            },
            {
                "run_id": "other",
                "ticker": "AAPL",
                "status": "completed",
                "architecture_version": "production",
                "architecture_fingerprint": "fp",
            },
        ]

    def list_runs(self, limit):
        assert limit == 5000
        return self.rows

    def get_run(self, run_id):
        index = 1 if run_id == "run-1" else 2
        return {
            "events": [{
                "type": "stats",
                "content": {
                    "llm_calls": 10 + index,
                    "tool_calls": 20 + index,
                    "tokens_in": 1000 * index,
                    "tokens_out": 100 * index,
                    "by_agent": {
                        "News Analyst": {
                            "llm_calls": 2,
                            "tool_calls": 3,
                            "tokens_in": 700 * index,
                            "tokens_out": 70 * index,
                        },
                    },
                    "by_tool": {
                        "get_news": {
                            "tool_calls": 2,
                            "input_chars": 20,
                            "output_chars": 40000 * index,
                            "errors": 0,
                        },
                    },
                },
            }],
        }


def test_run_cost_rollups_use_terminal_runs_before_outcome_maturity():
    rows = load_operator_run_costs(store=RunCostStore(), ticker="nvda")
    assert [row["run_id"] for row in rows] == ["run-1", "run-2"]

    rollup = architecture_run_cost_rollups(rows)[0]
    assert rollup["schema"] == "tradingagents/architecture-run-cost-rollup/v2"
    assert rollup["ticker"] == "NVDA"
    assert rollup["sample_count"] == 2
    assert rollup["stats_observed_count"] == 2
    assert rollup["run_status_counts"] == {
        "completed": 1,
        "review_required": 1,
    }
    assert rollup["mean_runtime_seconds"] == 150.0
    assert rollup["mean_tokens_in"] == 1500.0
    assert rollup["agent_hotspots"] == [{
        "agent": "News Analyst",
        "mean_tokens_in": 1050.0,
        "sample_count": 2,
    }]
    assert rollup["tool_context_hotspots"] == [{
        "tool": "get_news",
        "mean_output_chars": 60000.0,
        "sample_count": 2,
    }]
    assert rollup["rolling_cost_monitoring"]["distinct_analysis_date_count"] == 2
    assert rollup["rolling_cost_monitoring"]["windows"]["5"]["status"] == (
        "insufficient_history"
    )
    assert rollup["cost_assessment"] == {
        "schema": "tradingagents/run-cost-assessment/v1",
        "status": "insufficient_cost_history",
        "recommended_action": "continue_cost_collection",
        "automatic_architecture_mutation_allowed": False,
        "outcome_claim_allowed": False,
        "promotion_gate_effect": "none",
        "minimum_analysis_dates": 5,
        "sample_count": 2,
        "distinct_analysis_date_count": 2,
        "stats_observed_count": 2,
        "input_token_observed_count": 2,
        "adverse_run_count": 1,
        "high_context_token_threshold": 150000,
        "high_context_run_count": 0,
        "recent_mean_daily_tokens_in_delta": None,
        "recent_mean_daily_tokens_in_ratio": None,
    }


def test_retryable_outcome_settlement_probe_cost_remains_operator_visible():
    class SettlementProbeStore:
        def list_runs(self, limit):
            return [{
                "run_id": "settlement-probe",
                "ticker": "NVDA",
                "analysis_date": "2026-07-17",
                "status": "outcome_settlement_pending",
                "architecture_version": "production",
                "architecture_fingerprint": "fp",
                "started_at": "2026-07-17T20:00:00+00:00",
                "finished_at": "2026-07-17T20:00:03+00:00",
            }]

        def get_run(self, run_id):
            return {
                "events": [{
                    "type": "stats",
                    "content": {
                        "llm_calls": 0,
                        "tool_calls": 0,
                        "tokens_in": 0,
                        "tokens_out": 0,
                    },
                }],
            }

    rows = load_operator_run_costs(store=SettlementProbeStore(), ticker="NVDA")

    assert len(rows) == 1
    assert rows[0]["status"] == "outcome_settlement_pending"
    assert rows[0]["llm_calls"] == 0
    assert rows[0]["tokens_in"] == 0


def _cost_row(
    ticker,
    analysis_date,
    tokens_in,
    *,
    status="completed",
    runtime_cost_status="observed",
):
    return {
        "run_id": f"{ticker}-{analysis_date}-{tokens_in}",
        "ticker": ticker,
        "analysis_date": analysis_date,
        "status": status,
        "decision_status": "validated" if status == "completed" else status,
        "architecture_version": "production",
        "architecture_fingerprint": "shared-fingerprint",
        "runtime_cost_status": runtime_cost_status,
        "tokens_in": tokens_in,
        "runtime_seconds": tokens_in / 1000,
    }


def test_run_cost_rollups_isolate_tickers_with_same_architecture_identity():
    rollups = architecture_run_cost_rollups([
        _cost_row("NVDA", "2026-07-01", 100_000),
        _cost_row("AAPL", "2026-07-01", 80_000),
    ])

    assert [(row["ticker"], row["sample_count"]) for row in rollups] == [
        ("AAPL", 1),
        ("NVDA", 1),
    ]
    assert [row["mean_tokens_in"] for row in rollups] == [80_000, 100_000]


def test_rolling_cost_monitoring_sums_retries_before_comparing_date_windows():
    rows = [
        _cost_row("NVDA", f"2026-07-{day:02d}", 100_000)
        for day in range(1, 6)
    ]
    rows.extend(
        _cost_row("NVDA", f"2026-07-{day:02d}", 130_000)
        for day in range(6, 11)
    )
    rows.append(_cost_row("NVDA", "2026-07-10", 20_000))

    rollup = architecture_run_cost_rollups(rows)[0]
    monitoring = rollup["rolling_cost_monitoring"]
    window = monitoring["windows"]["5"]

    assert rollup["sample_count"] == 11
    assert monitoring["schema"] == (
        "tradingagents/rolling-run-cost-monitoring/v1"
    )
    assert monitoring["distinct_analysis_date_count"] == 10
    assert monitoring["multi_run_analysis_date_count"] == 1
    assert window["status"] == "comparison_ready"
    assert window["previous"]["run_count"] == 5
    assert window["current"]["run_count"] == 6
    assert window["previous"]["mean_daily_tokens_in"] == 100_000
    assert window["current"]["mean_daily_tokens_in"] == 134_000
    assert window["current_minus_previous"]["mean_daily_tokens_in"] == 34_000
    assert window["current_minus_previous"]["mean_daily_tokens_in_ratio"] == 0.34
    assert rollup["cost_assessment"]["status"] == (
        "recent_cost_increase_observed"
    )
    assert rollup["cost_assessment"]["recommended_action"] == (
        "investigate_recent_cost_increase"
    )
    assert rollup["cost_assessment"]["promotion_gate_effect"] == "none"


def test_cost_assessment_fails_closed_when_any_run_lacks_stats():
    rows = [
        _cost_row("NVDA", f"2026-07-{day:02d}", 100_000)
        for day in range(1, 6)
    ]
    rows[-1].pop("tokens_in")
    rows[-1]["runtime_cost_status"] = "not_observed"

    rollup = architecture_run_cost_rollups(rows)[0]

    assert rollup["stats_observed_count"] == 4
    assert rollup["rolling_cost_monitoring"]["windows"]["5"]["status"] == (
        "insufficient_history"
    )
    assert rollup["cost_assessment"]["status"] == (
        "incomplete_cost_observability"
    )
    assert rollup["cost_assessment"]["recommended_action"] == (
        "repair_cost_observability"
    )


def test_cost_assessment_requires_input_tokens_even_when_stats_event_exists():
    rows = [
        _cost_row("NVDA", f"2026-07-{day:02d}", 100_000)
        for day in range(1, 6)
    ]
    rows[-1].pop("tokens_in")

    assessment = architecture_run_cost_rollups(rows)[0]["cost_assessment"]

    assert assessment["stats_observed_count"] == 5
    assert assessment["input_token_observed_count"] == 4
    assert assessment["status"] == "incomplete_cost_observability"


@pytest.mark.parametrize(
    ("last_status", "expected_status", "expected_action"),
    [
        ("completed", "cost_baseline_ready", "monitor_cost_and_design_challenger"),
        (
            "review_required",
            "reliability_attention_required",
            "investigate_run_reliability",
        ),
    ],
)
def test_cost_assessment_distinguishes_ready_baseline_from_reliability_issue(
    last_status,
    expected_status,
    expected_action,
):
    rows = [
        _cost_row("NVDA", f"2026-07-{day:02d}", 100_000)
        for day in range(1, 6)
    ]
    rows[-1]["status"] = last_status

    assessment = architecture_run_cost_rollups(rows)[0]["cost_assessment"]

    assert assessment["status"] == expected_status
    assert assessment["recommended_action"] == expected_action
    assert assessment["automatic_architecture_mutation_allowed"] is False
    assert assessment["outcome_claim_allowed"] is False
