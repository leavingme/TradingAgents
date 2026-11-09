"""Runtime-only vendor registration; does not edit TradingAgents source/defaults."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import Iterator

from .providers import longbridge_mcp, westock


def config_with_fallbacks(config: dict | None = None) -> dict:
    """Copy TradingAgents config and prefer Westock with Longbridge/Yahoo fallbacks."""
    if config is None:
        from tradingagents.default_config import DEFAULT_CONFIG

        config = DEFAULT_CONFIG
    result = deepcopy(config)
    result.setdefault("data_vendors", {})
    result["data_vendors"]["core_stock_apis"] = "westock,longbridge_mcp,yfinance"
    result["data_vendors"]["technical_indicators"] = "westock,longbridge_mcp,yfinance"
    result["data_vendors"]["fundamental_data"] = "sec_edgar,westock,longbridge_mcp,yfinance"
    result["data_vendors"]["news_data"] = "westock,longbridge_mcp,yfinance"
    # Keep company-profile routing Westock-first, but prefer Longbridge for
    # actual statements. The router filters this list to each method's support.
    result.setdefault("tool_vendors", {}).update({
        "get_balance_sheet": "longbridge_mcp,sec_edgar,yfinance",
        "get_cashflow": "longbridge_mcp,sec_edgar,yfinance",
        "get_income_statement": "longbridge_mcp,sec_edgar,yfinance",
        "get_news": "westock,longbridge_mcp,yfinance",
        "get_global_news": "westock,yfinance",
        "get_insider_transactions": "yfinance",
    })
    return result


@contextmanager
def registered_fallbacks() -> Iterator[None]:
    """Temporarily add optional providers to the existing router registry."""
    from tradingagents.dataflows.router import VENDOR_METHODS
    from tradingagents.dataflows.vendors.yahoo import snapshot as yahoo_snapshot
    from tradingagents.agents import tools as agent_tools

    from .snapshot import last_snapshot_row_count, load_snapshot_ohlcv

    methods = {
        "get_stock_data": {
            "longbridge_mcp": longbridge_mcp.get_stock_data,
            "westock": westock.get_stock_data,
        },
        "get_indicators": {
            "longbridge_mcp": longbridge_mcp.get_indicators,
            "westock": westock.get_indicators,
        },
        "get_fundamentals": {
            "longbridge_mcp": longbridge_mcp.get_fundamentals,
            "westock": westock.get_fundamentals,
        },
        "get_balance_sheet": {
            "longbridge_mcp": longbridge_mcp.get_balance_sheet,
        },
        "get_cashflow": {
            "longbridge_mcp": longbridge_mcp.get_cashflow,
        },
        "get_income_statement": {
            "longbridge_mcp": longbridge_mcp.get_income_statement,
        },
        "get_news": {
            "longbridge_mcp": longbridge_mcp.get_news,
            "westock": westock.get_news,
        },
        "get_global_news": {
            "westock": westock.get_global_news,
        },
    }
    previous = {method: VENDOR_METHODS[method].copy() for method in methods}
    previous_snapshot_loader = yahoo_snapshot.load_ohlcv
    previous_snapshot_builder = agent_tools.build_verified_market_snapshot

    def build_routed_snapshot(symbol, as_of_date, look_back_days=30, indicators=None):
        text = previous_snapshot_builder(symbol, as_of_date, look_back_days, indicators)
        available_rows = last_snapshot_row_count()
        if available_rows is None:
            return text
        minimum_rows = {
            "close_10_ema": 10,
            "close_50_sma": 50,
            "close_200_sma": 200,
            "rsi": 14,
            "boll": 20,
            "boll_ub": 20,
            "boll_lb": 20,
            "macd": 26,
            "macds": 34,
            "macdh": 34,
            "atr": 14,
        }
        lines = []
        for line in text.splitlines():
            for name, required_rows in minimum_rows.items():
                prefix = f"| {name} |"
                if line.startswith(prefix) and available_rows < required_rows:
                    line = f"| {name} | N/A (requires {required_rows} rows; provider returned {available_rows}) |"
                    break
            lines.append(line)
        return "\n".join(lines)

    try:
        for method, providers in methods.items():
            VENDOR_METHODS[method].update(providers)
        # The core exact-price snapshot normally reads Yahoo directly. In this
        # optional bridge runtime it must use the same configured provider chain
        # as all other OHLCV requests.
        yahoo_snapshot.load_ohlcv = load_snapshot_ohlcv
        agent_tools.build_verified_market_snapshot = build_routed_snapshot
        yield
    finally:
        agent_tools.build_verified_market_snapshot = previous_snapshot_builder
        yahoo_snapshot.load_ohlcv = previous_snapshot_loader
        for method, providers in previous.items():
            VENDOR_METHODS[method].clear()
            VENDOR_METHODS[method].update(providers)
