"""Idempotent post-close analysis scheduling.

The systemd timer is intentionally a frequent wake-up mechanism, not the
source of market-time truth.  Each invocation evaluates every target in its
exchange-local timezone and the canonical runtime chooses the most recent
completed daily bar.  The latest completed market date owns its exchange-local
post-close window, so a persistent-timer wake-up after a host outage can catch
up that one latest date even on a weekend or before the next session closes.
Existing runs for the same symbol, requested cutoff date, and architecture
version make the operation idempotent across timer retries and host restarts;
the verified market-data date remains a separately audited runtime field.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tradingagents.architecture import (
    AGENT_ARCHITECTURE_VERSION,
    architecture_fingerprint,
    build_architecture_manifest,
)
from tradingagents.dataflows.ohlcv_cache import latest_completed_daily_bar_date
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.runtime import (
    AnalysisEvent,
    AnalysisExecutionError,
    AnalysisRequest,
    OUTCOME_SETTLEMENT_RETRYABLE_ERROR_TYPES,
    run_analysis_once,
)
from tradingagents.runtime.history import RunHistoryStore, history_store
from tradingagents.observability import normalize_stats_breakdown


_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._+\-^=]{1,32}$")
_TERMINAL_STATUSES = {
    "completed",
    "review_required",
    "unavailable",
    "failed",
    "cancelled",
    "market_data_unavailable",
    "outcome_settlement_pending",
    "outcome_settlement_unavailable",
}
_SCHEDULER_FAILURE_STATUSES = {
    "failed", "unavailable", "attempts_exhausted", "market_data_unavailable",
    "outcome_settlement_unavailable",
}
ARCHITECTURE_EVALUATION_STATUS_SCHEMA = (
    "tradingagents/architecture-evaluation-status/v5"
)
ARCHITECTURE_EVALUATION_SCAN_LIMIT = 5000
CONTEXT_COST_DIAGNOSTIC_SCHEMA = "tradingagents/context-cost-diagnostic/v1"
SCHEDULED_ARCHITECTURE_IDENTITY_SCHEMA = (
    "tradingagents/scheduled-architecture-identity/v1"
)
SCHEDULED_ARCHITECTURE_INVENTORY_SCHEMA = (
    "tradingagents/scheduled-architecture-inventory/v1"
)
MAX_SCHEDULED_ARCHITECTURES = 128
_SETTING_KEYS = {
    "research_depth",
    "llm_provider",
    "quick_think_llm",
    "deep_think_llm",
    "backend_url",
    "output_language",
    "google_thinking_level",
    "openai_reasoning_effort",
    "anthropic_effort",
}
_ALLOWED_VENDORS = {
    "core_stock_apis": {"longbridge_mcp", "longbridge", "westock", "alpha_vantage"},
    "technical_indicators": {"longbridge_mcp", "longbridge", "westock", "alpha_vantage"},
    "fundamental_data": {"longbridge_mcp", "longbridge", "westock", "alpha_vantage"},
    "news_data": {
        "longbridge_mcp", "longbridge", "westock", "duckduckgo", "alpha_vantage"
    },
    "social_data": {"bird", "stocktwits_browser", "reddit"},
    "macro_data": {"fred"},
    "prediction_markets": {"polymarket"},
}


def _context_cost_diagnostic(run: dict[str, Any]) -> dict[str, Any]:
    """Summarize the final stats event without copying any payload content."""
    events = run.get("events")
    if not isinstance(events, list):
        events = []
    stats = next(
        (
            event.get("content")
            for event in reversed(events)
            if isinstance(event, dict)
            and event.get("type") == "stats"
            and isinstance(event.get("content"), dict)
        ),
        None,
    )
    if not isinstance(stats, dict):
        return {
            "schema": CONTEXT_COST_DIAGNOSTIC_SCHEMA,
            "status": "not_observed",
            "top_agents": [],
            "top_tools": [],
        }

    breakdown = normalize_stats_breakdown(stats)
    agent_rows = [
        {"agent": agent, **metrics}
        for agent, metrics in breakdown["by_agent"].items()
    ]
    tool_rows = [
        {"tool": tool, **metrics}
        for tool, metrics in breakdown["by_tool"].items()
    ]

    top_agents = sorted(
        agent_rows,
        key=lambda row: (-row["tokens_in"], row["agent"]),
    )[:3]
    top_tools = sorted(
        tool_rows,
        key=lambda row: (-row["output_chars"], row["tool"]),
    )[:3]
    return {
        "schema": CONTEXT_COST_DIAGNOSTIC_SCHEMA,
        "status": (
            "observed" if top_tools else "agent_only" if top_agents else "totals_only"
        ),
        "top_agents": top_agents,
        "top_tools": top_tools,
    }


def _architecture_evaluation_status(
    store: RunHistoryStore,
    *,
    run_id: str,
    ticker: str,
) -> dict[str, Any]:
    """Build the compact post-run evaluation snapshot used by the scheduler."""
    from tradingagents.evaluation import architecture_rollups

    run = store.get_run(run_id)
    if not isinstance(run, dict):
        raise ValueError("scheduled run is missing from history")
    architecture_version = str(run.get("architecture_version") or "").strip()
    architecture_fingerprint = str(
        run.get("architecture_fingerprint") or ""
    ).strip()
    if not architecture_version or not architecture_fingerprint:
        raise ValueError("scheduled run lacks architecture identity")
    evaluations = store.list_decision_evaluations(
        ticker=ticker,
        limit=ARCHITECTURE_EVALUATION_SCAN_LIMIT,
        include_runtime_metrics=False,
    )
    rollups = architecture_rollups(evaluations)
    selected = next(
        (
            row
            for row in rollups
            if row.get("architecture_version") == architecture_version
            and row.get("architecture_fingerprint") == architecture_fingerprint
        ),
        None,
    )
    outcome = selected.get("outcome_assessment") if isinstance(selected, dict) else None
    outcome = outcome if isinstance(outcome, dict) else {}
    optimization = (
        selected.get("optimization_assessment")
        if isinstance(selected, dict)
        else None
    )
    optimization = optimization if isinstance(optimization, dict) else {}
    pending_runs = store.list_unevaluated_validated_runs(ticker=ticker)
    return {
        "schema": ARCHITECTURE_EVALUATION_STATUS_SCHEMA,
        "status": "loaded" if evaluations else "empty",
        "ticker": ticker,
        "scan_limit": ARCHITECTURE_EVALUATION_SCAN_LIMIT,
        "evaluated_count_scanned": len(evaluations),
        "pending_evaluation_count": len(pending_runs),
        "blocked_evaluation_count": sum(
            bool(row.get("settlement_issue_code")) for row in pending_runs
        ),
        "in_progress_evaluation_count": sum(
            bool(row.get("settlement_claimed_by_run_id"))
            for row in pending_runs
        ),
        "failed_evaluation_count": sum(
            bool(row.get("settlement_failure_code")) for row in pending_runs
        ),
        "cohort_count": len(rollups),
        "other_cohort_count": len(rollups) - int(selected is not None),
        "current_architecture": {
            "architecture_version": architecture_version,
            "architecture_fingerprint": architecture_fingerprint,
            "observed": selected is not None,
            "sample_count": (
                int(selected.get("sample_count") or 0) if selected else 0
            ),
            "outcome_status": outcome.get("status") or "not_observed",
            "readiness_status": (
                optimization.get("readiness_status")
                or "insufficient_outcome_samples"
            ),
            "recommended_action": (
                optimization.get("recommended_action")
                or "continue_sample_collection"
            ),
            "controlled_experiment_ready": bool(
                optimization.get("controlled_experiment_ready")
            ),
        },
        "context_cost_diagnostic": _context_cost_diagnostic(run),
    }


def _record_architecture_evaluation_status(
    store: RunHistoryStore,
    *,
    run_id: str,
    ticker: str,
) -> dict[str, Any]:
    """Persist a safe snapshot without changing an already formed decision."""
    try:
        content = _architecture_evaluation_status(
            store,
            run_id=run_id,
            ticker=ticker,
        )
        store.add_event(
            run_id,
            AnalysisEvent(  # type: ignore[arg-type]
                type="architecture_evaluation_status",
                run_id=run_id,
                content=content,
            ),
        )
        return content
    except Exception as exc:
        return {
            "schema": ARCHITECTURE_EVALUATION_STATUS_SCHEMA,
            "status": "unavailable",
            "ticker": ticker,
            "error_type": type(exc).__name__,
        }


def _default_schedule_path() -> Path:
    configured = os.environ.get("TRADINGAGENTS_DAILY_SCHEDULE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "daily_schedule.json"


def _default_web_config_path() -> Path:
    configured = os.environ.get("TRADINGAGENTS_WEB_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".tradingagents" / "web_config.json"


def _parse_clock(value: str) -> time:
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid run_after time {value!r}; expected HH:MM") from exc
    if parsed.tzinfo is not None or parsed.second or parsed.microsecond:
        raise ValueError(f"invalid run_after time {value!r}; expected local HH:MM")
    return parsed


@dataclass(frozen=True)
class ScheduledTarget:
    symbol: str
    timezone: str
    run_after: time
    asset_type: str = "stock"
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    selected_analysts: tuple[str, ...] = (
        "market",
        "social",
        "news",
        "fundamentals",
    )
    architecture_version: str = AGENT_ARCHITECTURE_VERSION
    longitudinal_context_mode: str = "research_and_portfolio"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScheduledTarget":
        symbol = str(payload.get("symbol", "")).strip().upper()
        if not _SYMBOL_RE.fullmatch(symbol):
            raise ValueError(f"invalid scheduled symbol: {symbol!r}")
        timezone_name = str(payload.get("timezone", "")).strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"invalid timezone for {symbol}: {timezone_name!r}") from exc
        asset_type = str(payload.get("asset_type", "stock")).strip().lower()
        if asset_type not in {"stock", "crypto"}:
            raise ValueError(f"invalid asset_type for {symbol}: {asset_type!r}")
        raw_weekdays = payload.get("weekdays", list(range(7)) if asset_type == "crypto" else list(range(5)))
        if not isinstance(raw_weekdays, list) or not raw_weekdays:
            raise ValueError(f"weekdays for {symbol} must be a non-empty list")
        weekdays = tuple(dict.fromkeys(int(day) for day in raw_weekdays))
        if any(day < 0 or day > 6 for day in weekdays):
            raise ValueError(f"weekdays for {symbol} must contain values from 0 to 6")
        analysts = payload.get(
            "selected_analysts", ["market", "social", "news", "fundamentals"]
        )
        if not isinstance(analysts, list) or not analysts:
            raise ValueError(f"selected_analysts for {symbol} must be a non-empty list")
        architecture_version = str(
            payload.get("architecture_version", AGENT_ARCHITECTURE_VERSION)
        ).strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", architecture_version):
            raise ValueError(f"invalid architecture_version for {symbol}")
        context_mode = str(
            payload.get("longitudinal_context_mode", "research_and_portfolio")
        ).strip()
        if context_mode not in {"portfolio_only", "research_and_portfolio"}:
            raise ValueError(f"invalid longitudinal_context_mode for {symbol}")
        return cls(
            symbol=symbol,
            timezone=timezone_name,
            run_after=_parse_clock(str(payload.get("run_after", ""))),
            asset_type=asset_type,
            weekdays=weekdays,
            selected_analysts=tuple(str(item).strip().lower() for item in analysts),
            architecture_version=architecture_version,
            longitudinal_context_mode=context_mode,
        )

    def is_due(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(self.timezone))
        return self.is_analysis_date_due(now, local.date().isoformat())

    def is_analysis_date_due(self, now: datetime, analysis_date: str) -> bool:
        """Whether one completed market date's configured window has passed.

        Tying the window to the market-data date preserves catch-up semantics:
        a persistent timer that resumes on Saturday may still execute Friday's
        latest completed session. It never walks older dates or reconstructs
        historical live decisions.
        """
        try:
            candidate = date.fromisoformat(analysis_date)
        except (TypeError, ValueError) as exc:
            raise ValueError("analysis_date must be an ISO date") from exc
        if candidate.weekday() not in self.weekdays:
            return False
        local = now.astimezone(ZoneInfo(self.timezone))
        scheduled_at = datetime.combine(
            candidate,
            self.run_after,
            tzinfo=ZoneInfo(self.timezone),
        )
        return local >= scheduled_at


@dataclass(frozen=True)
class DailySchedule:
    enabled: bool
    targets: tuple[ScheduledTarget, ...]
    paired_shadow_authorized: bool = False
    max_attempts_per_date: int = 2
    retry_after_minutes: int = 60
    stale_active_after_minutes: int = 360
    market_data_retry_after_minutes: int = 15
    market_data_max_wait_minutes: int = 240
    outcome_settlement_retry_after_minutes: int = 15
    outcome_settlement_max_wait_minutes: int = 240

    def __post_init__(self) -> None:
        identities = [
            (target.symbol, target.architecture_version) for target in self.targets
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("daily schedule contains duplicate symbol/architecture targets")
        groups: dict[str, list[ScheduledTarget]] = {}
        for target in self.targets:
            groups.setdefault(target.symbol, []).append(target)
        shadow_groups = {symbol: rows for symbol, rows in groups.items() if len(rows) > 1}
        for symbol, rows in shadow_groups.items():
            if len(rows) != 2:
                raise ValueError(
                    f"paired shadow schedule for {symbol} must contain exactly two arms"
                )
            shared_inputs = {
                (
                    row.timezone,
                    row.run_after,
                    row.asset_type,
                    row.weekdays,
                    row.selected_analysts,
                )
                for row in rows
            }
            if len(shared_inputs) != 1:
                raise ValueError(
                    f"paired shadow arms for {symbol} must share schedule and analysts"
                )
            if {row.longitudinal_context_mode for row in rows} != {
                "portfolio_only", "research_and_portfolio"
            }:
                raise ValueError(
                    f"paired shadow arms for {symbol} must isolate the supported "
                    "Research Manager context treatment"
                )
        if self.enabled and shadow_groups and not self.paired_shadow_authorized:
            raise ValueError(
                "enabled paired shadow schedule requires paired_shadow_authorized=true"
            )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DailySchedule":
        raw_targets = payload.get("targets", [])
        if not isinstance(raw_targets, list):
            raise ValueError("daily schedule targets must be a list")
        targets = tuple(ScheduledTarget.from_dict(item) for item in raw_targets)
        paired_shadow_authorized = payload.get("paired_shadow_authorized") is True
        max_attempts = int(payload.get("max_attempts_per_date", 2))
        retry_minutes = int(payload.get("retry_after_minutes", 60))
        stale_minutes = int(payload.get("stale_active_after_minutes", 360))
        market_data_retry_minutes = int(
            payload.get("market_data_retry_after_minutes", 15)
        )
        market_data_max_wait_minutes = int(
            payload.get("market_data_max_wait_minutes", 240)
        )
        outcome_settlement_retry_minutes = int(
            payload.get("outcome_settlement_retry_after_minutes", 15)
        )
        outcome_settlement_max_wait_minutes = int(
            payload.get("outcome_settlement_max_wait_minutes", 240)
        )
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts_per_date must be between 1 and 5")
        if retry_minutes < 15 or retry_minutes > 1440:
            raise ValueError("retry_after_minutes must be between 15 and 1440")
        if stale_minutes < 60 or stale_minutes > 2880:
            raise ValueError("stale_active_after_minutes must be between 60 and 2880")
        if market_data_retry_minutes < 15 or market_data_retry_minutes > 240:
            raise ValueError(
                "market_data_retry_after_minutes must be between 15 and 240"
            )
        if market_data_max_wait_minutes < 60 or market_data_max_wait_minutes > 1440:
            raise ValueError(
                "market_data_max_wait_minutes must be between 60 and 1440"
            )
        if market_data_retry_minutes > market_data_max_wait_minutes:
            raise ValueError(
                "market_data_retry_after_minutes cannot exceed market_data_max_wait_minutes"
            )
        if (
            outcome_settlement_retry_minutes < 15
            or outcome_settlement_retry_minutes > 240
        ):
            raise ValueError(
                "outcome_settlement_retry_after_minutes must be between 15 and 240"
            )
        if (
            outcome_settlement_max_wait_minutes < 60
            or outcome_settlement_max_wait_minutes > 1440
        ):
            raise ValueError(
                "outcome_settlement_max_wait_minutes must be between 60 and 1440"
            )
        if outcome_settlement_retry_minutes > outcome_settlement_max_wait_minutes:
            raise ValueError(
                "outcome_settlement_retry_after_minutes cannot exceed "
                "outcome_settlement_max_wait_minutes"
            )
        return cls(
            enabled=payload.get("enabled") is True,
            targets=targets,
            paired_shadow_authorized=paired_shadow_authorized,
            max_attempts_per_date=max_attempts,
            retry_after_minutes=retry_minutes,
            stale_active_after_minutes=stale_minutes,
            market_data_retry_after_minutes=market_data_retry_minutes,
            market_data_max_wait_minutes=market_data_max_wait_minutes,
            outcome_settlement_retry_after_minutes=outcome_settlement_retry_minutes,
            outcome_settlement_max_wait_minutes=outcome_settlement_max_wait_minutes,
        )


def load_daily_schedule(path: Path | None = None) -> DailySchedule:
    schedule_path = path or _default_schedule_path()
    try:
        payload = json.loads(schedule_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"daily schedule not found: {schedule_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid daily schedule JSON: {schedule_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("daily schedule root must be an object")
    return DailySchedule.from_dict(payload)


def load_runtime_preferences(path: Path | None = None) -> dict[str, Any]:
    """Load the server-owned Web preferences without accepting secrets.

    The persisted file contains only runtime/UI settings and ordered vendor
    enablement.  Unknown fields are ignored and provider rows are converted to
    the same comma-separated override shape used by Web runs.
    """
    config_path = path or _default_web_config_path()
    try:
        # Reuse the Web store's legacy migration and allowlists so timer and
        # browser runs cannot silently diverge after defaults change.
        from web.backend.web_config_store import WebConfigStore

        payload = WebConfigStore(config_path).load()
    except (ImportError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_settings = payload.get("settings")
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    result = {key: settings[key] for key in _SETTING_KEYS if key in settings}
    raw_providers = payload.get("providers")
    providers = raw_providers if isinstance(raw_providers, dict) else {}
    vendor_overrides: dict[str, str] = {}
    for category, rows in providers.items():
        if category not in _ALLOWED_VENDORS or not isinstance(rows, list):
            continue
        enabled = [
            str(row["id"]).strip()
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and row.get("enabled") is not False
            and row["id"].strip() in _ALLOWED_VENDORS[category]
        ]
        if enabled:
            vendor_overrides[category] = ", ".join(enabled)
    if vendor_overrides:
        result["config_overrides"] = {"data_vendors": vendor_overrides}
    return result


def _scheduled_analysis_request(
    target: ScheduledTarget,
    preferences: dict[str, Any] | None,
    *,
    analysis_date: str,
    run_id: str,
) -> AnalysisRequest:
    settings = preferences if isinstance(preferences, dict) else {}
    request_kwargs = {
        key: value
        for key, value in settings.items()
        if key in _SETTING_KEYS | {"config_overrides"}
    }
    return AnalysisRequest(
        ticker=target.symbol,
        analysis_date=analysis_date,
        asset_type=target.asset_type,
        selected_analysts=target.selected_analysts,
        run_id=run_id,
        architecture_version=target.architecture_version,
        longitudinal_context_mode=target.longitudinal_context_mode,
        require_exact_market_data_date=True,
        **request_kwargs,
    )


def _effective_architecture(
    request: AnalysisRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from tradingagents.runtime.config_builder import build_runtime_config

    effective_config = build_runtime_config(request)
    manifest = build_architecture_manifest(
        version=request.architecture_version,
        selected_analysts=request.selected_analysts,
        research_depth=effective_config.get("max_debate_rounds"),
        llm_provider=effective_config.get("llm_provider"),
        quick_think_llm=effective_config.get("quick_think_llm"),
        deep_think_llm=effective_config.get("deep_think_llm"),
        longitudinal_context_mode=request.longitudinal_context_mode,
        effective_config=effective_config,
    )
    return effective_config, manifest


def scheduled_architecture_identity(
    target: ScheduledTarget,
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the safe, canonical identity of one configured schedule target.

    This performs the same request/config/manifest construction as a real daily
    run without selecting market data, contacting a vendor, initializing an LLM,
    or writing history.  It intentionally excludes backend URLs and all secret
    material so operator surfaces can distinguish the active production
    architecture from historical cohorts before the first natural run.
    """
    request = _scheduled_analysis_request(
        target,
        preferences,
        analysis_date="2000-01-03",
        run_id="scheduled-architecture-identity",
    )
    effective_config, manifest = _effective_architecture(request)
    return {
        "schema": SCHEDULED_ARCHITECTURE_IDENTITY_SCHEMA,
        "ticker": target.symbol,
        "asset_type": target.asset_type,
        "architecture_version": request.architecture_version,
        "architecture_fingerprint": architecture_fingerprint(manifest),
        "architecture_manifest_schema": manifest["schema"],
        "selected_analysts": list(request.selected_analysts),
        "research_depth": effective_config.get("max_debate_rounds"),
        "llm_provider": effective_config.get("llm_provider"),
        "quick_think_llm": effective_config.get("quick_think_llm"),
        "deep_think_llm": effective_config.get("deep_think_llm"),
        "longitudinal_context_mode": request.longitudinal_context_mode,
    }


