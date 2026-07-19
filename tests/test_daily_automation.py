from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from tradingagents.automation.daily import (
    ARCHITECTURE_EVALUATION_SCAN_LIMIT,
    ARCHITECTURE_EVALUATION_STATUS_SCHEMA,
    DailySchedule,
    ScheduledTarget,
    _architecture_evaluation_status,
    _context_cost_diagnostic,
    _record_architecture_evaluation_status,
    load_runtime_preferences,
    load_scheduled_architecture_inventory,
    run_due_analyses,
    scheduled_architecture_identity,
    scheduler_exit_code,
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


def test_systemd_assets_preserve_long_run_and_persistent_timer_contract():
    workspace = Path(__file__).resolve().parents[1]
    service = (workspace / "deploy/systemd/tradingagents-daily.service").read_text(
        encoding="utf-8"
    )
    timer = (workspace / "deploy/systemd/tradingagents-daily.timer").read_text(
        encoding="utf-8"
    )

    assert "Type=oneshot" in service
    assert "TimeoutStartSec=infinity" in service
    assert "scripts/daily_analysis.py run" in service
    assert "OnCalendar=*:0/15" in timer
    assert "Persistent=true" in timer
    assert "RandomizedDelaySec=30" in timer


def test_target_due_uses_exchange_local_time():
    target = _schedule().targets[0]
    before = datetime(2026, 7, 17, 16, 29, tzinfo=ZoneInfo("America/New_York"))
    after = datetime(2026, 7, 17, 16, 30, tzinfo=ZoneInfo("America/New_York"))
    assert target.is_due(before) is False
    assert target.is_due(after) is True


def test_target_due_catches_latest_completed_weekday_after_outage():
    target = _schedule().targets[0]
    saturday = datetime(
        2026,
        7,
        18,
        9,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )

    assert target.is_due(saturday) is False
    assert target.is_analysis_date_due(saturday, "2026-07-17") is True
    assert target.is_analysis_date_due(saturday, "2026-07-18") is False
    with pytest.raises(ValueError, match="ISO date"):
        target.is_analysis_date_due(saturday, "not-a-date")


def test_scheduler_catches_latest_completed_date_after_weekend_restart(
    tmp_path,
    monkeypatch,
):
    store = RunHistoryStore(tmp_path / "runs.db")
    captured = []
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )

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
            report_path=None,
        )

    saturday = datetime(
        2026,
        7,
        18,
        9,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    first = run_due_analyses(
        _schedule(),
        now=saturday,
        store=store,
        preferences={},
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )
    second = run_due_analyses(
        _schedule(),
        now=saturday,
        store=store,
        preferences={},
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )

    assert first[0]["status"] == "completed"
    assert first[0]["analysis_date"] == "2026-07-17"
    assert first[0]["schedule_trigger"] == "latest_completed_date_catch_up"
    assert second[0]["status"] == "already_recorded"
    assert second[0]["schedule_trigger"] == "latest_completed_date_catch_up"
    assert len(captured) == 1
    assert captured[0].analysis_date == "2026-07-17"


def test_scheduled_architecture_inventory_fails_closed_without_leaking_paths(tmp_path):
    missing = tmp_path / "secret-schedule-name.json"

    inventory = load_scheduled_architecture_inventory(missing)

    assert inventory == {
        "schema": "tradingagents/scheduled-architecture-inventory/v1",
        "status": "unavailable",
        "schedule_enabled": None,
        "paired_shadow_authorized": False,
        "architectures": [],
        "error_type": "FileNotFoundError",
    }
    assert str(tmp_path) not in json.dumps(inventory)


def test_scheduled_architecture_inventory_reports_disabled_schedule(tmp_path):
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(
        json.dumps({"enabled": False, "targets": []}),
        encoding="utf-8",
    )

    inventory = load_scheduled_architecture_inventory(schedule_path)

    assert inventory["status"] == "schedule_disabled"
    assert inventory["schedule_enabled"] is False
    assert inventory["architectures"] == []


def test_scheduled_architecture_inventory_drops_internal_error_text(
    tmp_path,
    monkeypatch,
):
    schedule_path = tmp_path / "schedule.json"
    schedule_path.write_text(
        json.dumps({
            "enabled": True,
            "targets": [{
                "symbol": "NVDA",
                "timezone": "America/New_York",
                "run_after": "16:30",
            }],
        }),
        encoding="utf-8",
    )

    def fail_identity(*args, **kwargs):
        raise RuntimeError("sentinel-secret /private/schedule/path")

    monkeypatch.setattr(
        "tradingagents.automation.daily.scheduled_architecture_identity",
        fail_identity,
    )

    inventory = load_scheduled_architecture_inventory(schedule_path)

    assert inventory["status"] == "unavailable"
    assert inventory["error_type"] == "RuntimeError"
    assert "sentinel-secret" not in json.dumps(inventory)
    assert "/private" not in json.dumps(inventory)


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
        "paired_shadow_authorized": True,
        "targets": [
            {
                **common,
                "architecture_version": "baseline",
                "longitudinal_context_mode": "portfolio_only",
            },
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
    assert schedule.paired_shadow_authorized is True


def test_enabled_paired_shadow_requires_explicit_cost_authorization():
    common = {
        "symbol": "NVDA",
        "timezone": "America/New_York",
        "run_after": "16:30",
    }
    with pytest.raises(ValueError, match="paired_shadow_authorized=true"):
        DailySchedule.from_dict({
            "enabled": True,
            "targets": [
                {
                    **common,
                    "architecture_version": "baseline",
                    "longitudinal_context_mode": "portfolio_only",
                },
                {
                    **common,
                    "architecture_version": "challenger",
                    "longitudinal_context_mode": "research_and_portfolio",
                },
            ],
        })
    direct_targets = (
        ScheduledTarget.from_dict({
            **common,
            "architecture_version": "baseline",
            "longitudinal_context_mode": "portfolio_only",
        }),
        ScheduledTarget.from_dict({
            **common,
            "architecture_version": "challenger",
            "longitudinal_context_mode": "research_and_portfolio",
        }),
    )
    with pytest.raises(ValueError, match="paired_shadow_authorized=true"):
        DailySchedule(enabled=True, targets=direct_targets)


def test_paired_shadow_rejects_non_comparable_upstream_inputs():
    common = {
        "symbol": "NVDA",
        "timezone": "America/New_York",
        "run_after": "16:30",
        "longitudinal_context_mode": "portfolio_only",
    }
    with pytest.raises(ValueError, match="share schedule and analysts"):
        DailySchedule.from_dict({
            "enabled": False,
            "targets": [
                {
                    **common,
                    "architecture_version": "baseline",
                    "selected_analysts": ["market"],
                },
                {
                    **common,
                    "architecture_version": "challenger",
                    "longitudinal_context_mode": "research_and_portfolio",
                    "selected_analysts": ["market", "news"],
                },
            ],
        })


def test_completed_shadow_pairs_counterbalance_cold_cache_execution_order(
    tmp_path, monkeypatch
):
    common = {
        "symbol": "NVDA",
        "timezone": "America/New_York",
        "run_after": "16:30",
    }
    schedule = DailySchedule.from_dict({
        "enabled": True,
        "paired_shadow_authorized": True,
        "targets": [
            {
                **common,
                "architecture_version": "baseline",
                "longitudinal_context_mode": "portfolio_only",
            },
            {
                **common,
                "architecture_version": "challenger",
                "longitudinal_context_mode": "research_and_portfolio",
            },
        ],
    })
    store = RunHistoryStore(tmp_path / "runs.db")
    captured = []

    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: now,
    )

    def execute(request):
        captured.append((request.analysis_date, request.architecture_version))
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
            report_path=None,
        )

    first = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 16, 45, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )
    second = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 20, 16, 45, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )

    assert captured == [
        ("2026-07-17", "baseline"),
        ("2026-07-17", "challenger"),
        ("2026-07-20", "challenger"),
        ("2026-07-20", "baseline"),
    ]
    assert [
        (row["architecture_version"], row["planned_execution_order"])
        for row in first
    ] == [
        ("baseline", 1),
        ("challenger", 2),
    ]
    assert [
        (row["architecture_version"], row["planned_execution_order"])
        for row in second
    ] == [
        ("challenger", 1),
        ("baseline", 2),
    ]
    assert {row["execution_group_size"] for row in first + second} == {2}


