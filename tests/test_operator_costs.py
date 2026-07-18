import pytest

from tradingagents.evaluation import attach_operator_cost_metrics


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
