"""Westock news paths return structured reports and fall back cleanly."""

import json
import copy

import pytest

import tradingagents.default_config as default_config
import tradingagents.dataflows.westock_news as wnews
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows import interface
from tradingagents.runtime.audit_context import (
    bind_analysis_mode,
    bind_information_cutoff,
    bind_run_id,
    reset_analysis_mode,
    reset_information_cutoff,
    reset_run_id,
)


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


@pytest.mark.unit
def test_point_in_time_runtime_caps_external_vendor_dates_at_cutoff():
    run_token = bind_run_id("point-in-time-news")
    mode_token = bind_analysis_mode("point_in_time")
    cutoff_token = bind_information_cutoff("2026-07-10T12:30:00-04:00")
    try:
        assert interface._runtime_external_time_args(
            "get_news", ("NVDA", "2026-07-01", "2026-07-07")
        ) == ("NVDA", "2026-07-04", "2026-07-10")
        assert interface._runtime_external_time_args(
            "get_global_news", ("2026-07-07", 7, 20)
        ) == ("2026-07-10", 7, 20)
        assert interface._runtime_external_time_args(
            "get_macro_indicators", ("cpi", "2026-07-07", 365)
        ) == ("cpi", "2026-07-10", 365)
    finally:
        reset_information_cutoff(cutoff_token)
        reset_analysis_mode(mode_token)
        reset_run_id(run_token)


@pytest.mark.unit
def test_news_runtime_window_uses_utc_cutoff_date_across_timezone_boundary():
    run_token = bind_run_id("timezone-news")
    mode_token = bind_analysis_mode("point_in_time")
    cutoff_token = bind_information_cutoff("2026-07-10T23:30:00-04:00")
    try:
        assert interface._runtime_external_time_args(
            "get_global_news", ("2026-07-10", 7, 20)
        ) == ("2026-07-11", 7, 20)
        # FRED vintages use the cutoff's own calendar date and then apply their
        # conservative prior-day policy inside the vendor adapter.
        assert interface._runtime_external_time_args(
            "get_macro_indicators", ("cpi", "2026-07-10", 365)
        ) == ("cpi", "2026-07-10", 365)
    finally:
        reset_information_cutoff(cutoff_token)
        reset_analysis_mode(mode_token)
        reset_run_id(run_token)