def load_scheduled_architecture_inventory(
    schedule_path: Path | None = None,
    preferences_path: Path | None = None,
) -> dict[str, Any]:
    """Load active schedule identities without exposing configuration errors.

    The inventory is an operator control-plane view.  Invalid or unavailable
    server-owned configuration fails closed to an empty identity set while
    retaining only the local exception type for diagnosis.
    """
    try:
        schedule = load_daily_schedule(schedule_path)
        if not schedule.enabled:
            return {
                "schema": SCHEDULED_ARCHITECTURE_INVENTORY_SCHEMA,
                "status": "schedule_disabled",
                "schedule_enabled": False,
                "paired_shadow_authorized": schedule.paired_shadow_authorized,
                "architectures": [],
            }
        if len(schedule.targets) > MAX_SCHEDULED_ARCHITECTURES:
            raise ValueError(
                "scheduled architecture inventory exceeds its bounded limit"
            )
        preferences = load_runtime_preferences(preferences_path)
        identities = [
            scheduled_architecture_identity(target, preferences)
            for target in schedule.targets
        ]
        return {
            "schema": SCHEDULED_ARCHITECTURE_INVENTORY_SCHEMA,
            "status": "loaded",
            "schedule_enabled": True,
            "paired_shadow_authorized": schedule.paired_shadow_authorized,
            "architectures": identities,
        }
    except Exception as exc:
        return {
            "schema": SCHEDULED_ARCHITECTURE_INVENTORY_SCHEMA,
            "status": "unavailable",
            "schedule_enabled": None,
            "paired_shadow_authorized": False,
            "architectures": [],
            "error_type": type(exc).__name__,
        }


