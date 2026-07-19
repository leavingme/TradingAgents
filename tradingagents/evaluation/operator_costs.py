"""Operator-only cost enrichment for immutable outcome evaluations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite
from statistics import fmean
from typing import Any

from tradingagents.observability import (
    CANONICAL_STATS_AGENTS,
    CANONICAL_STATS_TOOLS,
    STATS_COST_FIELDS,
    STATS_TOOL_FIELDS,
    normalize_stats_snapshot,
)


MAX_OPERATOR_COST_ROWS = 5000
ARCHITECTURE_RUN_COST_ROLLUP_SCHEMA = (
    "tradingagents/architecture-run-cost-rollup/v2"
)
ROLLING_RUN_COST_MONITORING_SCHEMA = (
    "tradingagents/rolling-run-cost-monitoring/v1"
)
RUN_COST_ASSESSMENT_SCHEMA = "tradingagents/run-cost-assessment/v1"
RUN_COST_WINDOW_SIZES = (5, 10, 20)
MINIMUM_RUN_COST_DATES = 5
HIGH_CONTEXT_TOKEN_THRESHOLD = 150_000
_TERMINAL_COST_STATUSES = {
    "completed",
    "review_required",
    "unavailable",
    "failed",
    "cancelled",
    "market_data_unavailable",
    "outcome_settlement_pending",
    "outcome_settlement_unavailable",
}


def _final_stats(run: Any) -> dict[str, Any] | None:
    if not isinstance(run, dict):
        return None
    events = run.get("events")
    if not isinstance(events, list):
        return None
    return next(
        (
            event.get("content")
            for event in reversed(events)
            if isinstance(event, dict)
            and event.get("type") == "stats"
            and isinstance(event.get("content"), dict)
        ),
        None,
    )


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _runtime_seconds(row: dict[str, Any]) -> float | None:
    started = _timestamp(row.get("started_at") or row.get("run_started_at"))
    finished = _timestamp(row.get("finished_at") or row.get("run_finished_at"))
    if started is None or finished is None or finished < started:
        return None
    return (finished - started).total_seconds()


def _metric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number >= 0 else None


def _analysis_date(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _cost_window_summary(days: list[dict[str, Any]]) -> dict[str, Any]:
    token_values = [
        value
        for day in days
        if (value := _metric(day.get("tokens_in"))) is not None
    ]
    runtime_values = [
        value
        for day in days
        if (value := _metric(day.get("runtime_seconds"))) is not None
    ]
    return {
        "analysis_date_count": len(days),
        "from_analysis_date": days[0]["analysis_date"] if days else None,
        "through_analysis_date": days[-1]["analysis_date"] if days else None,
        "run_count": sum(int(day["run_count"]) for day in days),
        "input_token_complete_date_count": len(token_values),
        "runtime_complete_date_count": len(runtime_values),
        "mean_daily_tokens_in": (
            fmean(token_values) if len(token_values) == len(days) and days else None
        ),
        "mean_daily_runtime_seconds": (
            fmean(runtime_values)
            if len(runtime_values) == len(days) and days
            else None
        ),
        "adverse_run_count": sum(int(day["adverse_run_count"]) for day in days),
    }


def _rolling_run_cost_monitoring(group: list[dict[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_rows = 0
    for row in group:
        analysis_date = _analysis_date(row.get("analysis_date"))
        if analysis_date is None:
            invalid_rows += 1
            continue
        by_date[analysis_date].append(row)
    adverse_statuses = _TERMINAL_COST_STATUSES - {"completed"}
    daily_rows: list[dict[str, Any]] = []
    for analysis_date, rows in sorted(by_date.items()):
        daily: dict[str, Any] = {
            "analysis_date": analysis_date,
            "run_count": len(rows),
            "adverse_run_count": sum(
                str(row.get("status")) in adverse_statuses for row in rows
            ),
        }
        for field in ("tokens_in", "runtime_seconds"):
            values = [
                value
                for row in rows
                if (value := _metric(row.get(field))) is not None
            ]
            daily[field] = sum(values) if len(values) == len(rows) else None
        daily_rows.append(daily)

    windows: dict[str, Any] = {}
    for window_size in RUN_COST_WINDOW_SIZES:
        current_days = daily_rows[-window_size:]
        previous_days = daily_rows[-2 * window_size : -window_size]
        current = _cost_window_summary(current_days)
        previous = _cost_window_summary(previous_days)
        comparison_ready = bool(
            len(current_days) == window_size
            and len(previous_days) == window_size
            and current["mean_daily_tokens_in"] is not None
            and previous["mean_daily_tokens_in"] is not None
        )
        if comparison_ready:
            token_delta = (
                current["mean_daily_tokens_in"]
                - previous["mean_daily_tokens_in"]
            )
            previous_tokens = previous["mean_daily_tokens_in"]
            token_delta_ratio = (
                token_delta / previous_tokens if previous_tokens else None
            )
            runtime_delta = (
                current["mean_daily_runtime_seconds"]
                - previous["mean_daily_runtime_seconds"]
                if current["mean_daily_runtime_seconds"] is not None
                and previous["mean_daily_runtime_seconds"] is not None
                else None
            )
            delta = {
                "mean_daily_tokens_in": token_delta,
                "mean_daily_tokens_in_ratio": token_delta_ratio,
                "mean_daily_runtime_seconds": runtime_delta,
            }
        else:
            delta = None
        windows[str(window_size)] = {
            "status": (
                "comparison_ready" if comparison_ready else "insufficient_history"
            ),
            "required_analysis_dates": 2 * window_size,
            "current": current,
            "previous": previous,
            "current_minus_previous": delta,
        }
    return {
        "schema": ROLLING_RUN_COST_MONITORING_SCHEMA,
        "interpretation": (
            "Descriptive operator cost monitoring only. All terminal attempts on "
            "one ticker/analysis date are summed before comparing date windows."
        ),
        "automatic_architecture_mutation_allowed": False,
        "outcome_claim_allowed": False,
        "window_sizes": list(RUN_COST_WINDOW_SIZES),
        "distinct_analysis_date_count": len(daily_rows),
        "multi_run_analysis_date_count": sum(
            int(day["run_count"] > 1) for day in daily_rows
        ),
        "invalid_rows_excluded": invalid_rows,
        "windows": windows,
    }


def _run_cost_assessment(
    rollup: dict[str, Any],
    group: list[dict[str, Any]],
) -> dict[str, Any]:
    sample_count = int(rollup["sample_count"])
    observed_count = int(rollup["stats_observed_count"])
    token_observed_count = int(rollup.get("tokens_in_sample_count", 0))
    monitoring = rollup["rolling_cost_monitoring"]
    distinct_dates = int(monitoring["distinct_analysis_date_count"])
    adverse_count = sum(
        count
        for status, count in rollup["run_status_counts"].items()
        if status != "completed"
    )
    high_context_count = sum(
        1
        for row in group
        if (
            tokens := _metric(row.get("tokens_in"))
        ) is not None and tokens > HIGH_CONTEXT_TOKEN_THRESHOLD
    )
    ready_window = next(
        (
            monitoring["windows"][str(size)]
            for size in RUN_COST_WINDOW_SIZES
            if monitoring["windows"][str(size)]["status"] == "comparison_ready"
        ),
        None,
    )
    recent_token_delta = (
        ready_window["current_minus_previous"]["mean_daily_tokens_in"]
        if ready_window
        else None
    )
    recent_token_ratio = (
        ready_window["current_minus_previous"]["mean_daily_tokens_in_ratio"]
        if ready_window
        else None
    )
    recent_increase = bool(
        recent_token_delta is not None
        and recent_token_ratio is not None
        and recent_token_delta >= 10_000
        and recent_token_ratio >= 0.10
    )
    if observed_count < sample_count or token_observed_count < sample_count:
        status = "incomplete_cost_observability"
        recommended_action = "repair_cost_observability"
    elif distinct_dates < MINIMUM_RUN_COST_DATES:
        status = "insufficient_cost_history"
        recommended_action = "continue_cost_collection"
    elif adverse_count:
        status = "reliability_attention_required"
        recommended_action = "investigate_run_reliability"
    elif recent_increase:
        status = "recent_cost_increase_observed"
        recommended_action = "investigate_recent_cost_increase"
    else:
        status = "cost_baseline_ready"
        recommended_action = "monitor_cost_and_design_challenger"
    return {
        "schema": RUN_COST_ASSESSMENT_SCHEMA,
        "status": status,
        "recommended_action": recommended_action,
        "automatic_architecture_mutation_allowed": False,
        "outcome_claim_allowed": False,
        "promotion_gate_effect": "none",
        "minimum_analysis_dates": MINIMUM_RUN_COST_DATES,
        "sample_count": sample_count,
        "distinct_analysis_date_count": distinct_dates,
        "stats_observed_count": observed_count,
        "input_token_observed_count": token_observed_count,
        "adverse_run_count": adverse_count,
        "high_context_token_threshold": HIGH_CONTEXT_TOKEN_THRESHOLD,
        "high_context_run_count": high_context_count,
        "recent_mean_daily_tokens_in_delta": recent_token_delta,
        "recent_mean_daily_tokens_in_ratio": recent_token_ratio,
    }


def attach_operator_cost_metrics(
    evaluations: list[dict[str, Any]],
    *,
    store: Any,
) -> list[dict[str, Any]]:
    """Attach sanitized per-tool metrics without changing canonical history rows.

    History stays the source of immutable outcome and Agent-level cost fields.
    This operator boundary performs bounded run lookups for the final stats event,
    copies only canonical numeric tool counters, and never mutates its input rows.
    """
    if len(evaluations) > MAX_OPERATOR_COST_ROWS:
        raise ValueError(
            f"operator cost enrichment is limited to {MAX_OPERATOR_COST_ROWS} rows"
        )
    run_cache: dict[str, dict[str, Any] | None] = {}
    enriched: list[dict[str, Any]] = []
    for evaluation in evaluations:
        row = dict(evaluation)
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
            row["tool_context_status"] = "not_observed"
            enriched.append(row)
            continue
        if run_id not in run_cache:
            stats = _final_stats(store.get_run(run_id))
            run_cache[run_id] = normalize_stats_snapshot(stats) if stats else None
        snapshot = run_cache[run_id]
        if snapshot:
            row["runtime_cost_status"] = "observed"
            for field, metric in snapshot["totals"].items():
                row.setdefault(field, metric)
            if snapshot["by_agent"] and "agent_costs" not in row:
                row["agent_costs"] = {
                    agent: dict(metrics)
                    for agent, metrics in sorted(snapshot["by_agent"].items())
                }
            tool_context = snapshot["by_tool"]
        else:
            row["runtime_cost_status"] = "not_observed"
            tool_context = None
        if "runtime_seconds" not in row:
            runtime_seconds = _runtime_seconds(row)
            if runtime_seconds is not None:
                row["runtime_seconds"] = runtime_seconds
        if tool_context:
            row["tool_context_status"] = "observed"
            row["tool_context"] = {
                tool: dict(metrics)
                for tool, metrics in sorted(tool_context.items())
            }
        else:
            row["tool_context_status"] = "not_observed"
        enriched.append(row)
    return enriched


def load_operator_run_costs(
    *,
    store: Any,
    ticker: str | None = None,
    limit: int = MAX_OPERATOR_COST_ROWS,
) -> list[dict[str, Any]]:
    """Load terminal runs for immediate cost evaluation, independent of outcomes."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
        raise ValueError("operator run cost limit must be between 1 and 5000")
    normalized_ticker = ticker.strip().upper() if isinstance(ticker, str) else None
    runs = [
        row
        for row in store.list_runs(limit=MAX_OPERATOR_COST_ROWS)
        if str(row.get("status")) in _TERMINAL_COST_STATUSES
        and (
            normalized_ticker is None
            or str(row.get("ticker") or "").upper() == normalized_ticker
        )
    ][:limit]
    return attach_operator_cost_metrics(runs, store=store)


