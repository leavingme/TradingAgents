"""Westock news data fetching functions with DuckDuckGo fallback.

This module exposes first-class Westock vendor functions for news retrieval.
"""
from __future__ import annotations

import logging
from datetime import datetime
from dateutil.relativedelta import relativedelta

from .config import get_config
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)


def _ddg_news_fallback(query: str, start_date: str, end_date: str, limit: int) -> str:
    """Helper to fetch and format news from DuckDuckGo search as a fallback."""
    from .duckduckgo_search import ddg_search
    logger.info("Falling back to DuckDuckGo search for query %r", query)
    results = ddg_search(query, limit=limit)
    if not results:
        return f"No news found for query '{query}' via fallback search between {start_date} and {end_date}"

    news_str = ""
    for r in results:
        news_str += f"### {r['title']} (source: {r['publisher']})\n"
        if r["summary"]:
            news_str += f"{r['summary']}\n"
        if r["link"]:
            news_str += f"Link: {r['link']}\n"
        news_str += "\n"

    return f"## News Fallback for query '{query}', from {start_date} to {end_date}:\n\n{news_str}"


def get_news_westock(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker. Falls back to DuckDuckGo search.

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
    
    # 1. Try westock-data
    if is_westock_available():
        w_code = to_westock_code(ticker)
        logger.info("westock-data available; fetching news for %s (mapped to %s)", ticker, w_code)
        try:
            raw = run_westock(["news", "list", w_code, "--limit", str(article_limit)], raw=True)
            import json
            articles = json.loads(raw)
            if articles and isinstance(articles, list):
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
        except Exception as exc:
            logger.warning("westock-data news list failed: %s; trying DuckDuckGo fallback", exc)

    # 2. Fall back to DuckDuckGo search
    from .symbol_utils import resolve_social_query
    sq = resolve_social_query(ticker)
    query = sq["news_query"]
    return _ddg_news_fallback(query, start_date, end_date, article_limit)


def get_global_news_westock(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    Retrieve global/macro economic news. Falls back to DuckDuckGo on error.

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
    
    # 1. Try westock-data global news
    if is_westock_available():
        logger.info("westock-data available; fetching global/hot news")
        try:
            raw = run_westock(["hot", "news", "--limit", str(limit)], raw=True)
            import json
            articles = json.loads(raw)
            if articles and isinstance(articles, list):
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
                # Calculate date range
                curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
                start_dt = curr_dt - relativedelta(days=look_back_days)
                start_date = start_dt.strftime("%Y-%m-%d")
                return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"
        except Exception as exc:
            logger.warning("westock-data global/hot news failed: %s; trying DuckDuckGo", exc)

    # 2. Fall back to DuckDuckGo search
    from .duckduckgo_search import ddg_search
    ddg_query = "US inflation Fed rate cut GDP economy market news"
    results = ddg_search(ddg_query, limit=limit)
    if not results:
        return f"No global news found for {curr_date} via fallback."

    # Format date range
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    news_str = ""
    for r in results:
        news_str += f"### {r['title']} (source: {r['publisher']})\n"
        if r["summary"]:
            news_str += f"{r['summary']}\n"
        if r["link"]:
            news_str += f"Link: {r['link']}\n"
        news_str += "\n"

    return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"
