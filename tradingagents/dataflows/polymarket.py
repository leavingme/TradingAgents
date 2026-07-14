"""Polymarket prediction-market vendor.

Surfaces live, market-implied probabilities for forward-looking events (Fed
decisions, recession, elections, geopolitics, crypto) to the news analyst, as a
complement to news (what happened) and FRED macro data (where things stand):
what the crowd actually prices to happen next.

Uses Polymarket's public Gamma API (https://gamma-api.polymarket.com) — no key,
no auth. Each market's ``outcomePrices`` are the implied probabilities of its
outcomes (a "Yes" at 0.76 means the market prices a 76% chance).
"""
import json
import math
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.evidence_models import (
    PredictionMarket,
    PredictionMarketFeed,
    PredictionOutcome,
    parse_external_datetime,
    prediction_source_id,
)

GAMMA_BASE = "https://gamma-api.polymarket.com"

# Network timeout (seconds), consistent with the other vendors.
REQUEST_TIMEOUT = 30

# Default number of markets to return, ranked by traded volume.
DEFAULT_LIMIT = 6


def _current_temporal_context() -> tuple[str, str | None]:
    # Keep runtime imports lazy: dataflows.interface imports this module while
    # runtime itself imports the graph/dataflow stack.
    from tradingagents.runtime.audit_context import (
        current_analysis_mode,
        current_information_cutoff,
    )

    return current_analysis_mode(), current_information_cutoff()


def _reject_unavailable_point_in_time_snapshot(topic: str) -> None:
    """Fail closed only for explicit historical point-in-time analysis."""
    analysis_mode, information_cutoff = _current_temporal_context()
    if analysis_mode == "point_in_time":
        raise NoMarketDataError(
            topic,
            detail=(
                "Polymarket exposes only a live snapshot and cannot provide "
                f"point-in-time evidence for information_cutoff={information_cutoff}"
            ),
        )


def _request(path: str, params: dict) -> dict:
    response = requests.get(
        f"{GAMMA_BASE}/{path}", params=params, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def _parse_json_list(value) -> list:
    """Gamma encodes ``outcomes``/``outcomePrices`` as JSON-string arrays."""
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


def _float_or_nan(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return math.nan
    return parsed


def _adapt_market(
    event: dict, market: dict, *, observed_at: str
) -> PredictionMarket:
    event_id = str(event.get("id") or "").strip()
    market_id = str(market.get("id") or "").strip()
    event_slug = str(event.get("slug") or "").strip()
    market_slug = str(market.get("slug") or "").strip()
    outcomes = _parse_json_list(market.get("outcomes"))
    prices = _parse_json_list(market.get("outcomePrices"))
    expiry = market.get("endDate") or event.get("endDate") or ""
    try:
        expiry = parse_external_datetime(expiry)
    except (ValueError, OverflowError, OSError):
        expiry = ""
    slug = event_slug or market_slug
    url = f"https://polymarket.com/event/{quote(slug)}" if slug else ""
    return PredictionMarket(
        source_id=prediction_source_id(
            vendor="polymarket", event_id=event_id, market_id=market_id
        ),
        event_id=event_id,
        event_title=str(event.get("title") or "").strip(),
        market_id=market_id,
        condition_id=str(market.get("conditionId") or "").strip(),
        question=str(market.get("question") or "").strip(),
        slug=market_slug,
        url=url,
        expires_at=expiry,
        observed_at=observed_at,
        outcomes=tuple(
            PredictionOutcome(label=str(label).strip(), probability=_float_or_nan(price))
            for label, price in zip(outcomes, prices)
        ),
        volume=_float_or_nan(market.get("volumeNum") or market.get("volume") or 0),
        one_week_probability_change=(
            _float_or_nan(market.get("oneWeekPriceChange"))
            if market.get("oneWeekPriceChange") is not None
            else None
        ),
        vendor="polymarket",
        active=bool(market.get("active", True)),
        closed=bool(market.get("closed", False)),
        archived=bool(market.get("archived", False)),
    )


def get_prediction_markets(
    topic: str, limit: int | None = None
) -> PredictionMarketFeed:
    """Return live prediction-market probabilities for an event topic.

    Args:
        topic: Event keyword(s), e.g. "Fed rate cut", "recession 2026",
            "US election", or a sector/company event.
        limit: Max markets to return (ranked by traded volume); ``None`` uses
            DEFAULT_LIMIT.

    Returns:
        A structured feed adapted directly from Gamma event/market JSON. The
        routing layer performs deterministic validation before rendering.
    """
    _reject_unavailable_point_in_time_snapshot(topic)

    if limit is None:
        limit = DEFAULT_LIMIT
    limit = int(limit)
    if not topic.strip():
        raise ValueError("prediction-market topic must not be empty")
    if not 1 <= limit <= 20:
        raise ValueError("prediction-market limit must be between 1 and 20")

    try:
        data = _request("public-search", {"q": topic, "limit_per_type": 20})
    except requests.RequestException as e:
        raise VendorUnavailableError(
            f"Polymarket public-search failed for {topic!r}: {e}"
        ) from e
    if not isinstance(data, dict):
        raise VendorUnavailableError("Polymarket public-search returned non-object JSON")

    observed_at = datetime.now(timezone.utc).isoformat()
    markets = tuple(
        _adapt_market(event, market, observed_at=observed_at)
        for event in (data.get("events") or [])
        if isinstance(event, dict)
        for market in (event.get("markets") or [])
        if isinstance(market, dict)
    )
    return PredictionMarketFeed(
        topic=topic.strip(),
        observed_at=observed_at,
        requested_limit=limit,
        markets=markets,
    )
