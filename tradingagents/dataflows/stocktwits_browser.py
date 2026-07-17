"""Read-only StockTwits JSON adapter using a stateless Playwright browser."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .errors import NoMarketDataError, VendorNotConfiguredError, VendorRateLimitError
from .social_data import SocialFeed, SocialPost

if TYPE_CHECKING:
    from playwright.sync_api import SyncPlaywright

logger = logging.getLogger(__name__)

_API_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"


def _get_playwright() -> "SyncPlaywright":
    """Lazy import to avoid hard dependency when not used."""
    from playwright.sync_api import sync_playwright
    return sync_playwright()


def fetch_stocktwits_feed(
    ticker: str,
    start_date: str,
    end_date: str,
    limit: int = 30,
    timeout: float = 30.0,
) -> SocialFeed:
    """Fetch StockTwits messages for ``ticker`` using Playwright browser automation.

    Launches a stateless headless Chrome process, waits for the public endpoint,
    and converts its JSON response directly into the unified social model.

    Args:
        ticker: Stock ticker symbol (e.g., "NVDA", "AAPL")
        limit: Maximum number of messages to return (default 30)
        timeout: Browser navigation timeout in seconds (default 30)

    The endpoint exposes only a current stream. Historical point-in-time runs
    therefore fail closed instead of substituting current posts.
    """
    from tradingagents.runtime.audit_context import current_analysis_mode, current_run_id

    if current_run_id() and current_analysis_mode() == "point_in_time":
        raise VendorNotConfiguredError(
            "StockTwits current stream does not support point-in-time snapshots"
        )
    url = _API_URL.format(ticker=ticker.upper())

    try:
        pw = _get_playwright()
    except Exception as exc:
        raise VendorNotConfiguredError(
            "Playwright is not installed; install the project dependencies"
        ) from exc

    executable = shutil.which("google-chrome") or shutil.which("chromium")
    if executable is None:
        raise VendorNotConfiguredError(
            "StockTwits browser vendor requires google-chrome or chromium in PATH"
        )

    try:
        with pw as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            with browser:
                context = browser.new_context(
                    user_agent=_UA,
                )
                page = context.new_page()
                response = page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                if response is None:
                    raise RuntimeError("StockTwits navigation returned no response")
                if response.status == 429:
                    raise VendorRateLimitError("StockTwits API returned HTTP 429")
                if response.status != 200:
                    raise RuntimeError(f"StockTwits API returned HTTP {response.status}")
                try:
                    data = response.json()
                except Exception as exc:
                    raise RuntimeError("StockTwits API did not return JSON") from exc
    except VendorRateLimitError:
        raise
    except Exception as exc:
        if type(exc).__name__ == "TimeoutError":
            raise RuntimeError("StockTwits browser request timed out") from exc
        raise

    return _normalize_stocktwits_payload(
        data,
        ticker=ticker,
        limit=limit,
        observed_at=datetime.now(timezone.utc),
    )


def _normalize_stocktwits_payload(
    data: object,
    *,
    ticker: str,
    limit: int,
    observed_at: datetime,
) -> SocialFeed:
    """Map the public API JSON directly into the unified social model."""
    if not isinstance(data, dict):
        raise RuntimeError("StockTwits response root must be an object")
    symbol_data = data.get("symbol")
    messages_data = data.get("messages")
    if not isinstance(symbol_data, dict) or not isinstance(messages_data, list):
        raise RuntimeError("StockTwits response is missing symbol or messages fields")

    posts = []
    for item in messages_data[:limit]:
        if not isinstance(item, dict):
            continue
        try:
            created_at = datetime.fromisoformat(
                str(item["created_at"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            continue
        user = item.get("user") or {}
        if not isinstance(user, dict):
            continue
        entities = item.get("entities") or {}
        sentiment_data = entities.get("sentiment") if isinstance(entities, dict) else None
        sentiment = sentiment_data.get("basic") if isinstance(sentiment_data, dict) else None
        likes = item.get("likes") or {}
        posts.append(
            SocialPost(
                post_id=str(item.get("id") or ""),
                text=str(item.get("body") or ""),
                created_at=created_at,
                author_id=str(user.get("id") or ""),
                username=str(user.get("username") or "unknown"),
                like_count=int(likes.get("total") or 0) if isinstance(likes, dict) else 0,
                sentiment=sentiment,
            )
        )
    if not posts:
        raise NoMarketDataError(ticker, detail="StockTwits returned no usable messages")
    watchlist_count = symbol_data.get("watchlist_count")
    return SocialFeed(
        source="stocktwits_browser",
        symbol=ticker.upper(),
        posts=tuple(posts),
        observed_at=observed_at,
        watchlist_count=int(watchlist_count) if watchlist_count is not None else None,
    )
