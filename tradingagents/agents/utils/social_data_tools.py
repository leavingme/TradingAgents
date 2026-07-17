from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.social_data import render_social_feed
from tradingagents.dataflows.untrusted_content import render_untrusted_payload


@tool
def get_social_posts(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    **kwargs,
) -> str:
    """Retrieve validated X/Twitter posts for a ticker."""
    return render_untrusted_payload({
        "social_posts": render_social_feed(
            route_to_vendor("get_social_posts", ticker, start_date, end_date)
        )
    })


@tool
def get_stocktwits_messages(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    **kwargs,
) -> str:
    """Retrieve recent StockTwits messages and sentiment for a ticker.

    Returns validated bullish/bearish labels and recent messages with timestamps.
    """
    return render_untrusted_payload({
        "stocktwits": render_social_feed(
            route_to_vendor(
                "get_stocktwits_messages", ticker, start_date, end_date
            )
        )
    })
