from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
from unittest import mock

import pandas as pd
import pytest

from tradingagents.agents.utils.technical_indicators_tools import get_indicators
from tradingagents.dataflows import interface, ohlcv_cache, stockstats_utils, westock
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.data_validation import (
    IndicatorBatch,
    IndicatorObservation,
    NormalizedIndicatorData,
    validate_indicator_batch,
)
from tradingagents.dataflows import longbridge_mcp


def _ohlcv_frame() -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-07-10", periods=800)
    close = pd.Series(range(800), dtype="float64") * 0.1 + 100
    return pd.DataFrame({
        "Date": dates,
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": pd.Series(range(800), dtype="float64") + 1000,
    })


@pytest.mark.unit
def test_westock_batch_loads_ohlcv_once_and_validates_every_series(monkeypatch):
    calls = 0

    def load_once(symbol, curr_date):
        nonlocal calls
        calls += 1
        return _ohlcv_frame()

    monkeypatch.setattr(westock, "load_ohlcv", load_once)
    batch = westock.get_stock_stats_indicators_batch(
        "NVDA", ["rsi", "macd", "atr", "close_50_sma"], "2026-07-10", 60
    )
    validated, failures = validate_indicator_batch(batch)

    assert calls == 1
    assert failures == {}
    assert {item.indicator for item in validated.series} == {
        "rsi", "macd", "atr", "close_50_sma"
    }
    assert validated.latest_ohlcv_date == "2026-07-10"
    assert validated.reference_close == pytest.approx(179.9)


@pytest.mark.unit
def test_batch_values_match_existing_single_indicator_path(monkeypatch):
    monkeypatch.setattr(westock, "load_ohlcv", lambda *args: _ohlcv_frame())
    requested = ["rsi", "macd", "atr", "boll_ub"]
    batch = westock.get_stock_stats_indicators_batch(
        "NVDA", requested, "2026-07-10", 60
    )

    for item in batch.series:
        existing = westock.get_stock_stats_indicators_window(
            "NVDA", item.indicator, "2026-07-10", 60
        )
        existing_values = {
            line.split(": ", 1)[0]: float(line.split(": ", 1)[1])
            for line in existing.splitlines()
            if line.startswith("2026-") and "N/A" not in line
        }
        assert item.observations[-1].value == pytest.approx(
            existing_values[item.observations[-1].date.strftime("%Y-%m-%d")],
            rel=1e-12,
        )


@pytest.mark.unit
def test_ohlcv_cache_fill_is_singleflight(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    cached = {"frame": None}
    active = 0
    max_active = 0
    calls = 0
    guard = threading.Lock()
    frame = _ohlcv_frame().tail(30).copy()

    monkeypatch.setattr(
        ohlcv_cache,
        "read_cached_ohlcv",
        lambda *args: None if cached["frame"] is None else cached["frame"].copy(),
    )

    def fetch(*args):
        nonlocal active, max_active, calls
        with guard:
            active += 1
            calls += 1
            max_active = max(max_active, active)
        time.sleep(0.03)
        cached["frame"] = frame.copy()
        with guard:
            active -= 1
        return frame.to_csv(index=False)

    monkeypatch.setattr(interface, "route_to_vendor", fetch)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(
            lambda _: stockstats_utils.load_ohlcv("NVDA", "2026-07-10"),
            range(6),
        ))

    assert calls == 1
    assert max_active == 1
    assert all(not result.empty for result in results)


@pytest.mark.unit
def test_tool_passes_all_indicators_in_one_batch_call():
    with mock.patch(
        "tradingagents.agents.utils.technical_indicators_tools.route_indicator_batch",
        return_value="batch",
    ) as route:
        result = get_indicators.func(
            symbol="NVDA",
            indicator=["RSI", "macd", "rsi"],
            curr_date="2026-07-10",
            look_back_days=60,
            **{"/invoke": True},
        )

    assert result == "batch"
    route.assert_called_once_with(
        "NVDA", ["rsi", "macd", "rsi"], "2026-07-10", 60
    )


