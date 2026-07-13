from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.untrusted_content import render_untrusted_payload
from tradingagents.dataflows.evidence_models import render_macro_series


@tool
def get_macro_indicators(
    indicator: Annotated[
        str,
        "Macro indicator: a friendly alias such as 'cpi', 'core_pce', "
        "'unemployment', 'fed_funds_rate', '10y_treasury', 'yield_curve', "
        "'real_gdp', 'vix', or a raw FRED series ID such as 'CPIAUCSL'.",
    ],
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format; the end of the window"],
    look_back_days: Annotated[
        int | None, "Trailing window length in days; omit for a 1-year window"
    ] = None,
    symbol: Annotated[
        str | None,
        "The ticker symbol of the asset being analyzed (e.g., 'NVDA', '0700.HK', '600519.SS'). "
        "Providing this enables mapping friendly aliases to the correct local market indicators.",
    ] = None,
    **kwargs,
) -> str:
    """
    Retrieve a macroeconomic indicator time series from FRED (Federal Reserve
    Economic Data): policy rates, Treasury yields, inflation, labor, and growth.
    Returns the series title, units, frequency, the latest value, the change
    over the window, and a recent observation table. Uses the configured
    macro_data vendor.

    Args:
        indicator (str): Friendly alias or raw FRED series ID
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Trailing window length; omit for a 1-year window
        symbol (str): Optional symbol to resolve non-US market indicators

    Returns:
        str: A formatted markdown report of the macro series
    """
    indicator_mapped = indicator
    if symbol:
        sym_upper = symbol.strip().upper()
        # Hong Kong market routing
        if sym_upper.endswith(".HK"):
            mapping = {
                "cpi": "hk_cpi",
                "core_cpi": "hk_cpi",
                "gdp": "hk_gdp",
                "real_gdp": "hk_gdp",
            }
            if indicator.lower() in mapping:
                indicator_mapped = mapping[indicator.lower()]
        # China A-shares routing
        elif any(sym_upper.endswith(suffix) for suffix in (".SS", ".SZ", ".SH", ".CN")):
            mapping = {
                "cpi": "cn_cpi",
                "core_cpi": "cn_cpi",
                "gdp": "cn_gdp",
                "real_gdp": "cn_gdp",
                "interest_rate": "cn_interest_rate",
                "fed_funds_rate": "cn_interest_rate",
            }
            if indicator.lower() in mapping:
                indicator_mapped = mapping[indicator.lower()]

    return render_untrusted_payload({
        "macro_observations": render_macro_series(
            route_to_vendor(
                "get_macro_indicators", indicator_mapped, curr_date, look_back_days
            )
        )
    })
