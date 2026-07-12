from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.social_data import render_social_feed


@tool
def get_social_posts(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
    **kwargs,
) -> str:
    """Retrieve validated X/Twitter posts for a ticker."""
    return render_social_feed(route_to_vendor("get_social_posts", ticker, start_date, end_date))
