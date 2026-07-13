"""Westock news paths return structured reports and fall back cleanly."""

import json
import copy

import pytest

import tradingagents.default_config as default_config
import tradingagents.dataflows.westock_news as wnews
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.interface import route_to_vendor


@pytest.mark.unit
def test_global_news_uses_westock_when_available(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.run_westock",
        lambda *a, **k: json.dumps([
            {"news_title": "PAST EVENT", "source": "Westock", "publish_time": 1_746_400_000,
             "url": "https://example.com/past-event"}
        ]),
    )

    out = wnews.get_global_news_westock("2025-05-09", look_back_days=7, limit=10)

    assert out.scope == "global"
    assert out.items[0].title == "PAST EVENT"


@pytest.mark.unit
def test_global_news_westock_only_reports_no_data_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: False,
    )

    with pytest.raises(NoMarketDataError) as exc:
        wnews.get_global_news_westock("2025-05-09", look_back_days=7, limit=10)

    assert "westock-data CLI is not available" in str(exc.value)


@pytest.mark.unit
def test_news_falls_back_to_duckduckgo_only_when_configured(monkeypatch):
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))
    set_config({"data_vendors": {"news_data": "westock, duckduckgo"}})
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.duckduckgo_search.ddg_search",
        lambda *a, **k: [
            {
                "title": "Fallback headline",
                "summary": "Fallback summary",
                "publisher": "example.com",
                "link": "https://example.com/news",
                "pub_date": "2025-05-08",
            }
        ],
    )

    try:
        out = route_to_vendor("get_global_news", "2025-05-09", 7, 10)
    finally:
        set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))

    assert out.items[0].title == "Fallback headline"
    assert out.items[0].source_id.startswith("news_")


@pytest.mark.unit
def test_news_does_not_fallback_to_duckduckgo_when_not_configured(monkeypatch):
    set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))
    set_config({"data_vendors": {"news_data": "westock"}})
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: False,
    )
    ddg = lambda *a, **k: pytest.fail("DuckDuckGo should not be called")
    monkeypatch.setattr("tradingagents.dataflows.duckduckgo_search.ddg_search", ddg)

    try:
        with pytest.raises(NoMarketDataError) as exc:
            route_to_vendor("get_global_news", "2025-05-09", 7, 10)
    finally:
        set_config(copy.deepcopy(default_config.DEFAULT_CONFIG))

    assert "westock-data CLI is not available" in str(exc.value)
