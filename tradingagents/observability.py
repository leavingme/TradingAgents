"""Bounded schemas shared by operator-facing runtime observability."""

from __future__ import annotations

from typing import Any


CANONICAL_STATS_AGENTS = frozenset({
    "Market Analyst",
    "Sentiment Analyst",
    "News Analyst",
    "Fundamentals Analyst",
    "Bull Researcher",
    "Bear Researcher",
    "Research Manager",
    "Trader",
    "Aggressive Analyst",
    "Conservative Analyst",
    "Neutral Analyst",
    "Portfolio Manager",
})
CANONICAL_STATS_TOOLS = frozenset({
    "get_balance_sheet",
    "get_cashflow",
    "get_financial_evidence",
    "get_fundamentals",
    "get_global_news",
    "get_indicators",
    "get_income_statement",
    "get_insider_transactions",
    "get_macro_indicators",
    "get_news",
    "get_prediction_markets",
    "get_social_posts",
    "get_stock_data",
    "get_stocktwits_messages",
    "get_verified_market_snapshot",
})
STATS_COST_FIELDS = ("llm_calls", "tool_calls", "tokens_in", "tokens_out")
STATS_TOOL_FIELDS = ("tool_calls", "input_chars", "output_chars", "errors")
MAX_NORMALIZED_STATS_METRIC = 10_000_000_000


def _normalized_metric(value: Any) -> int | None:
    if (
        type(value) is not int
        or not 0 <= value <= MAX_NORMALIZED_STATS_METRIC
    ):
        return None
    return value


def normalize_stats_breakdown(value: Any) -> dict[str, dict[str, dict[str, int]]]:
    """Return bounded numeric Agent/tool stats without retaining payload content."""
    if not isinstance(value, dict):
        return {"by_agent": {}, "by_tool": {}}
    normalized: dict[str, dict[str, dict[str, int]]] = {
        "by_agent": {},
        "by_tool": {},
    }
    specifications = (
        ("by_agent", CANONICAL_STATS_AGENTS | {"Unattributed"}, STATS_COST_FIELDS),
        ("by_tool", CANONICAL_STATS_TOOLS | {"Unattributed"}, STATS_TOOL_FIELDS),
    )
    for section, allowed_names, fields in specifications:
        rows = value.get(section)
        if not isinstance(rows, dict):
            continue
        for name, raw_metrics in rows.items():
            if name not in allowed_names or not isinstance(raw_metrics, dict):
                continue
            metrics = {
                field: _normalized_metric(raw_metrics.get(field))
                for field in fields
            }
            if any(metric is None for metric in metrics.values()):
                continue
            normalized[section][name] = {
                field: int(metrics[field]) for field in fields
            }
    return normalized
