import pytest

from tradingagents.evaluation import (
    architecture_rollups,
    compare_architectures,
    score_outcome,
)
from tradingagents.runtime.events import AnalysisEvent
from tradingagents.runtime.history import RunHistoryStore


def test_deterministic_direction_and_hold_scoring():
    assert score_outcome("Buy", 0.03)["directional_hit"] is True
    assert score_outcome("Sell", -0.03)["directional_hit"] is True
    assert score_outcome("Underweight", 0.03)["directional_hit"] is False
    assert score_outcome("Hold", 0.01)["directional_hit"] is True
    assert score_outcome("Hold", 0.04)["directional_hit"] is False


def test_history_persists_idempotent_architecture_evaluation(tmp_path):
    store = RunHistoryStore(tmp_path / "runs.db")
    store.create_run(
        "run-1", "NVDA", "2026-07-01", "stock", ["market"], "minimax-cn", 1,
        architecture_version="baseline",
    )
    store.mark_started("run-1", started_at="2026-07-01T20:00:00+00:00")
    store.add_event("run-1", AnalysisEvent(
        type="stats",
        run_id="run-1",
        content={"llm_calls": 10, "tool_calls": 20, "tokens_in": 1000, "tokens_out": 200},
    ))
    store.add_event("run-1", AnalysisEvent(
        type="stats",
        run_id="run-1",
        content={"llm_calls": 12, "tool_calls": 24, "tokens_in": 1200, "tokens_out": 240},
    ))
    store.mark_finished(
        "run-1", "completed", finished_at="2026-07-01T20:02:30+00:00"
    )
    record = {
        "run_id": "run-1",
        "horizon_sessions": 5,
        "evaluated_by_run_id": "run-2",
        "ticker": "NVDA",
        "analysis_date": "2026-07-01",
        "rating": "Buy",
        "benchmark": "SPY",
        "entry_date": "2026-07-01",
        "exit_date": "2026-07-08",
        "stock_entry_close": 100.0,
        "stock_exit_close": 105.0,
        "benchmark_entry_close": 500.0,
        "benchmark_exit_close": 510.0,
        "stock_entry_source_id": "ohlcv:test:stock-entry:2026-07-01",
        "stock_exit_source_id": "ohlcv:test:stock-exit:2026-07-08",
        "benchmark_entry_source_id": "ohlcv:test:bench-entry:2026-07-01",
        "benchmark_exit_source_id": "ohlcv:test:bench-exit:2026-07-08",
        "raw_return": 0.05,
        "benchmark_return": 0.02,
        "alpha_return": 0.03,
        "exposure": 1.0,
        "directional_hit": True,
        "score": 0.03,
        "architecture_version": "baseline",
        "evaluated_at": "2026-07-10T20:00:00+00:00",
    }
    store.add_decision_evaluation(record)
    store.add_decision_evaluation(record)
    rows = store.list_decision_evaluations(ticker="nvda")
    assert len(rows) == 1
    assert rows[0]["evaluated_by_run_id"] == "run-2"
    assert rows[0]["directional_hit"] == 1
    assert rows[0]["runtime_seconds"] == 150.0
    assert rows[0]["llm_calls"] == 12
    assert rows[0]["tool_calls"] == 24
    assert rows[0]["tokens_in"] == 1200
    assert rows[0]["tokens_out"] == 240
    lightweight = store.list_decision_evaluations(
        ticker="nvda",
        include_runtime_metrics=False,
    )
    assert "runtime_seconds" not in lightweight[0]
    assert "tokens_in" not in lightweight[0]

    store.create_run(
        "run-future", "NVDA", "2026-07-02", "stock", ["market"],
        "minimax-cn", 1, architecture_version="baseline",
    )
    store.add_decision_evaluation({
        **record,
        "run_id": "run-future",
        "analysis_date": "2026-07-02",
        "evaluated_at": "2026-07-20T16:00:00-04:00",
    })
    newest = store.list_decision_evaluations(
        ticker="NVDA",
        limit=1,
        include_runtime_metrics=False,
    )
    assert newest[0]["evaluated_at"] == "2026-07-20T20:00:00+00:00"
    cutoff_rows = store.list_decision_evaluations(
        ticker="NVDA",
        evaluated_before="2026-07-15T20:00:00+00:00",
        limit=1,
        include_runtime_metrics=False,
    )
    assert [row["run_id"] for row in cutoff_rows] == ["run-1"]
    assert store.list_decision_evaluations(
        exclude_ticker="NVDA",
        include_runtime_metrics=False,
    ) == []
    with pytest.raises(ValueError, match="timezone"):
        store.list_decision_evaluations(evaluated_before="2026-07-15")
    with pytest.raises(ValueError, match="mutually exclusive"):
        store.list_decision_evaluations(ticker="NVDA", exclude_ticker="AAPL")


