"""Structured Longbridge CLI/MCP news adapters and routing."""

from __future__ import annotations

import copy

import pytest

import tradingagents.default_config as default_config
from tradingagents.dataflows import interface, longbridge, longbridge_mcp
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.evidence_models import validate_news_feed


@pytest.mark.unit
def test_longbridge_cli_ticker_news_maps_raw_json(monkeypatch):
    seen = []
    details = []
    monkeypatch.setattr(longbridge, "_run_cli_json_list", lambda args: seen.append(args) or [{
        "id": "123",
        "title": "NVIDIA launches a platform",
        "published_at": "2026-07-13T06:09:27Z",
        "url": "https://longbridge.com/news/123",
    }])
    monkeypatch.setattr(
        longbridge,
        "_run_cli",
        lambda args, timeout=30: details.append(args) or "Full article body.",
    )

    feed = longbridge.get_news("NVDA", "2026-07-07", "2026-07-13")
    validated = validate_news_feed(feed, symbol="NVDA")

    assert seen == [["news", "NVDA.US", "--count", "20"]]
    assert details == [["news", "detail", "123"]]
    assert validated.items[0].publisher == "Longbridge"
    assert validated.items[0].symbols == ("NVDA",)
    assert validated.items[0].vendor == "longbridge"
    assert validated.items[0].summary == "Full article body."
    assert validated.items[0].source_id.startswith("news_")


@pytest.mark.unit
def test_longbridge_cli_global_news_uses_structured_search(monkeypatch):
    seen = []
    monkeypatch.setattr(longbridge, "_run_cli_json_list", lambda args: seen.append(args) or [{
        "id": "456",
        "title": "Central banks reassess inflation",
        "source_name": "Example Wire",
        "time": "2026-07-12T05:58:31Z",
        "excerpt": "Rates remain restrictive.",
        "url": "https://longbridge.com/news/456.md",
    }])

    feed = longbridge.get_global_news("2026-07-13", 7, 5)
    validated = validate_news_feed(feed)

    assert seen[0][:2] == ["news", "search"]
    assert seen[0][-2:] == ["--count", "5"]
    assert validated.scope == "global"
    assert validated.items[0].publisher == "Example Wire"
    assert validated.items[0].summary == "Rates remain restrictive."


@pytest.mark.unit
def test_longbridge_mcp_ticker_news_maps_structured_payload(monkeypatch):
    class Client:
        def call_tool(self, name, arguments):
            assert name == "news"
            assert arguments == {"symbol": "0700.HK"}
            return [{
                "id": "789",
                "title": "Tencent announces an update",
                "description": "Product details.",
                "published_at": "2026-07-13T04:50:52Z",
                "url": "https://longbridge.com/news/789",
                "related_symbols": ["9988.HK"],
            }]

    monkeypatch.setattr(longbridge_mcp, "_client", Client)
    monkeypatch.setattr(longbridge_mcp, "_resolve_tool", lambda client, capability: capability)

    feed = longbridge_mcp.get_news("0700.HK", "2026-07-07", "2026-07-13")
    validated = validate_news_feed(feed, symbol="0700.HK")

    assert validated.items[0].symbols == ("0700.HK", "9988.HK")
    assert validated.items[0].summary == "Product details."
    assert validated.items[0].vendor == "longbridge_mcp"


@pytest.mark.unit
def test_news_router_prefers_mcp_then_cli(monkeypatch):
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))
    attempts = []

    def no_mcp(*args):
        attempts.append("longbridge_mcp")
        raise RuntimeError("MCP temporarily unavailable")

    def cli(*args):
        attempts.append("longbridge")
        return longbridge._news_rows_to_feed([{
            "title": "Fallback headline",
            "published_at": "2026-07-12T01:00:00Z",
            "url": "https://longbridge.com/news/fallback",
            "description": "Fallback article body.",
        }], vendor="longbridge", scope="ticker", start_date=args[1],
            end_date=args[2], query=args[0], symbol=args[0])

    monkeypatch.setitem(interface.VENDOR_METHODS["get_news"], "longbridge_mcp", no_mcp)
    monkeypatch.setitem(interface.VENDOR_METHODS["get_news"], "longbridge", cli)
    try:
        result = interface.route_to_vendor(
            "get_news", "NVDA", "2026-07-07", "2026-07-13"
        )
    finally:
        set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))

    assert attempts == ["longbridge_mcp", "longbridge"]
    assert result.items[0].title == "Fallback headline"
    assert result.items[0].source_id.startswith("news_")


@pytest.mark.unit
def test_longbridge_news_vendor_registration_and_defaults():
    assert "longbridge_mcp" in interface.VENDOR_METHODS["get_news"]
    assert "longbridge" in interface.VENDOR_METHODS["get_news"]
    assert "longbridge" in interface.VENDOR_METHODS["get_global_news"]
    assert default_config.DEFAULT_CONFIG["data_vendors"]["news_data"].startswith(
        "longbridge_mcp, longbridge"
    )