def test_incomplete_shadow_pair_does_not_advance_counterbalance(tmp_path, monkeypatch):
    common = {
        "symbol": "NVDA",
        "timezone": "America/New_York",
        "run_after": "16:30",
    }
    schedule = DailySchedule.from_dict({
        "enabled": True,
        "paired_shadow_authorized": True,
        "targets": [
            {
                **common,
                "architecture_version": "baseline",
                "longitudinal_context_mode": "portfolio_only",
            },
            {
                **common,
                "architecture_version": "challenger",
                "longitudinal_context_mode": "research_and_portfolio",
            },
        ],
    })
    store = RunHistoryStore(tmp_path / "runs.db")
    for version, status in (("baseline", "completed"), ("challenger", "failed")):
        run_id = f"{version}-incomplete-pair"
        store.create_run(
            run_id,
            "NVDA",
            "2026-07-17",
            "stock",
            ["market"],
            "minimax-cn",
            1,
            architecture_version=version,
        )
        store.mark_finished(run_id, status)
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: now,
    )

    result = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 20, 16, 45, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        dry_run=True,
    )

    assert [row["architecture_version"] for row in result] == [
        "baseline",
        "challenger",
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


def test_architecture_evaluation_status_is_compact_and_scoped_to_run_identity():
    class FakeStore:
        def __init__(self):
            self.evaluation_query = None

        def get_run(self, run_id):
            assert run_id == "scheduled-run"
            return {
                "architecture_version": "production",
                "architecture_fingerprint": "production-fingerprint",
            }

        def list_decision_evaluations(self, **kwargs):
            self.evaluation_query = kwargs
            return [{
                "ticker": "NVDA",
                "analysis_date": "2026-07-01",
                "entry_date": "2026-07-02",
                "exit_date": "2026-07-09",
                "architecture_version": "production",
                "architecture_fingerprint": "production-fingerprint",
                "horizon_sessions": 5,
                "rating": "Buy",
                "directional_hit": True,
                "raw_return": 0.02,
                "alpha_return": 0.01,
                "score": 0.01,
                "analysis_evidence_complete": True,
                "architecture_input_complete": True,
            }]

        def list_unevaluated_validated_runs(self, **kwargs):
            assert kwargs == {"ticker": "NVDA"}
            return [{
                "run_id": "pending",
                "settlement_issue_code": "validated_decision_missing",
            }]

    store = FakeStore()
    status = _architecture_evaluation_status(
        store,
        run_id="scheduled-run",
        ticker="NVDA",
    )

    assert store.evaluation_query == {
        "ticker": "NVDA",
        "limit": ARCHITECTURE_EVALUATION_SCAN_LIMIT,
        "include_runtime_metrics": False,
    }
    assert status == {
        "schema": ARCHITECTURE_EVALUATION_STATUS_SCHEMA,
        "status": "loaded",
        "ticker": "NVDA",
        "scan_limit": ARCHITECTURE_EVALUATION_SCAN_LIMIT,
        "evaluated_count_scanned": 1,
        "pending_evaluation_count": 1,
        "blocked_evaluation_count": 1,
        "cohort_count": 1,
        "other_cohort_count": 0,
        "current_architecture": {
            "architecture_version": "production",
            "architecture_fingerprint": "production-fingerprint",
            "observed": True,
            "sample_count": 1,
            "outcome_status": "insufficient_samples",
            "readiness_status": "insufficient_outcome_samples",
            "recommended_action": "continue_sample_collection",
            "controlled_experiment_ready": False,
        },
        "context_cost_diagnostic": {
            "schema": "tradingagents/context-cost-diagnostic/v1",
            "status": "not_observed",
            "top_agents": [],
            "top_tools": [],
        },
    }
    serialized = json.dumps(status)
    assert "raw_return" not in serialized
    assert "alpha_return" not in serialized
    assert "agent_costs" not in serialized


def test_context_cost_diagnostic_is_bounded_compact_and_content_free():
    diagnostic = _context_cost_diagnostic({
        "events": [{
            "type": "stats",
            "content": {
                "by_agent": {
                    "News Analyst": {
                        "llm_calls": 2, "tool_calls": 3,
                        "tokens_in": 90_000, "tokens_out": 9_000,
                    },
                    "attacker-agent": {
                        "llm_calls": 1, "tool_calls": 1,
                        "tokens_in": 999_999, "tokens_out": 1,
                        "payload": "credential=sentinel-secret",
                    },
                    "Market Analyst": {
                        "llm_calls": 1, "tool_calls": 1,
                        "tokens_in": 10_000_000_001, "tokens_out": 1,
                    },
                },
                "by_tool": {
                    "get_news": {
                        "tool_calls": 3, "input_chars": 20,
                        "output_chars": 80_000, "errors": 0,
                        "by_agent": {"News Analyst": {"result": "secret"}},
                    },
                    "attacker-tool": {
                        "tool_calls": 1, "input_chars": 1,
                        "output_chars": 999_999, "errors": 0,
                        "result": "credential=sentinel-secret",
                    },
                    "get_indicators": {
                        "tool_calls": 1, "input_chars": 1,
                        "output_chars": 10_000_000_001, "errors": 0,
                    },
                },
            },
        }],
    })

    assert diagnostic == {
        "schema": "tradingagents/context-cost-diagnostic/v1",
        "status": "observed",
        "top_agents": [{
            "agent": "News Analyst",
            "llm_calls": 2,
            "tool_calls": 3,
            "tokens_in": 90_000,
            "tokens_out": 9_000,
        }],
        "top_tools": [{
            "tool": "get_news",
            "tool_calls": 3,
            "input_chars": 20,
            "output_chars": 80_000,
            "errors": 0,
        }],
    }
    serialized = json.dumps(diagnostic)
    assert "sentinel-secret" not in serialized
    assert "attacker" not in serialized
    assert "by_agent" not in serialized


def test_architecture_evaluation_status_persists_and_redacts_failures(tmp_path):
    store = RunHistoryStore(tmp_path / "runs.db")
    store.create_run(
        "scheduled-run", "NVDA", "2026-07-17", "stock", ["market"],
        "minimax-cn", 1, architecture_version="production",
        architecture_fingerprint="production-fingerprint",
    )

    status = _record_architecture_evaluation_status(
        store,
        run_id="scheduled-run",
        ticker="NVDA",
    )

    assert status["status"] == "empty"
    events = store.get_run("scheduled-run")["events"]
    assert events[-1]["type"] == "architecture_evaluation_status"
    assert events[-1]["content"] == status

    class FailingStore:
        def get_run(self, run_id):
            raise RuntimeError("credential=sentinel-secret")

    failure = _record_architecture_evaluation_status(
        FailingStore(),
        run_id="failed-run",
        ticker="NVDA",
    )
    assert failure == {
        "schema": ARCHITECTURE_EVALUATION_STATUS_SCHEMA,
        "status": "unavailable",
        "ticker": "NVDA",
        "error_type": "RuntimeError",
    }
    assert "sentinel-secret" not in json.dumps(failure)


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
    assert first[0]["schedule_trigger"] == "on_time_window"
    assert first[0]["architecture_evaluation_status"]["status"] == "empty"
    persisted = store.get_run(first[0]["run_id"])["events"]
    assert persisted[-1]["type"] == "architecture_evaluation_status"
    assert second[0]["status"] == "already_recorded"
    assert len(captured) == 1
    assert captured[0].llm_provider == "minimax-cn"
    assert captured[0].quick_think_llm == "MiniMax-M3"


@pytest.mark.parametrize(
    ("decision_status", "scheduler_status", "exit_code"),
    [
        ("validated", "completed", 0),
        ("review_required", "review_required", 0),
        ("unavailable", "unavailable", 1),
    ],
)
def test_scheduler_preserves_canonical_decision_failure_semantics(
    tmp_path,
    monkeypatch,
    decision_status,
    scheduler_status,
    exit_code,
):
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )

    result = run_due_analyses(
        _schedule(),
        now=datetime(2026, 7, 17, 17, 0, tzinfo=ZoneInfo("America/New_York")),
        store=RunHistoryStore(tmp_path / "runs.db"),
        preferences={},
        execute=lambda request: SimpleNamespace(
            run_id=request.run_id,
            decision_status=decision_status,
            report_path=None,
        ),
        lock_path=tmp_path / "daily.lock",
    )

    assert result[0]["status"] == scheduler_status
    assert result[0]["decision_status"] == decision_status
    assert scheduler_exit_code(result) == exit_code