def test_history_rejects_evaluation_without_exact_ohlcv_provenance(tmp_path):
    store = RunHistoryStore(tmp_path / "runs.db")
    store.create_run(
        "run-unsafe", "NVDA", "2026-07-01", "stock", ["market"],
        "minimax-cn", 1,
    )
    with pytest.raises(ValueError, match="lacks audited provenance"):
        store.add_decision_evaluation({
            "run_id": "run-unsafe",
            "horizon_sessions": 5,
            "ticker": "NVDA",
            "analysis_date": "2026-07-01",
            "rating": "Buy",
            "benchmark": "SPY",
            "raw_return": 0.05,
            "benchmark_return": 0.02,
            "alpha_return": 0.03,
            "exposure": 1.0,
            "directional_hit": True,
            "score": 0.03,
            "architecture_version": "baseline",
        })


def test_architecture_comparison_never_auto_promotes_sequential_cohorts():
    evaluations = []
    for version, score in (("baseline", 0.001), ("challenger", 0.01)):
        for index in range(20):
            evaluations.append({
                "architecture_version": version,
                "horizon_sessions": 5,
                "directional_hit": True,
                "raw_return": score,
                "alpha_return": score,
                "score": score,
            })
    rollups = architecture_rollups(evaluations)
    assert {row["sample_count"] for row in rollups} == {20}
    comparison = compare_architectures(
        evaluations, baseline="baseline", challenger="challenger"
    )
    assert comparison["passes_point_estimate"] is True
    assert comparison["passes_paired_gate"] is False
    assert comparison["status"] == "review_required"


def test_architecture_comparison_uses_same_day_shadow_pairs():
    evaluations = []
    for index in range(20):
        for version, score, hit in (
            ("baseline", 0.0, False),
            ("challenger", 0.01, True),
        ):
            evaluations.append({
                "run_id": f"{version}-{index}",
                "ticker": "NVDA",
                "analysis_date": f"2026-06-{index + 1:02d}",
                "architecture_version": version,
                "horizon_sessions": 5,
                "directional_hit": hit,
                "raw_return": 0.03,
                "benchmark_return": 0.01,
                "alpha_return": 0.02,
                "entry_date": f"2026-06-{index + 1:02d}",
                "exit_date": f"2026-07-{index + 1:02d}",
                "stock_entry_close": 100.0,
                "stock_exit_close": 103.0,
                "benchmark_entry_close": 500.0,
                "benchmark_exit_close": 505.0,
                "stock_entry_source_id": f"ohlcv:test:stock-entry:{index}",
                "stock_exit_source_id": f"ohlcv:test:stock-exit:{index}",
                "benchmark_entry_source_id": f"ohlcv:test:bench-entry:{index}",
                "benchmark_exit_source_id": f"ohlcv:test:bench-exit:{index}",
                "runtime_seconds": 100.0 if version == "baseline" else 80.0,
                "llm_calls": 10 if version == "baseline" else 8,
                "tool_calls": 20 if version == "baseline" else 18,
                "tokens_in": 1000 if version == "baseline" else 800,
                "tokens_out": 200 if version == "baseline" else 180,
                "score": score,
            })
    comparison = compare_architectures(
        evaluations, baseline="baseline", challenger="challenger"
    )
    assert comparison["status"] == "review_required"
    assert comparison["passes_paired_gate"] is True
    assert comparison["paired"]["sample_count"] == 20
    assert comparison["paired"]["lower_95_score_delta"] == 0.01
    assert comparison["paired"]["critical_value"] == 2.093
    assert comparison["baseline"]["mean_tokens_in"] == 1000.0
    assert comparison["challenger"]["mean_tokens_in"] == 800.0
    assert comparison["paired_costs"]["tokens_in"]["sample_count"] == 20
    assert comparison["paired_costs"]["tokens_in"]["mean_delta"] == -200.0
    assert comparison["paired_costs"]["tokens_in"]["mean_reduction"] == 200.0
    assert comparison["paired_costs"]["runtime_seconds"]["mean_reduction"] == 20.0


