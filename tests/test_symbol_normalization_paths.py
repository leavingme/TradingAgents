"""Symbol normalization must apply on every westock path, not just price fetch.

Regression tests for #983 (instrument identity), #984 (reflection returns), and
the news path: a broker symbol like XAUUSD must resolve to the same Westock symbol
(GC=F) that the price path uses, so identity, realized-return, and news lookups
hit the right instrument instead of failing/mismatching.
"""
import json

import tradingagents.agents.utils.agent_utils as au
from tradingagents.dataflows.longbridge import normalize_symbol as normalize_longbridge_symbol
import tradingagents.dataflows.westock_news as wnews
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_identity_lookup_normalizes_symbol(monkeypatch):
    seen = []

    monkeypatch.setattr("tradingagents.dataflows.symbol_utils.is_westock_available", lambda: True)
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.run_westock",
        lambda args, raw=True: seen.append(args[1]) or json.dumps(
            {"success": True, "data": {"name": "Gold Futures", "industry": "FUTURE"}}
        ),
    )
    au.resolve_instrument_identity.cache_clear()

    identity = au.resolve_instrument_identity("XAUUSD")

    assert seen[0] == "gc=f"  # normalized, not the raw broker symbol
    assert identity.get("company_name") == "Gold Futures"


def test_fetch_returns_normalizes_symbol(monkeypatch, tmp_path):
    from tradingagents.dataflows import config as config_module
    config = dict(config_module.get_config())
    config["data_cache_dir"] = str(tmp_path)
    monkeypatch.setattr(config_module, "_config", config)
    queried = []
    monkeypatch.setattr("tradingagents.dataflows.symbol_utils.is_westock_available", lambda: True)
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.run_westock",
        lambda args, raw=True: queried.append(args[1]) or json.dumps([
            {"date": date, "open": 100, "high": 120, "low": 99, "last": 100 + i, "volume": 1}
            for i, date in enumerate(
                ("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09")
            )
        ]),
    )

    # _fetch_returns does not use ``self``; call unbound to avoid building the graph.
    raw, alpha, days = TradingAgentsGraph._fetch_returns(
        None, "XAUUSD", "2025-01-02", holding_days=5, benchmark="SPY"
    )

    assert queried[0] == "gc=f"  # stock symbol normalized (#984)
    assert queried[1] == "usSPY"   # benchmark left as the canonical symbol
    assert raw is not None and days is not None


def test_news_lookup_normalizes_symbol(monkeypatch):
    seen = []
    monkeypatch.setattr("tradingagents.dataflows.symbol_utils.is_westock_available", lambda: True)
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.run_westock",
        lambda args, raw=True: seen.append(args[2]) or json.dumps([
            {"title": "Gold moves", "src": "Westock", "time": "2025-01-02", "url": "https://example.test"}
        ]),
    )

    out = wnews.get_news_westock("XAUUSD", "2025-01-01", "2025-01-10")

    assert seen[0] == "gc=f"   # news queried with the canonical symbol
    assert out.query == "XAUUSD (resolved to GC=F)"
    assert out.items[0].symbols == ("XAUUSD",)


def test_longbridge_normalize_symbol_preserves_a_share_code():
    assert normalize_longbridge_symbol("000001.SZ") == "000001.SZ"
    assert normalize_longbridge_symbol("600519.SH") == "600519.SH"
    assert normalize_longbridge_symbol("0700.HK") == "700.HK"