def architecture_run_cost_rollups(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate run costs before fixed-horizon market outcomes have matured."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(
            str(row.get("ticker") or "UNKNOWN").strip().upper(),
            str(row.get("architecture_version") or "legacy-unspecified"),
            str(row.get("architecture_fingerprint") or "legacy-unspecified"),
        )].append(row)
    output: list[dict[str, Any]] = []
    for (ticker, version, fingerprint), group in sorted(groups.items()):
        analysis_dates = sorted({
            normalized
            for row in group
            if (normalized := _analysis_date(row.get("analysis_date"))) is not None
        })
        rollup: dict[str, Any] = {
            "schema": ARCHITECTURE_RUN_COST_ROLLUP_SCHEMA,
            "ticker": ticker,
            "architecture_version": version,
            "architecture_fingerprint": fingerprint,
            "sample_count": len(group),
            "stats_observed_count": sum(
                row.get("runtime_cost_status") == "observed" for row in group
            ),
            "from_analysis_date": analysis_dates[0] if analysis_dates else None,
            "through_analysis_date": analysis_dates[-1] if analysis_dates else None,
            "run_status_counts": {
                status: sum(str(row.get("status") or "unknown") == status for row in group)
                for status in sorted({
                    str(row.get("status") or "unknown") for row in group
                })
            },
            "decision_status_counts": {
                status: sum(
                    str(row.get("decision_status") or "not_observed") == status
                    for row in group
                )
                for status in sorted({
                    str(row.get("decision_status") or "not_observed")
                    for row in group
                })
            },
        }
        for field in ("runtime_seconds", *STATS_COST_FIELDS):
            values = [
                metric
                for row in group
                if (metric := _metric(row.get(field))) is not None
            ]
            rollup[f"{field}_sample_count"] = len(values)
            if values:
                rollup[f"mean_{field}"] = fmean(values)

        agent_names = sorted({
            agent
            for row in group
            for agent in (
                row.get("agent_costs") if isinstance(row.get("agent_costs"), dict) else {}
            )
            if agent in CANONICAL_STATS_AGENTS | {"Unattributed"}
        })
        rollup["agent_costs"] = {}
        for agent in agent_names:
            agent_rollup: dict[str, Any] = {}
            for field in STATS_COST_FIELDS:
                values = [
                    metric
                    for row in group
                    if isinstance(row.get("agent_costs"), dict)
                    and isinstance(row["agent_costs"].get(agent), dict)
                    and (metric := _metric(row["agent_costs"][agent].get(field)))
                    is not None
                ]
                agent_rollup[f"{field}_sample_count"] = len(values)
                if values:
                    agent_rollup[f"mean_{field}"] = fmean(values)
            rollup["agent_costs"][str(agent)] = agent_rollup

        tool_names = sorted({
            tool
            for row in group
            for tool in (
                row.get("tool_context")
                if isinstance(row.get("tool_context"), dict)
                else {}
            )
            if tool in CANONICAL_STATS_TOOLS | {"Unattributed"}
        })
        rollup["tool_context"] = {}
        for tool in tool_names:
            tool_rollup: dict[str, Any] = {}
            for field in STATS_TOOL_FIELDS:
                values = [
                    metric
                    for row in group
                    if isinstance(row.get("tool_context"), dict)
                    and isinstance(row["tool_context"].get(tool), dict)
                    and (metric := _metric(row["tool_context"][tool].get(field)))
                    is not None
                ]
                tool_rollup[f"{field}_sample_count"] = len(values)
                if values:
                    tool_rollup[f"mean_{field}"] = fmean(values)
            rollup["tool_context"][str(tool)] = tool_rollup

        rollup["agent_hotspots"] = sorted(
            (
                {
                    "agent": agent,
                    "mean_tokens_in": fields["mean_tokens_in"],
                    "sample_count": fields["tokens_in_sample_count"],
                }
                for agent, fields in rollup["agent_costs"].items()
                if "mean_tokens_in" in fields
            ),
            key=lambda item: (-item["mean_tokens_in"], item["agent"]),
        )[:3]
        rollup["tool_context_hotspots"] = sorted(
            (
                {
                    "tool": tool,
                    "mean_output_chars": fields["mean_output_chars"],
                    "sample_count": fields["output_chars_sample_count"],
                }
                for tool, fields in rollup["tool_context"].items()
                if "mean_output_chars" in fields
            ),
            key=lambda item: (-item["mean_output_chars"], item["tool"]),
        )[:3]
        rollup["rolling_cost_monitoring"] = _rolling_run_cost_monitoring(group)
        rollup["cost_assessment"] = _run_cost_assessment(rollup, group)
        output.append(rollup)
    return output