def _runs_for_market_date(
    store: RunHistoryStore,
    symbol: str,
    analysis_date: str,
    architecture_version: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in store.list_runs(limit=10_000)
        if str(row.get("ticker", "")).upper() == symbol
        and str(row.get("analysis_date")) == analysis_date
        and str(row.get("architecture_version")) == architecture_version
    ]


def _completed_shadow_pair_count(
    store: RunHistoryStore,
    *,
    symbol: str,
    analysis_date: str,
    architecture_versions: tuple[str, ...],
) -> int:
    """Count prior dates where every configured shadow variant completed.

    Only fully observed pairs influence the next rotation.  A failed or missing
    arm cannot enter a paired outcome comparison, so letting it advance the
    sequence would reintroduce cold/warm-cache imbalance among usable samples.
    """
    required = set(architecture_versions)
    completed_by_date: dict[str, set[str]] = {}
    for row in store.list_runs(limit=10_000):
        row_date = str(row.get("analysis_date") or "")
        version = str(row.get("architecture_version") or "")
        if (
            str(row.get("ticker") or "").upper() != symbol
            or row_date >= analysis_date
            or version not in required
            or str(row.get("status")) not in {"completed", "review_required"}
        ):
            continue
        completed_by_date.setdefault(row_date, set()).add(version)
    return sum(required.issubset(versions) for versions in completed_by_date.values())


