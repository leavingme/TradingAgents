"""Keyless DuckDuckGo search dataflow using parsel."""
from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from datetime import datetime

from parsel import Selector

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
                "pub_date": datetime.now(),  # Fallback date
            })

    return results
