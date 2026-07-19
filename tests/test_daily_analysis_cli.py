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


def _run_daily_cli(tmp_path: Path, command: str) -> tuple[dict, str]:
    workspace = Path(__file__).resolve().parents[1]
    schedule = _write_schedule(tmp_path)
    missing_web_config = tmp_path / "missing-web-config.json"
    environment = os.environ.copy()
    environment["TRADINGAGENTS_DB"] = str(tmp_path / "runs.db")
    extra_args = ["--ticker", "NVDA"] if command == "evaluate" else []
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
