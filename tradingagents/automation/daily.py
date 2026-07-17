"""Idempotent post-close analysis scheduling.

The systemd timer is intentionally a frequent wake-up mechanism, not the
source of market-time truth.  Each invocation evaluates every target in its
exchange-local timezone and the canonical runtime chooses the most recent
completed daily bar.  Existing runs for the same symbol, requested cutoff
date, and architecture version make the operation idempotent across timer
retries and host restarts; the verified market-data date remains a separately
audited runtime field.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
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
from tradingagents.runtime import AnalysisRequest, run_analysis_once
from tradingagents.runtime.history import RunHistoryStore, history_store


_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._+\-^=]{1,32}$")
_TERMINAL_STATUSES = {
    "completed",
    "review_required",
    "unavailable",
    "failed",
    "cancelled",
}
_SCHEDULER_FAILURE_STATUSES = {"failed", "unavailable", "attempts_exhausted"}
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
        return local.weekday() in self.weekdays and local.time().replace(tzinfo=None) >= self.run_after


@dataclass(frozen=True)
class DailySchedule:
    enabled: bool
    targets: tuple[ScheduledTarget, ...]
    max_attempts_per_date: int = 2
    retry_after_minutes: int = 60
    stale_active_after_minutes: int = 360

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DailySchedule":
        raw_targets = payload.get("targets", [])
        if not isinstance(raw_targets, list):
            raise ValueError("daily schedule targets must be a list")
        targets = tuple(ScheduledTarget.from_dict(item) for item in raw_targets)
        identities = [(target.symbol, target.architecture_version) for target in targets]
        if len(identities) != len(set(identities)):
            raise ValueError("daily schedule contains duplicate symbol/architecture targets")
        max_attempts = int(payload.get("max_attempts_per_date", 2))
        retry_minutes = int(payload.get("retry_after_minutes", 60))
        stale_minutes = int(payload.get("stale_active_after_minutes", 360))
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts_per_date must be between 1 and 5")
        if retry_minutes < 15 or retry_minutes > 1440:
            raise ValueError("retry_after_minutes must be between 15 and 1440")
        if stale_minutes < 60 or stale_minutes > 2880:
            raise ValueError("stale_active_after_minutes must be between 60 and 2880")
        return cls(
            enabled=payload.get("enabled") is True,
            targets=targets,
            max_attempts_per_date=max_attempts,
            retry_after_minutes=retry_minutes,
            stale_active_after_minutes=stale_minutes,
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
) -> tuple[str, dict[str, Any]] | None:
    if not existing:
        return None
    latest = existing[0]
    statuses = {str(row.get("status")) for row in existing}
    if statuses & {"completed", "review_required"}:
        return "already_recorded", latest
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
    if len(existing) >= schedule.max_attempts_per_date:
        return "attempts_exhausted", latest
    reference = _parse_timestamp(latest.get("finished_at") or latest.get("created_at"))
    if reference is not None:
        retry_at = reference + timedelta(minutes=schedule.retry_after_minutes)
        if now.astimezone(timezone.utc) < retry_at:
            return "retry_wait", {**latest, "retry_at": retry_at.isoformat()}
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
            if not target.is_due(current):
                continue
            if target.symbol not in date_by_symbol:
                date_by_symbol[target.symbol] = latest_completed_daily_bar_date(
                    target.symbol, now=current
                ).date().isoformat()
            analysis_dates[index] = date_by_symbol[target.symbol]
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
            disposition = _existing_run_disposition(
                existing,
                schedule=schedule,
                now=current,
            )
            if disposition is not None:
                scheduler_status, latest = disposition
                outcomes.append(
                    {
                        "symbol": target.symbol,
                        "analysis_date": analysis_date,
                        "status": scheduler_status,
                        "run_id": latest.get("run_id"),
                        "run_status": latest.get("status"),
                        "decision_status": latest.get("decision_status"),
                        "architecture_version": target.architecture_version,
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
            request_kwargs = {
                key: value
                for key, value in runtime_preferences.items()
                if key in _SETTING_KEYS | {"config_overrides"}
            }
            request = AnalysisRequest(
                ticker=target.symbol,
                analysis_date=analysis_date,
                asset_type=target.asset_type,
                selected_analysts=target.selected_analysts,
                run_id=run_id,
                architecture_version=target.architecture_version,
                longitudinal_context_mode=target.longitudinal_context_mode,
                **request_kwargs,
            )
            if dry_run:
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
                        status="failed",
                        architecture_version=request.architecture_version,
                        architecture_fingerprint="pre-runtime-failure",
                    )
                    store.mark_finished(run_id, "failed")
                outcomes.append(
                    {
                        "symbol": target.symbol,
                        "analysis_date": analysis_date,
                        "status": "failed",
                        "run_id": run_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "architecture_version": target.architecture_version,
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
            }.get(decision_status, "unavailable")
            outcomes.append(
                {
                    "symbol": target.symbol,
                    "analysis_date": analysis_date,
                    "status": scheduler_status,
                    "run_id": result.run_id,
                    "decision_status": decision_status,
                    "architecture_version": target.architecture_version,
                    "planned_execution_order": execution_order,
                    "execution_group_size": execution_group_size,
                    "report_path": str(result.report_path) if result.report_path else None,
                }
            )
        return outcomes


def terminal_statuses() -> frozenset[str]:
    """Expose scheduler terminal statuses for diagnostics and tests."""
    return frozenset(_TERMINAL_STATUSES)


def scheduler_exit_code(outcomes: list[dict[str, Any]]) -> int:
    """Return non-zero when the daily decision failed or retries are exhausted."""
    return int(any(item.get("status") in _SCHEDULER_FAILURE_STATUSES for item in outcomes))