def test_scheduler_exit_code_keeps_exhausted_failure_visible():
    assert scheduler_exit_code([{"status": "attempts_exhausted"}]) == 1
    assert scheduler_exit_code([{"status": "retry_wait"}]) == 0


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
        preferences={
            "llm_provider": "minimax-cn",
            "research_depth": 3,
            "output_language": "French",
            "backend_url": "https://user:credential@example.invalid/v1",
            "config_overrides": {
                "data_vendors": {"news_data": "longbridge_mcp, longbridge"}
            },
        },
        dry_run=True,
        lock_path=tmp_path / "missing-parent" / "daily.lock",
    )
    assert result[0]["status"] == "would_run"
    assert result[0]["llm_provider"] == "minimax-cn"
    assert result[0]["quick_think_llm"] == "MiniMax-M3"
    assert result[0]["research_depth"] == 3
    assert result[0]["output_language"] == "French"
    assert result[0]["data_vendors"]["news_data"] == "longbridge_mcp, longbridge"
    assert result[0]["custom_backend_configured"] is True
    assert result[0]["architecture_manifest_schema"] == (
        "tradingagents/agent-architecture-manifest/v4"
    )
    assert len(result[0]["architecture_fingerprint"]) == 64
    assert result[0]["architecture_manifest"]["decision_config"][
        "trade_risk_policy"
    ]["max_position_pct"] == 5.0
    assert "credential" not in json.dumps(result)
    assert store.list_runs() == []
    assert not (tmp_path / "missing-parent").exists()
    identity = scheduled_architecture_identity(
        _schedule().targets[0],
        {
            "llm_provider": "minimax-cn",
            "research_depth": 3,
            "output_language": "French",
            "backend_url": "https://user:credential@example.invalid/v1",
            "config_overrides": {
                "data_vendors": {"news_data": "longbridge_mcp, longbridge"}
            },
        },
    )
    assert identity["architecture_fingerprint"] == result[0][
        "architecture_fingerprint"
    ]
    assert identity["architecture_version"] == result[0]["architecture_version"]
    assert identity["selected_analysts"] == result[0]["selected_analysts"]
    assert identity["research_depth"] == 3
    assert "backend" not in json.dumps(identity).lower()
    assert "credential" not in json.dumps(identity).lower()


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


