from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _write_schedule(tmp_path: Path) -> Path:
    path = tmp_path / "daily-schedule.json"
    path.write_text(
        json.dumps({
            "enabled": True,
            "paired_shadow_authorized": False,
            "targets": [{
                "symbol": "NVDA",
                "asset_type": "stock",
                "timezone": "America/New_York",
                "run_after": "16:30",
                "architecture_version": "production",
                "longitudinal_context_mode": "research_and_portfolio",
                "weekdays": [0, 1, 2, 3, 4],
                "selected_analysts": [
                    "market",
                    "social",
                    "news",
                    "fundamentals",
                ],
            }],
        }),
        encoding="utf-8",
    )
    return path


def _run_daily_cli(
    tmp_path: Path,
    command: str,
    *command_args: str,
) -> tuple[dict, str]:
    workspace = Path(__file__).resolve().parents[1]
    schedule = _write_schedule(tmp_path)
    missing_web_config = tmp_path / "missing-web-config.json"
    environment = os.environ.copy()
    environment["TRADINGAGENTS_DB"] = str(tmp_path / "runs.db")
    extra_args = ["--ticker", "NVDA"] if command == "evaluate" else []
    extra_args.extend(command_args)
    completed = subprocess.run(
        [
            sys.executable,
            str(workspace / "scripts/daily_analysis.py"),
            command,
            "--config",
            str(schedule),
            "--web-config",
            str(missing_web_config),
            *extra_args,
        ],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout), completed.stdout


def test_daily_status_always_exposes_safe_active_architecture_identity(tmp_path):
    payload, serialized = _run_daily_cli(tmp_path, "status")

    assert payload["outcome_settlement_retry_after_minutes"] == 15
    assert payload["outcome_settlement_max_wait_minutes"] == 240
    inventory = payload["active_architecture_inventory"]
    assert inventory["status"] == "loaded"
    assert inventory["schedule_enabled"] is True
    assert inventory["paired_shadow_authorized"] is False
    assert len(inventory["architectures"]) == 1
    identity = inventory["architectures"][0]
    assert identity["ticker"] == "NVDA"
    assert identity["architecture_version"] == "production"
    assert len(identity["architecture_fingerprint"]) == 64
    assert identity["research_depth"] == 1
    assert identity["llm_provider"] == "minimax-cn"
    assert str(tmp_path) not in serialized
    assert "backend_url" not in serialized


def test_daily_evaluate_observes_active_identity_without_runs_or_outcomes(tmp_path):
    payload, serialized = _run_daily_cli(tmp_path, "evaluate")

    assert payload["evaluation_count"] == 0
    assert payload["run_cost_sample_count"] == 0
    active = payload["active_architecture_inventory"]["architectures"][0]
    assert active["observation_status"] == "awaiting_first_active_run"
    assert active["terminal_run_count"] == 0
    assert active["outcome_sample_count"] == 0
    assert active["measurement_continuity"] == {
        "schema": "tradingagents/architecture-measurement-continuity/v1",
        "status": "awaiting_initial_run",
        "recommended_action": (
            "collect_first_active_run_without_decision_changes"
        ),
        "minimum_outcome_samples": 20,
        "measurement_continuity_recommended": True,
        "safety_and_correctness_fixes_override_continuity": True,
        "automatic_architecture_mutation_allowed": False,
        "paired_shadow_authorization_required": True,
    }
    assert active["automatic_architecture_mutation_allowed"] is False
    assert active["paired_shadow_authorization_required"] is True
    assert str(tmp_path) not in serialized


def test_daily_evaluate_selects_registered_experiment_plan(tmp_path):
    plan_fingerprint = "a" * 64
    payload, _ = _run_daily_cli(
        tmp_path,
        "evaluate",
        "--baseline",
        "baseline",
        "--challenger",
        "challenger",
        "--experiment-plan-fingerprint",
        plan_fingerprint,
    )

    assert payload["comparison"]["selected_experiment_plan_fingerprint"] == (
        plan_fingerprint
    )
    assert payload["comparison"]["status"] == "insufficient_data"


def test_daily_evaluate_distinguishes_invalid_history_from_maturing_outcome(
    tmp_path,
):
    from tradingagents.runtime.events import AnalysisEvent
    from tradingagents.runtime.history import RunHistoryStore

    store = RunHistoryStore(tmp_path / "runs.db")
    store.create_run(
        "blocked-outcome",
        "NVDA",
        "2026-07-01",
        "stock",
        ["market"],
        "minimax-cn",
        1,
    )
    store.add_event("blocked-outcome", AnalysisEvent(
        type="run_completed",
        run_id="blocked-outcome",
        timestamp="2026-07-01T21:00:00+00:00",
        content={"decision_status": "validated"},
    ))
    store.record_decision_evaluation_issue(
        "blocked-outcome",
        horizon_sessions=5,
        issue_code="validated_decision_missing",
        detected_by_run_id="auditor-run",
    )
    for run_id in ("claimed-outcome", "settler-run"):
        store.create_run(
            run_id,
            "NVDA",
            "2026-07-02",
            "stock",
            ["market"],
            "minimax-cn",
            1,
        )
    store.add_event("claimed-outcome", AnalysisEvent(
        type="run_completed",
        run_id="claimed-outcome",
        timestamp="2026-07-02T21:00:00+00:00",
        content={
            "decision": "Rating: Hold",
            "decision_status": "validated",
            "decision_as_of": "2026-07-02T21:00:00+00:00",
        },
    ))
    assert store.claim_decision_evaluation(
        "claimed-outcome",
        horizon_sessions=5,
        claimed_by_run_id="settler-run",
    ) == "claimed"
    store.create_run(
        "failed-outcome",
        "NVDA",
        "2026-07-03",
        "stock",
        ["market"],
        "minimax-cn",
        1,
    )
    store.add_event("failed-outcome", AnalysisEvent(
        type="run_completed",
        run_id="failed-outcome",
        timestamp="2026-07-03T21:00:00+00:00",
        content={
            "decision": "Rating: Buy",
            "decision_status": "validated",
            "decision_as_of": "2026-07-03T21:00:00+00:00",
        },
    ))
    store.record_decision_evaluation_failure(
        "failed-outcome",
        horizon_sessions=5,
        failure_code="ohlcv_unavailable",
        failed_by_run_id="settler-run",
    )

    payload, serialized = _run_daily_cli(tmp_path, "evaluate")

    assert payload["pending_evaluation_count"] == 3
    assert payload["blocked_evaluation_count"] == 1
    assert payload["in_progress_evaluation_count"] == 1
    assert payload["failed_evaluation_count"] == 1
    pending_by_status = {
        row["status"]: row for row in payload["pending_evaluations"]
    }
    assert pending_by_status["blocked_invalid_history"][
        "settlement_issue_code"
    ] == (
        "validated_decision_missing"
    )
    assert pending_by_status["settlement_in_progress"][
        "settlement_claimed_by_run_id"
    ] == "settler-run"
    assert pending_by_status["settlement_in_progress"][
        "settlement_claim_expires_at"
    ]
    assert pending_by_status["retryable_settlement_failure"][
        "settlement_failure_code"
    ] == "ohlcv_unavailable"
    assert pending_by_status["retryable_settlement_failure"][
        "settlement_failure_count"
    ] == 1
    assert "auditor-run" not in serialized