def _counterbalanced_target_indices(
    schedule: DailySchedule,
    *,
    analysis_dates: dict[int, str],
    store: RunHistoryStore,
) -> list[int]:
    """Rotate same-symbol shadow arms across completed paired observations."""
    ordered = list(range(len(schedule.targets)))
    groups: dict[tuple[str, str], list[int]] = {}
    for index, analysis_date in analysis_dates.items():
        target = schedule.targets[index]
        groups.setdefault((target.symbol, analysis_date), []).append(index)
    for (symbol, analysis_date), positions in groups.items():
        if len(positions) < 2:
            continue
        versions = tuple(
            schedule.targets[index].architecture_version for index in positions
        )
        rotation = _completed_shadow_pair_count(
            store,
            symbol=symbol,
            analysis_date=analysis_date,
            architecture_versions=versions,
        ) % len(positions)
        rotated = positions[rotation:] + positions[:rotation]
        for destination, source in zip(positions, rotated):
            ordered[destination] = source
    return ordered


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _existing_run_disposition(
    existing: list[dict[str, Any]],
    *,
    schedule: DailySchedule,
    now: datetime,
    current_architecture_fingerprint: str | None = None,
) -> tuple[str, dict[str, Any]] | None:
    if not existing:
        return None
    latest = existing[0]
    statuses = {str(row.get("status")) for row in existing}
    if statuses & {"completed", "review_required"}:
        return "already_recorded", latest
    market_data_runs = [
        row for row in existing
        if row.get("status") in {"market_data_pending", "market_data_unavailable"}
    ]
    if latest.get("status") in {"market_data_pending", "market_data_unavailable"}:
        if any(row.get("status") == "market_data_unavailable" for row in market_data_runs):
            return "market_data_unavailable", latest
        first_pending = market_data_runs[-1]
        pending_since = _parse_timestamp(
            first_pending.get("started_at") or first_pending.get("created_at")
        )
        if (
            pending_since is not None
            and now.astimezone(timezone.utc)
            >= pending_since + timedelta(minutes=schedule.market_data_max_wait_minutes)
        ):
            return "market_data_unavailable", latest
        reference = _parse_timestamp(
            latest.get("finished_at") or latest.get("created_at")
        )
        if reference is not None:
            retry_at = reference + timedelta(
                minutes=schedule.market_data_retry_after_minutes
            )
            if now.astimezone(timezone.utc) < retry_at:
                return "market_data_wait", {**latest, "retry_at": retry_at.isoformat()}
        return None
    settlement_runs = [
        row
        for row in existing
        if row.get("status")
        in {"outcome_settlement_pending", "outcome_settlement_unavailable"}
    ]
    if latest.get("status") in {
        "outcome_settlement_pending",
        "outcome_settlement_unavailable",
    }:
        if any(
            row.get("status") == "outcome_settlement_unavailable"
            for row in settlement_runs
        ):
            return "outcome_settlement_unavailable", latest
        first_pending = settlement_runs[-1]
        pending_since = _parse_timestamp(
            first_pending.get("started_at") or first_pending.get("created_at")
        )
        if (
            pending_since is not None
            and now.astimezone(timezone.utc)
            >= pending_since
            + timedelta(minutes=schedule.outcome_settlement_max_wait_minutes)
        ):
            return "outcome_settlement_unavailable", latest
        reference = _parse_timestamp(
            latest.get("finished_at") or latest.get("created_at")
        )
        if reference is not None:
            retry_at = reference + timedelta(
                minutes=schedule.outcome_settlement_retry_after_minutes
            )
            if now.astimezone(timezone.utc) < retry_at:
                return "outcome_settlement_wait", {
                    **latest,
                    "retry_at": retry_at.isoformat(),
                }
        return None
    active = [row for row in existing if row.get("status") in {"pending", "running"}]
    if active:
        newest_active = active[0]
        active_since = _parse_timestamp(
            newest_active.get("started_at") or newest_active.get("created_at")
        )
        if (
            active_since is None
            or now.astimezone(timezone.utc)
            < active_since + timedelta(minutes=schedule.stale_active_after_minutes)
        ):
            return "already_recorded", newest_active
    unscoped_fingerprints = {None, "", "legacy-unspecified", "pre-runtime-failure"}
    counted_attempts = [
        row
        for row in existing
        if row.get("status") not in {
            "market_data_pending",
            "market_data_unavailable",
            "outcome_settlement_pending",
            "outcome_settlement_unavailable",
        }
        and (
            current_architecture_fingerprint is None
            or row.get("architecture_fingerprint")
            in unscoped_fingerprints | {current_architecture_fingerprint}
        )
    ]
    if len(counted_attempts) >= schedule.max_attempts_per_date:
        return "attempts_exhausted", counted_attempts[0]
    if not counted_attempts:
        return None
    latest_attempt = counted_attempts[0]
    reference = _parse_timestamp(
        latest_attempt.get("finished_at") or latest_attempt.get("created_at")
    )
    if reference is not None:
        retry_at = reference + timedelta(minutes=schedule.retry_after_minutes)
        if now.astimezone(timezone.utc) < retry_at:
            return "retry_wait", {
                **latest_attempt,
                "retry_at": retry_at.isoformat(),
            }
    return None


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_due_analyses(
    schedule: DailySchedule,
    *,
    now: datetime | None = None,
    store: RunHistoryStore = history_store,
    preferences: dict[str, Any] | None = None,
    execute: Callable[[AnalysisRequest], Any] = run_analysis_once,
    dry_run: bool = False,
    lock_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Run each due target at most once per requested cutoff date."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("scheduler now must be timezone-aware")
    if not schedule.enabled:
        return [{"status": "disabled"}]
    runtime_preferences = preferences if preferences is not None else load_runtime_preferences()
    actual_lock_path = lock_path or Path.home() / ".tradingagents" / "daily.lock"

    lock_context = nullcontext(True) if dry_run else _exclusive_lock(actual_lock_path)
    with lock_context as acquired:
        if not acquired:
            return [{"status": "locked", "reason": "another scheduler invocation is active"}]
        outcomes: list[dict[str, Any]] = []
        analysis_dates: dict[int, str] = {}
        date_by_symbol: dict[str, str] = {}
        for index, target in enumerate(schedule.targets):
            if target.symbol not in date_by_symbol:
                date_by_symbol[target.symbol] = latest_completed_daily_bar_date(
                    target.symbol, now=current
                ).date().isoformat()
            analysis_date = date_by_symbol[target.symbol]
            if target.is_analysis_date_due(current, analysis_date):
                analysis_dates[index] = analysis_date
        ordered_indices = _counterbalanced_target_indices(
            schedule,
            analysis_dates=analysis_dates,
            store=store,
        )
        group_sizes: dict[tuple[str, str], int] = {}
        for index, analysis_date in analysis_dates.items():
            target = schedule.targets[index]
            key = (target.symbol, analysis_date)
            group_sizes[key] = group_sizes.get(key, 0) + 1
        group_positions: dict[tuple[str, str], int] = {}

        for target_index in ordered_indices:
            target = schedule.targets[target_index]
            analysis_date = analysis_dates.get(target_index)
            if analysis_date is None:
                outcomes.append({"symbol": target.symbol, "status": "not_due"})
                continue
            local_date = current.astimezone(
                ZoneInfo(target.timezone)
            ).date().isoformat()
            schedule_trigger = (
                "on_time_window"
                if analysis_date == local_date
                else "latest_completed_date_catch_up"
            )
            group_key = (target.symbol, analysis_date)
            group_positions[group_key] = group_positions.get(group_key, 0) + 1
            execution_order = group_positions[group_key]
            execution_group_size = group_sizes[group_key]
            existing = _runs_for_market_date(
                store,
                target.symbol,
                analysis_date,
                target.architecture_version,
            )
            current_architecture_fingerprint = None
            existing_statuses = {str(row.get("status")) for row in existing}
            if (
                not existing_statuses.intersection({"completed", "review_required"})
                and any(
                    row.get("status") in {"failed", "cancelled", "unavailable"}
                    for row in existing
                )
            ):
                try:
                    current_architecture_fingerprint = (
                        scheduled_architecture_identity(
                            target, runtime_preferences
                        )["architecture_fingerprint"]
                    )
                except Exception:
                    # Preserve the conservative legacy budget if identity
                    # preview itself is unavailable. The actual runtime call,
                    # when still below budget, persists the typed failure.
                    current_architecture_fingerprint = None
            disposition = _existing_run_disposition(
                existing,
                schedule=schedule,
                now=current,
                current_architecture_fingerprint=(
                    current_architecture_fingerprint
                ),
            )
            if disposition is not None:
                scheduler_status, latest = disposition
                if (
                    scheduler_status == "market_data_unavailable"
                    and latest.get("status") == "market_data_pending"
                ):
                    timeout_event = AnalysisEvent(
                        type="market_data_status",
                        run_id=str(latest["run_id"]),
                        content={
                            "status": "unavailable_after_bounded_wait",
                            "requested_analysis_date": analysis_date,
                            "market_data_date": latest.get("market_data_date"),
                            "max_wait_minutes": schedule.market_data_max_wait_minutes,
                        },
                    )
                    store.add_event(str(latest["run_id"]), timeout_event)
                    store.mark_finished(str(latest["run_id"]), "market_data_unavailable")
                    latest = {**latest, "status": "market_data_unavailable"}
                if (
                    scheduler_status == "outcome_settlement_unavailable"
                    and latest.get("status") == "outcome_settlement_pending"
                ):
                    timeout_event = AnalysisEvent(
                        type="outcome_settlement_status",
                        run_id=str(latest["run_id"]),
                        content={
                            "status": "unavailable_after_bounded_wait",
                            "requested_analysis_date": analysis_date,
                            "max_wait_minutes": (
                                schedule.outcome_settlement_max_wait_minutes
                            ),
                        },
                    )
                    store.add_event(str(latest["run_id"]), timeout_event)
                    store.mark_finished(
                        str(latest["run_id"]), "outcome_settlement_unavailable"
                    )
                    latest = {**latest, "status": "outcome_settlement_unavailable"}
                outcomes.append(
                    {
                        "symbol": target.symbol,
                        "analysis_date": analysis_date,
                        "status": scheduler_status,
                        "run_id": latest.get("run_id"),
                        "run_status": latest.get("status"),
                        "decision_status": latest.get("decision_status"),
                        "architecture_version": target.architecture_version,
                        "schedule_trigger": schedule_trigger,
                        "planned_execution_order": execution_order,
                        "execution_group_size": execution_group_size,
                        **(
                            {"retry_at": latest["retry_at"]}
                            if latest.get("retry_at")
                            else {}
                        ),
                    }
                )
                continue
            run_id = (
                f"daily-{safe_ticker_component(target.symbol)}-"
                f"{safe_ticker_component(target.architecture_version)}-"
                f"{analysis_date.replace('-', '')}-{uuid4().hex[:8]}"
            )
            request = _scheduled_analysis_request(
                target,
                runtime_preferences,
                analysis_date=analysis_date,
                run_id=run_id,
            )
            if dry_run:
                effective_config, manifest = _effective_architecture(request)
                outcomes.append(
                    {
                        "symbol": target.symbol,
                        "analysis_date": analysis_date,
                        "status": "would_run",
                        "run_id": run_id,
                        "llm_provider": effective_config.get("llm_provider"),
                        "quick_think_llm": effective_config.get("quick_think_llm"),
                        "deep_think_llm": effective_config.get("deep_think_llm"),
                        "selected_analysts": list(request.selected_analysts),
                        "research_depth": effective_config.get("max_debate_rounds"),
                        "output_language": effective_config.get("output_language"),
                        "data_vendors": dict(effective_config.get("data_vendors") or {}),
                        "reasoning_config": {
                            key: effective_config.get(key)
                            for key in (
                                "google_thinking_level",
                                "openai_reasoning_effort",
                                "anthropic_effort",
                            )
                            if effective_config.get(key) is not None
                        },
                        "custom_backend_configured": bool(
                            effective_config.get("backend_url")
                        ),
                        "architecture_version": request.architecture_version,
                        "schedule_trigger": schedule_trigger,
                        "architecture_fingerprint": architecture_fingerprint(manifest),
                        "architecture_manifest_schema": manifest["schema"],
                        "architecture_manifest": manifest,
                        "analysis_mode": request.analysis_mode,
                        "longitudinal_context_mode": request.longitudinal_context_mode,
                        "planned_execution_order": execution_order,
                        "execution_group_size": execution_group_size,
                    }
                )
                continue
            try:
                result = execute(request)
            except Exception as exc:
                error_type = (
                    exc.error_type
                    if isinstance(exc, AnalysisExecutionError)
                    else type(exc).__name__
                )
                settlement_retryable = (
                    error_type in OUTCOME_SETTLEMENT_RETRYABLE_ERROR_TYPES
                )
                # The canonical runtime normally registers the run before doing
                # any expensive work.  Keep the scheduler's retry budget
                # authoritative even when an exception happens before that
                # registration point (for example, while constructing the
                # preliminary architecture manifest).
                if store.get_run(run_id) is None:
                    store.create_run(
                        run_id=run_id,
                        ticker=request.ticker,
                        analysis_date=str(request.analysis_date),
                        asset_type=request.asset_type,
                        selected_analysts=request.selected_analysts,
                        llm_provider=request.llm_provider,
                        research_depth=request.research_depth,
                        status=(
                            "outcome_settlement_pending"
                            if settlement_retryable
                            else "failed"
                        ),
                        architecture_version=request.architecture_version,
                        architecture_fingerprint="pre-runtime-failure",
                    )
                if settlement_retryable:
                    store.add_event(
                        run_id,
                        AnalysisEvent(
                            type="outcome_settlement_status",
                            run_id=run_id,
                            content={
                                "status": "pending_retry",
                                "error_type": error_type,
                                "retry_after_minutes": (
                                    schedule.outcome_settlement_retry_after_minutes
                                ),
                                "max_wait_minutes": (
                                    schedule.outcome_settlement_max_wait_minutes
                                ),
                            },
                        ),
                    )
                    store.mark_finished(run_id, "outcome_settlement_pending")
                elif store.get_run(run_id) is not None:
                    store.mark_finished(run_id, "failed")
                outcomes.append(
                    {
                        "symbol": target.symbol,
                        "analysis_date": analysis_date,
                        "status": (
                            "outcome_settlement_pending"
                            if settlement_retryable
                            else "failed"
                        ),
                        "run_id": run_id,
                        "error_type": error_type,
                        "architecture_version": target.architecture_version,
                        "schedule_trigger": schedule_trigger,
                        "planned_execution_order": execution_order,
                        "execution_group_size": execution_group_size,
                    }
                )
                continue
            decision_status = str(result.decision_status)
            scheduler_status = {
                "validated": "completed",
                "review_required": "review_required",
                "unavailable": "unavailable",
                "market_data_pending": "market_data_pending",
            }.get(decision_status, "unavailable")
            evaluation_status = (
                None
                if decision_status == "market_data_pending"
                else _record_architecture_evaluation_status(
                    store,
                    run_id=result.run_id,
                    ticker=target.symbol,
                )
            )
            outcomes.append(
                {
                    "symbol": target.symbol,
                    "analysis_date": analysis_date,
                    "status": scheduler_status,
                    "run_id": result.run_id,
                    "decision_status": decision_status,
                    "architecture_version": target.architecture_version,
                    "schedule_trigger": schedule_trigger,
                    "planned_execution_order": execution_order,
                    "execution_group_size": execution_group_size,
                    "report_path": str(result.report_path) if result.report_path else None,
                    "architecture_evaluation_status": evaluation_status,
                }
            )
        return outcomes


def terminal_statuses() -> frozenset[str]:
    """Expose scheduler terminal statuses for diagnostics and tests."""
    return frozenset(_TERMINAL_STATUSES)


def scheduler_exit_code(outcomes: list[dict[str, Any]]) -> int:
    """Return non-zero when the daily decision failed or retries are exhausted."""
    return int(any(item.get("status") in _SCHEDULER_FAILURE_STATUSES for item in outcomes))
