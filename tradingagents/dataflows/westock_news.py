"""Westock news data fetching functions.

This module exposes first-class Westock vendor functions for news retrieval.
"""
from __future__ import annotations

import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .config import get_config
from .errors import NoMarketDataError
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)


def get_news_westock(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker from Westock only.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles
    """
    article_limit = get_config()["news_article_limit"]
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"

    from .symbol_utils import is_westock_available, to_westock_code, run_westock
    
    if not is_westock_available():
        raise NoMarketDataError(ticker, canonical, detail="westock-data CLI is not available")

    w_code = to_westock_code(ticker)
    logger.info("westock-data available; fetching news for %s (mapped to %s)", ticker, w_code)
    try:
        raw = run_westock(["news", "list", w_code, "--limit", str(article_limit)], raw=True)
        import json
        articles = json.loads(raw)
    except Exception as exc:
        raise NoMarketDataError(ticker, canonical, detail=f"westock-data news list failed: {exc}") from exc

    if not articles or not isinstance(articles, list):
        raise NoMarketDataError(ticker, canonical, detail="westock-data returned no news articles")

    news_str = ""
    for a in articles:
        title = a.get("title", a.get("news_title", "No title"))
        src = a.get("src", a.get("source", "Unknown"))
        time_str = a.get("time", "")
        link = a.get("url", "")
        news_str += f"### {title} (source: {src})\n"
        news_str += f"Published: {time_str}\n"
        if link:
            news_str += f"Link: {link}\n"
        news_str += "\n"
    return f"## {ticker}{resolved} News, from {start_date} to {end_date}:\n\n{news_str}"


def get_global_news_westock(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    Retrieve global/macro economic news from Westock only.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles to return. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string containing global news articles
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    from .symbol_utils import is_westock_available, run_westock
    
    if not is_westock_available():
        raise NoMarketDataError(curr_date, detail="westock-data CLI is not available")

    logger.info("westock-data available; fetching global/hot news")
    try:
        raw = run_westock(["hot", "news", "--limit", str(limit)], raw=True)
        import json
        articles = json.loads(raw)
    except Exception as exc:
        raise NoMarketDataError(curr_date, detail=f"westock-data global/hot news failed: {exc}") from exc

    if not articles or not isinstance(articles, list):
        raise NoMarketDataError(curr_date, detail="westock-data returned no global news articles")

    news_str = ""
    for a in articles:
        title = a.get("news_title", "No title")
        src = a.get("source", "Unknown")
        ts = a.get("publish_time")
        time_str = ""
        if ts:
            time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        news_str += f"### {title} (source: {src})\n"
        if time_str:
            news_str += f"Published: {time_str}\n"
        news_str += "\n"
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")
    return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"
