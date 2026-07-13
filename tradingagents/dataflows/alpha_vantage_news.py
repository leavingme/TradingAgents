import json

from .alpha_vantage_common import _make_api_request, format_datetime_for_api
from .errors import NoMarketDataError
from .evidence_models import NewsFeed, NewsItem, parse_external_datetime


def _payload(value, symbol: str) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise NoMarketDataError(symbol, detail="Alpha Vantage returned non-JSON news") from exc
    if not isinstance(value, dict):
        raise NoMarketDataError(symbol, detail="Alpha Vantage returned invalid news payload")
    message = value.get("Error Message") or value.get("Information") or value.get("Note")
    if message:
        raise NoMarketDataError(symbol, detail=str(message))
    return value


def _to_feed(payload: dict, *, start: str, end: str, symbol: str | None) -> NewsFeed:
    items = []
    for raw in payload.get("feed") or []:
        if not isinstance(raw, dict):
            continue
        try:
            published = parse_external_datetime(raw.get("time_published"))
        except ValueError:
            published = ""
        payload_symbols = tuple(
            str(row.get("ticker", "")).upper()
            for row in raw.get("ticker_sentiment") or []
            if isinstance(row, dict) and row.get("ticker")
        )
        symbols = payload_symbols
        items.append(NewsItem(
            source_id="", title=str(raw.get("title") or ""),
            publisher=str(raw.get("source") or raw.get("source_domain") or ""),
            published_at=published, url=str(raw.get("url") or ""),
            summary=str(raw.get("summary") or ""), symbols=symbols,
            vendor="alpha_vantage",
        ))
    return NewsFeed(
        items=tuple(items), scope="ticker" if symbol else "global",
        requested_start=start, requested_end=end, query=symbol or "global macro",
    )


def get_news(ticker, start_date, end_date) -> NewsFeed:
    """Returns live and historical market news & sentiment data from premier news outlets worldwide.

    Covers stocks, cryptocurrencies, forex, and topics like fiscal policy, mergers & acquisitions, IPOs.

    Args:
        ticker: Stock symbol for news articles.
        start_date: Start date for news search.
        end_date: End date for news search.

    Returns:
        Dictionary containing news sentiment data or JSON string.
    """

    params = {
        "tickers": ticker,
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(end_date),
    }

    result = _payload(_make_api_request("NEWS_SENTIMENT", params), ticker)
    return _to_feed(result, start=start_date, end=end_date, symbol=ticker)

def get_global_news(curr_date, look_back_days: int = 7, limit: int = 50) -> NewsFeed:
    """Returns global market news & sentiment data without ticker-specific filtering.

    Covers broad market topics like financial markets, economy, and more.

    Args:
        curr_date: Current date in yyyy-mm-dd format.
        look_back_days: Number of days to look back (default 7).
        limit: Maximum number of articles (default 50).

    Returns:
        Dictionary containing global news sentiment data or JSON string.
    """
    from datetime import datetime, timedelta

    # Calculate start date
    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - timedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    params = {
        "topics": "financial_markets,economy_macro,economy_monetary",
        "time_from": format_datetime_for_api(start_date),
        "time_to": format_datetime_for_api(curr_date),
        "limit": str(limit),
    }

    result = _payload(_make_api_request("NEWS_SENTIMENT", params), "GLOBAL")
    return _to_feed(result, start=start_date, end=curr_date, symbol=None)


def get_insider_transactions(symbol: str) -> dict[str, str] | str:
    """Returns latest and historical insider transactions by key stakeholders.

    Covers transactions by founders, executives, board members, etc.

    Args:
        symbol: Ticker symbol. Example: "IBM".

    Returns:
        Dictionary containing insider transaction data or JSON string.
    """

    params = {
        "symbol": symbol,
    }

    return _make_api_request("INSIDER_TRANSACTIONS", params)