def test_market_data_pending_retries_without_consuming_analysis_attempt(
    tmp_path, monkeypatch
):
    store = RunHistoryStore(tmp_path / "runs.db")
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )
    schedule = DailySchedule(
        enabled=True,
        targets=_schedule().targets,
        max_attempts_per_date=1,
        market_data_retry_after_minutes=15,
        market_data_max_wait_minutes=60,
    )
    calls = []

    def execute(request):
        calls.append(request)
        status = "market_data_pending" if len(calls) == 1 else "completed"
        store.create_run(
            request.run_id,
            request.ticker,
            request.analysis_date,
            request.asset_type,
            request.selected_analysts,
            request.llm_provider,
            request.research_depth,
            status=status,
            created_at=(
                "2026-07-17T20:45:00+00:00"
                if len(calls) == 1
                else "2026-07-17T21:01:00+00:00"
            ),
            architecture_version=request.architecture_version,
        )
        store.mark_finished(
            request.run_id,
            status,
            finished_at=(
                "2026-07-17T20:46:00+00:00"
                if len(calls) == 1
                else "2026-07-17T21:02:00+00:00"
            ),
        )
        return SimpleNamespace(
            run_id=request.run_id,
            decision_status=(
                "market_data_pending" if len(calls) == 1 else "validated"
            ),
            report_path=None,
        )

    first = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 16, 45, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )
    waiting = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 16, 50, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )
    retry = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 17, 1, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=execute,
        lock_path=tmp_path / "daily.lock",
    )

    assert first[0]["status"] == "market_data_pending"
    assert first[0]["architecture_evaluation_status"] is None
    assert calls[0].require_exact_market_data_date is True
    assert waiting[0]["status"] == "market_data_wait"
    assert retry[0]["status"] == "completed"
    assert len(calls) == 2


