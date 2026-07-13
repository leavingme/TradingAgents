"""Keyless DuckDuckGo search dataflow using parsel."""
from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from parsel import Selector

from .config import get_config
from .errors import NoMarketDataError
from .symbol_utils import resolve_social_query
from .evidence_models import NewsFeed, NewsItem

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def ddg_search(query: str, limit: int = 10) -> list[dict]:
    """Perform a keyless search on DuckDuckGo HTML Lite and return results."""
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            html_content = response.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("DuckDuckGo search failed for query %r: %s", query, e)
        return []

    selector = Selector(text=html_content)
    results = []

    for item in selector.css(".result")[:limit]:
        title_a = item.css(".result__title a")
        title = title_a.css("::text").get()
        link = title_a.attrib.get("href")
        snippet = item.css(".result__snippet::text").get()

        # If redirect link, clean it
        if link and "duckduckgo.com/l/?uddg=" in link:
            parsed = urllib.parse.urlparse(link)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs:
                link = qs["uddg"][0]

        if title and link:
            results.append({
                "title": title.strip(),
                "summary": snippet.strip() if snippet else "",
                "publisher": urllib.parse.urlparse(link).netloc or "Web",
                "link": link,
                # HTML Lite does not expose publication time. Never substitute
                # retrieval time because that defeats look-ahead validation.
                "pub_date": None,
            })

    return results


def _format_results(title: str, results: list[dict]) -> str:
    news_str = ""
    for result in results:
        news_str += f"### {result['title']} (source: {result['publisher']})\n"
        if result["summary"]:
            news_str += f"{result['summary']}\n"
        if result["link"]:
            news_str += f"Link: {result['link']}\n"
        news_str += "\n"
    return f"{title}\n\n{news_str}"


def get_news_duckduckgo(ticker: str, start_date: str, end_date: str) -> NewsFeed:
    """Retrieve ticker news through DuckDuckGo when it is in the configured chain."""
    limit = get_config()["news_article_limit"]
    query = resolve_social_query(ticker)["news_query"]
    results = ddg_search(query, limit=limit)
    if not results:
        raise NoMarketDataError(
            ticker,
            detail=f"DuckDuckGo returned no news results for query {query!r}",
        )

    return NewsFeed(
        items=tuple(NewsItem(
            source_id="", title=item["title"], publisher=item["publisher"],
            # DuckDuckGo HTML does not expose a trustworthy publication time.
            published_at=str(item.get("pub_date") or ""),
            url=item["link"], summary=item["summary"],
            symbols=(ticker.upper(),), vendor="duckduckgo",
        ) for item in results),
        scope="ticker", requested_start=start_date, requested_end=end_date,
        query=query,
    )


def get_global_news_duckduckgo(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> NewsFeed:
    """Retrieve global market news through DuckDuckGo when configured."""
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_date = (curr_dt - timedelta(days=look_back_days)).strftime("%Y-%m-%d")
    query = " ".join(config.get("global_news_queries") or [])
    if not query:
        query = "US inflation Fed rate cut GDP economy market news"

    results = ddg_search(query, limit=limit)
    if not results:
        raise NoMarketDataError(
            curr_date,
            detail=f"DuckDuckGo returned no global news results for query {query!r}",
        )

    return NewsFeed(
        items=tuple(NewsItem(
            source_id="", title=item["title"], publisher=item["publisher"],
            published_at=str(item.get("pub_date") or ""),
            url=item["link"], summary=item["summary"],
            symbols=(), vendor="duckduckgo",
        ) for item in results),
        scope="global", requested_start=start_date, requested_end=curr_date,
        query=query,
    )
