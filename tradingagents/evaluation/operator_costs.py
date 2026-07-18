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
    "tradingagents/architecture-run-cost-rollup/v1"
)
_TERMINAL_COST_STATUSES = {
    "completed",
    "review_required",
    "unavailable",
    "failed",
    "cancelled",
    "market_data_unavailable",
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
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(
            str(row.get("architecture_version") or "legacy-unspecified"),
            str(row.get("architecture_fingerprint") or "legacy-unspecified"),
        )].append(row)
    output: list[dict[str, Any]] = []
    for (version, fingerprint), group in sorted(groups.items()):
        analysis_dates = sorted({
            str(row["analysis_date"])
            for row in group
            if row.get("analysis_date")
        })
        rollup: dict[str, Any] = {
            "schema": ARCHITECTURE_RUN_COST_ROLLUP_SCHEMA,
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
        output.append(rollup)
    return output