def test_market_data_pending_fails_closed_after_bounded_wait(tmp_path, monkeypatch):
    store = RunHistoryStore(tmp_path / "runs.db")
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )
    schedule = DailySchedule(
        enabled=True,
        targets=_schedule().targets,
        market_data_retry_after_minutes=15,
        market_data_max_wait_minutes=60,
    )
    store.create_run(
        "pending-bar",
        "NVDA",
        "2026-07-17",
        "stock",
        ["market"],
        "minimax-cn",
        1,
        status="market_data_pending",
        created_at="2026-07-17T20:45:00+00:00",
        architecture_version=schedule.targets[0].architecture_version,
    )
    store.mark_finished(
        "pending-bar",
        "market_data_pending",
        finished_at="2026-07-17T20:46:00+00:00",
    )

    outcome = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 17, 46, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=lambda request: (_ for _ in ()).throw(
            AssertionError("bounded wait must fail before another execution")
        ),
        lock_path=tmp_path / "daily.lock",
    )

    assert outcome[0]["status"] == "market_data_unavailable"
    assert scheduler_exit_code(outcome) == 1
    recorded = store.get_run("pending-bar")
    assert recorded["status"] == "market_data_unavailable"
    assert recorded["events"][-1]["content"]["status"] == (
        "unavailable_after_bounded_wait"
    )