@pytest.mark.unit
def test_batch_router_falls_back_only_missing_indicators(monkeypatch):
    rsi = NormalizedIndicatorData(
        indicator="rsi",
        analysis_date=pd.Timestamp("2026-07-10"),
        observations=(IndicatorObservation(pd.Timestamp("2026-07-10"), 55.0),),
        bars=1,
        source_text="2026-07-10: 55",
    )
    partial = IndicatorBatch(
        symbol="NVDA.US",
        analysis_date="2026-07-10",
        vendor="westock",
        requested_indicators=("rsi", "atr"),
        series=(rsi,),
        latest_ohlcv_date="2026-07-10",
        reference_close=179.9,
        calculation_start="2023-07-11",
        failures=(("atr", "local calculation failed"),),
    )
    atr = NormalizedIndicatorData(
        indicator="atr",
        analysis_date=pd.Timestamp("2026-07-10"),
        observations=(IndicatorObservation(pd.Timestamp("2026-07-10"), 2.5),),
        bars=1,
        source_text="2026-07-10: 2.5",
    )
    fallback = IndicatorBatch(
        symbol="NVDA.US",
        analysis_date="2026-07-10",
        vendor="longbridge_mcp",
        requested_indicators=("atr",),
        series=(atr,),
        latest_ohlcv_date="2026-07-10",
        reference_close=179.9,
        calculation_start="2023-07-11",
    )
    calls = []

    def routed(method, *args, **kwargs):
        calls.append((method, args, kwargs))
        if method == "get_indicators_batch":
            if kwargs.get("_exclude_vendors") == {"westock"}:
                assert args[1] == ("atr",)
                return fallback
            return partial
        raise AssertionError("single-indicator fallback should not be needed")

    monkeypatch.setattr(interface, "route_to_vendor", routed)
    result = interface.route_indicator_batch(
        "NVDA", ["rsi", "atr"], "2026-07-10", 60
    )

    assert "2026-07-10: 55" in result
    assert "2026-07-10: 2.5" in result
    assert [call[0] for call in calls] == [
        "get_indicators_batch", "get_indicators_batch"
    ]


@pytest.mark.unit
def test_longbridge_mcp_batch_uses_one_quant_request(monkeypatch):
    timestamps = [
        int(pd.Timestamp(day).timestamp() * 1000)
        for day in ("2026-07-09T04:00:00Z", "2026-07-10T04:00:00Z")
    ]
    raw = {
        "chart_json": json.dumps({
            "series_graphs": {
                "0": {"Plot": {"title": "rsi", "series": [50.0, 55.0]}},
                "1": {"Plot": {"title": "atr", "series": [2.0, 2.5]}},
                "2": {"Plot": {"title": "__reference_close", "series": [178.0, 179.9]}},
            }
        }),
        "events_json": json.dumps([
            {"BarStart": {"timestamp": timestamps[0]}},
            {"Plot": {"series_index": 0}},
            {"BarStart": {"timestamp": timestamps[1]}},
            "HistoryEnd",
        ]),
    }
    client = mock.Mock()
    client.tools = {"quant_run": {}}
    client.list_tools.return_value = [{"name": "quant_run"}]
    client.call_tool.return_value = raw
    monkeypatch.setattr(longbridge_mcp, "_client", lambda: client)

    batch = longbridge_mcp.get_indicators_batch(
        "NVDA", ["rsi", "atr"], "2026-07-10", 60
    )
    validated, failures = validate_indicator_batch(batch)

    assert failures == {}
    assert {item.indicator for item in validated.series} == {"rsi", "atr"}
    assert client.call_tool.call_count == 1
    arguments = client.call_tool.call_args.args[1]
    assert 'plot(ta.rsi(close, 14), "rsi")' in arguments["script"]
    assert 'plot(ta.atr(14), "atr")' in arguments["script"]
    assert 'plot(close, "__reference_close")' in arguments["script"]


@pytest.mark.unit
def test_longbridge_mcp_batch_normalizes_hk_timestamp_to_trading_date(monkeypatch):
    timestamp = int(pd.Timestamp("2026-07-07T16:00:00Z").timestamp() * 1000)
    raw = {
        "chart_json": json.dumps({
            "series_graphs": {
                "0": {"Plot": {"title": "rsi", "series": [55.0]}},
                "1": {"Plot": {"title": "__reference_close", "series": [478.8]}},
            }
        }),
        "events_json": json.dumps([
            {"BarStart": {"timestamp": timestamp}}, "HistoryEnd"
        ]),
    }
    client = mock.Mock()
    client.tools = {"quant_run": {}}
    client.list_tools.return_value = [{"name": "quant_run"}]
    client.call_tool.return_value = raw
    monkeypatch.setattr(longbridge_mcp, "_client", lambda: client)

    batch = longbridge_mcp.get_indicators_batch(
        "700.HK", ["rsi"], "2026-07-08", 30
    )
    validated, failures = validate_indicator_batch(batch)

    assert failures == {}
    assert validated.latest_ohlcv_date == "2026-07-08"
    assert validated.series[0].observations[0].date == pd.Timestamp("2026-07-08")


@pytest.mark.unit
def test_batch_rejects_more_than_eight_indicators():
    with pytest.raises(ValueError, match="At most 8"):
        interface.route_indicator_batch(
            "NVDA", [f"indicator-{index}" for index in range(9)], "2026-07-10"
        )
