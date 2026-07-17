from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tradingagents.automation.daily import (
    DailySchedule,
    ScheduledTarget,
    load_runtime_preferences,
    run_due_analyses,
)
from tradingagents.runtime.history import RunHistoryStore


def _schedule() -> DailySchedule:
    return DailySchedule(
        enabled=True,
        targets=(
            ScheduledTarget(
                symbol="NVDA",
                timezone="America/New_York",
                run_after=datetime.strptime("16:30", "%H:%M").time(),
            ),
        ),
    )


def test_target_due_uses_exchange_local_time():
    target = _schedule().targets[0]
    before = datetime(2026, 7, 17, 16, 29, tzinfo=ZoneInfo("America/New_York"))
    after = datetime(2026, 7, 17, 16, 30, tzinfo=ZoneInfo("America/New_York"))
    assert target.is_due(before) is False
    assert target.is_due(after) is True


def test_schedule_rejects_duplicate_symbols():
    target = {
        "symbol": "NVDA",
        "timezone": "America/New_York",
        "run_after": "16:30",
    }
    with pytest.raises(ValueError, match="duplicate"):
        DailySchedule.from_dict({"enabled": True, "targets": [target, target]})


def test_schedule_allows_paired_shadow_versions_for_same_symbol():
    common = {
        "symbol": "NVDA",
        "timezone": "America/New_York",
        "run_after": "16:30",
    }
    schedule = DailySchedule.from_dict({
        "enabled": True,
        "targets": [
            {**common, "architecture_version": "baseline"},
            {
                **common,
                "architecture_version": "challenger",
                "longitudinal_context_mode": "research_and_portfolio",
            },
        ],
    })
    assert [target.architecture_version for target in schedule.targets] == [
        "baseline", "challenger"
    ]


def test_runtime_preferences_reuse_server_models_and_vendor_order(tmp_path):
    path = tmp_path / "web.json"
    path.write_text(
        json.dumps(
            {
                "settings": {
                    "llm_provider": "minimax-cn",
                    "quick_think_llm": "MiniMax-M3",
                    "deep_think_llm": "MiniMax-M3",
                    "ignored_secret": "must-not-load",
                },
                "providers": {
                    "news_data": [
                        {"id": "longbridge_mcp", "enabled": True},
                        {"id": "duckduckgo", "enabled": False},
                    ],
                    "unknown_category": [{"id": "shell", "enabled": True}],
                    "social_data": [{"id": "unknown_vendor", "enabled": True}],
                },
            }
        ),
        encoding="utf-8",
    )
    result = load_runtime_preferences(path)
    assert result["llm_provider"] == "minimax-cn"
    assert result["quick_think_llm"] == "MiniMax-M3"
    assert "ignored_secret" not in result
    vendors = result["config_overrides"]["data_vendors"]
    assert vendors["news_data"] == "longbridge_mcp"
    assert "unknown_category" not in vendors
    assert all("shell" not in chain for chain in vendors.values())


def test_runtime_preferences_apply_same_legacy_migration_as_web(tmp_path):
    path = tmp_path / "web.json"
    path.write_text(json.dumps({
        "settings": {},
        "providers": {
            "social_data": [
                {"id": "bird", "enabled": True},
                {"id": "reddit", "enabled": True},
            ]
        },
    }), encoding="utf-8")
    result = load_runtime_preferences(path)
    assert result["config_overrides"]["data_vendors"]["social_data"] == (
        "bird, stocktwits_browser, reddit"
    )