def test_pre_runtime_failure_is_persisted_and_counts_toward_retry_bound(
    tmp_path, monkeypatch
):
    store = RunHistoryStore(tmp_path / "runs.db")
    monkeypatch.setattr(
        "tradingagents.automation.daily.latest_completed_daily_bar_date",
        lambda symbol, now: datetime(2026, 7, 17),
    )
    schedule = DailySchedule(
        enabled=True,
        targets=_schedule().targets,
        max_attempts_per_date=1,
        retry_after_minutes=60,
    )

    def fail_before_runtime_registration(request):
        raise RuntimeError(
            "pre-runtime failure credential=sentinel-secret "
            "https://user:secret@example.invalid/v1"
        )

    first = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 17, 0, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=fail_before_runtime_registration,
        lock_path=tmp_path / "daily.lock",
    )
    assert first[0]["status"] == "failed"
    assert first[0]["error_type"] == "RuntimeError"
    assert "sentinel-secret" not in json.dumps(first)
    assert "example.invalid" not in json.dumps(first)
    recorded = store.get_run(first[0]["run_id"])
    assert recorded["status"] == "failed"
    assert recorded["architecture_fingerprint"] == "pre-runtime-failure"

    second = run_due_analyses(
        schedule,
        now=datetime(2026, 7, 17, 18, 30, tzinfo=ZoneInfo("America/New_York")),
        store=store,
        preferences={},
        execute=fail_before_runtime_registration,
        lock_path=tmp_path / "daily.lock",
    )
    assert second[0]["status"] == "attempts_exhausted"
    assert len(store.list_runs()) == 1


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
