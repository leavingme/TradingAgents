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
    assert rollup["schema"] == "tradingagents/architecture-run-cost-rollup/v1"
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
