"""Operator-only cost enrichment for immutable outcome evaluations."""

from __future__ import annotations

from typing import Any

from tradingagents.observability import normalize_stats_breakdown


MAX_OPERATOR_COST_ROWS = 5000


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
    run_cache: dict[str, dict[str, dict[str, int]] | None] = {}
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
            breakdown = normalize_stats_breakdown(stats)
            run_cache[run_id] = breakdown["by_tool"] or None
        tool_context = run_cache[run_id]
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