def test_due_run_reuses_preferences_and_is_idempotent(tmp_path, monkeypatch):
    store = RunHistoryStore(tmp_path / "runs.db")
    captured = []

    def execute(request):
        captured.append(request)
        store.create_run(
            request.run_id,
            request.ticker,
            request.analysis_date,
            request.asset_type,
            request.selected_analysts,
            request.llm_provider,
                request.research_depth,
                architecture_version=request.architecture_version,
        )
        store.mark_finished(request.run_id, "completed")
        return SimpleNamespace(
            run_id=request.run_id,
            decision_status="validated",
            report_path=Path("report.md"),
        )

    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )
    now = datetime(2026, 7, 17, 16, 45, tzinfo=ZoneInfo("America/New_York"))
    preferences = {
        "llm_provider": "minimax-cn",
        "quick_think_llm": "MiniMax-M3",
        "deep_think_llm": "MiniMax-M3",
        "research_depth": 1,
    }
    first = run_due_analyses(
        _schedule(),
        now=now,
        store=store,
        preferences=preferences,
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )
    second = run_due_analyses(
        _schedule(),
        now=now,
        store=store,
        preferences=preferences,
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )
    assert first[0]["status"] == "completed"
    assert second[0]["status"] == "already_recorded"
    assert len(captured) == 1
    assert captured[0].llm_provider == "minimax-cn"
    assert captured[0].quick_think_llm == "MiniMax-M3"


def test_dry_run_does_not_create_history(tmp_path, monkeypatch):
    store = RunHistoryStore(tmp_path / "runs.db")
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )
    result = run_due_analyses(
        _schedule(),
        now=datetime(2026, 7, 17, 17, 0, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={"llm_provider": "minimax-cn"},
        dry_run=True,
        lock_path=tmp_path / "missing-parent" / "daily.lock",
    )
    assert result[0]["status"] == "would_run"
    assert store.list_runs() == []
    assert not (tmp_path / "missing-parent").exists()


def test_failed_run_retries_only_after_delay_and_stops_at_bound(tmp_path, monkeypatch):
    store = RunHistoryStore(tmp_path / "runs.db")
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )
    store.create_run(
        "failed-1", "NVDA", "2026-07-17", "stock", ["market"], "minimax-cn", 1,
        status="failed", created_at="2026-07-17T20:35:00+00:00",
        architecture_version=_schedule().targets[0].architecture_version,
    )
    store.mark_finished("failed-1", "failed", finished_at="2026-07-17T20:40:00+00:00")
    schedule = DailySchedule(
        enabled=True,
        targets=_schedule().targets,
        max_attempts_per_date=2,
        retry_after_minutes=60,
    )
    wait = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 17, 0, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=lambda request: None,
        lock_path=tmp_path / "daily.lock",
    )
    assert wait[0]["status"] == "retry_wait"

    def fail_again(request):
        store.create_run(
            request.run_id,
            request.ticker,
            request.analysis_date,
            request.asset_type,
            request.selected_analysts,
            request.llm_provider,
            request.research_depth,
            status="failed",
            created_at="2026-07-17T22:00:00+00:00",
            architecture_version=request.architecture_version,
        )
        store.mark_finished(request.run_id, "failed", finished_at="2026-07-17T22:01:00+00:00")
        raise RuntimeError("transient")

    retry = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 18, 0, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=fail_again,
        lock_path=tmp_path / "daily.lock",
    )
    assert retry[0]["status"] == "failed"
    exhausted = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 20, 0, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=lambda request: None,
        lock_path=tmp_path / "daily.lock",
    )
    assert exhausted[0]["status"] == "attempts_exhausted"


def test_stale_active_run_allows_one_bounded_recovery(tmp_path, monkeypatch):
    store = RunHistoryStore(tmp_path / "runs.db")
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )
    store.create_run(
        "stale-run", "NVDA", "2026-07-17", "stock", ["market"], "minimax-cn", 1,
        status="running", created_at="2026-07-17T12:00:00+00:00",
        architecture_version=_schedule().targets[0].architecture_version,
    )
    store.mark_started("stale-run", started_at="2026-07-17T12:01:00+00:00")
    captured = []

    def recover(request):
        captured.append(request.run_id)
        return SimpleNamespace(
            run_id=request.run_id,
            decision_status="validated",
            report_path=None,
        )

    outcome = run_due_analyses(
        _schedule(),
        now=datetime(2026, 7, 17, 18, 30, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=recover,
        lock_path=tmp_path / "daily.lock",
    )
    assert outcome[0]["status"] == "completed"
    assert len(captured) == 1
