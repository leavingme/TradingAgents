from typing import Annotated

from langchain_core.tools import tool
from pydantic import AfterValidator, Field

from tradingagents.dataflows.interface import route_indicator_batch

DEFAULT_MARKET_INDICATORS = (
    "close_50_sma",
    "close_200_sma",
    "close_10_ema",
    "rsi",
    "macd",
    "macdh",
    "boll_ub",
    "boll_lb",
)


def _validate_indicator_selection(value: list[str] | str) -> list[str] | str:
    raw = value if isinstance(value, list) else value.split(",")
    selected = [str(item).strip() for item in raw if str(item).strip()]
    if not selected:
        return list(DEFAULT_MARKET_INDICATORS)
    if len(selected) > 8:
        raise ValueError("at most eight indicators are allowed")
    return value


IndicatorList = Annotated[list[str], Field(max_length=8)]
IndicatorText = str


@tool
def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[
        IndicatorList | IndicatorText,
        AfterValidator(_validate_indicator_selection),
        "zero to eight technical indicator names; an empty selection uses the server-defined diversified default batch",
    ],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
    **kwargs,
) -> str:
    """
    Retrieve up to eight technical indicators in one batch for a ticker.
    Args:
        symbol (str): Ticker symbol of the company, e.g. AAPL, TSM
        indicator: One name or a list such as ['rsi', 'macd', 'atr']; an empty
            value uses the server-defined diversified default batch.
        curr_date (str): The current trading date you are trading on, YYYY-mm-dd
        look_back_days (int): How many days to look back, default is 30
    Returns:
        str: A formatted dataframe containing the technical indicators for the specified ticker symbol and indicator.
    """
    raw = indicator if isinstance(indicator, list) else indicator.split(",")
    indicators = [str(item).strip().lower() for item in raw if str(item).strip()]
    return route_indicator_batch(symbol, indicators, curr_date, look_back_days)
