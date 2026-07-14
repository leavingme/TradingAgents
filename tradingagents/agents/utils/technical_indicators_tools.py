from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_indicator_batch


@tool
def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[
        list[str] | str,
        "one to eight technical indicator names; prefer one list in a single tool call",
    ],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
    **kwargs,
) -> str:
    """
    Retrieve up to eight technical indicators in one batch for a ticker.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        indicator: One name or a list such as ['rsi', 'macd', 'atr'].
        curr_date (str): The current trading date you are trading on, YYYY-mm-dd
        look_back_days (int): How many days to look back, default is 30
    Returns:
        str: A formatted dataframe containing the technical indicators for the specified ticker symbol and indicator.
    """
    raw = indicator if isinstance(indicator, list) else indicator.split(",")
    indicators = [str(item).strip().lower() for item in raw if str(item).strip()]
    return route_indicator_batch(symbol, indicators, curr_date, look_back_days)
