from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.untrusted_content import render_untrusted_payload
from tradingagents.dataflows.evidence_models import (
    PredictionMarketFeed,
    render_prediction_market_feed,
)


@tool
def get_prediction_markets(
    topic: Annotated[
        str,
        "Event topic/keyword, e.g. 'Fed rate cut', 'recession 2026', "
        "'US election', or a sector/company event.",
    ],
    limit: Annotated[int | None, "Max markets to return; omit for a default of 6"] = None,
    **kwargs,
) -> str:
    """
    Retrieve live, market-implied probabilities for forward-looking events from
    prediction markets (Polymarket): Fed decisions, recession, elections,
    geopolitics, crypto. Returns the most-traded open markets matching the
    topic, each with its implied probability, traded volume, resolution date,
    and recent move. Uses the configured prediction_markets vendor.

    Args:
        topic (str): Event keyword(s) to search
        limit (int): Max markets to return; omit for a default of 6

    Returns:
        str: A formatted markdown report of matching prediction markets
    """
    result = route_to_vendor("get_prediction_markets", topic, limit)
    rendered = (
        render_prediction_market_feed(result)
        if isinstance(result, PredictionMarketFeed)
        else str(result)
    )
    return render_untrusted_payload({"prediction_markets": rendered})
