"""Westock news paths return structured reports and fall back cleanly."""

import json

import pytest

import tradingagents.dataflows.westock_news as wnews


@pytest.mark.unit
def test_global_news_uses_westock_when_available(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.run_westock",
        lambda *a, **k: json.dumps([
            {"news_title": "PAST EVENT", "source": "Westock", "publish_time": 1_746_400_000}
        ]),
    )

    out = wnews.get_global_news_westock("2025-05-09", look_back_days=7, limit=10)

    assert "Global Market News" in out
    assert "PAST EVENT" in out


@pytest.mark.unit
def test_global_news_falls_back_to_ddg(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.duckduckgo_search.ddg_search",
        lambda *a, **k: [],
    )

    out = wnews.get_global_news_westock("2025-05-09", look_back_days=7, limit=10)

    assert "No global news found" in out