def test_architecture_comparison_rejects_mixed_configuration_fingerprints():
    evaluations = []
    for version in ("baseline", "challenger"):
        for index in range(20):
            evaluations.append({
                "ticker": "NVDA",
                "analysis_date": f"2026-06-{index + 1:02d}",
                "architecture_version": version,
                "architecture_fingerprint": (
                    f"{version}-changed" if version == "baseline" and index == 19
                    else f"{version}-stable"
                ),
                "horizon_sessions": 5,
                "directional_hit": True,
                "raw_return": 0.03,
                "alpha_return": 0.02,
                "score": 0.01,
            })
    comparison = compare_architectures(
        evaluations, baseline="baseline", challenger="challenger"
    )
    assert comparison["status"] == "invalid_comparison"


def test_architecture_rollups_do_not_merge_mixed_fingerprints():
    rows = [
        {
            "architecture_version": "candidate",
            "architecture_fingerprint": fingerprint,
            "horizon_sessions": 5,
            "directional_hit": True,
            "raw_return": score,
            "alpha_return": score,
            "score": score,
        }
        for fingerprint, score in (("fp-a", 0.01), ("fp-b", 0.02))
    ]
    rollups = architecture_rollups(rows)
    assert len(rollups) == 2
    assert {row["architecture_fingerprint"] for row in rollups} == {"fp-a", "fp-b"}


def test_architecture_pairing_requires_identical_ohlcv_provenance():
    evaluations = []
    for index in range(20):
        for version, score in (("baseline", 0.0), ("challenger", 0.01)):
            evaluations.append({
                "run_id": f"{version}-{index}",
                "ticker": "NVDA",
                "analysis_date": f"2026-06-{index + 1:02d}",
                "architecture_version": version,
                "architecture_fingerprint": f"{version}-fp",
                "horizon_sessions": 5,
                "directional_hit": version == "challenger",
                "raw_return": 0.03,
                "benchmark_return": 0.01,
                "alpha_return": 0.02,
                "entry_date": f"2026-06-{index + 1:02d}",
                "exit_date": f"2026-07-{index + 1:02d}",
                "stock_entry_close": 100.0,
                "stock_exit_close": 103.0,
                "benchmark_entry_close": 500.0,
                "benchmark_exit_close": 505.0,
                "stock_entry_source_id": f"ohlcv:test:stock-entry:{index}",
                "stock_exit_source_id": f"ohlcv:test:stock-exit:{index}",
                "benchmark_entry_source_id": f"ohlcv:test:bench-entry:{index}",
                "benchmark_exit_source_id": f"ohlcv:test:bench-exit:{index}",
                "score": score,
            })
    # Same prices are insufficient when one challenger used a different source.
    evaluations[-1]["benchmark_exit_source_id"] = "ohlcv:other:bench-exit:19"
    comparison = compare_architectures(
        evaluations, baseline="baseline", challenger="challenger"
    )
    assert comparison["paired"]["sample_count"] == 19
    assert comparison["paired"]["provenance_mismatches_excluded"] == 1
    assert comparison["paired_costs"]["tokens_in"]["sample_count"] == 0
    assert comparison["paired_costs"]["tokens_in"]["missing_pairs_excluded"] == 19
    assert comparison["passes_paired_gate"] is False


def test_architecture_pairing_uses_student_t_not_normal_lower_bound():
    evaluations = []
    deltas = [0.001 if index % 2 else 0.005 for index in range(20)]
    for index, delta in enumerate(deltas):
        for version, score in (("baseline", 0.0), ("challenger", delta)):
            evaluations.append({
                "ticker": "NVDA",
                "analysis_date": f"2026-05-{index + 1:02d}",
                "architecture_version": version,
                "architecture_fingerprint": f"{version}-fp",
                "horizon_sessions": 5,
                "directional_hit": True,
                "raw_return": 0.03,
                "benchmark_return": 0.01,
                "alpha_return": 0.02,
                "entry_date": f"2026-05-{index + 1:02d}",
                "exit_date": f"2026-06-{index + 1:02d}",
                "stock_entry_close": 100.0,
                "stock_exit_close": 103.0,
                "benchmark_entry_close": 500.0,
                "benchmark_exit_close": 505.0,
                "stock_entry_source_id": f"ohlcv:test:stock-entry:{index}",
                "stock_exit_source_id": f"ohlcv:test:stock-exit:{index}",
                "benchmark_entry_source_id": f"ohlcv:test:bench-entry:{index}",
                "benchmark_exit_source_id": f"ohlcv:test:bench-exit:{index}",
                "score": score,
            })
    comparison = compare_architectures(
        evaluations, baseline="baseline", challenger="challenger"
    )
    paired = comparison["paired"]
    normal_lower = paired["mean_score_delta"] - 1.96 * paired["standard_error"]
    assert paired["critical_value"] == 2.093
    assert paired["lower_95_score_delta"] < normal_lower
