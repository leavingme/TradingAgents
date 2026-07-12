import copy
import json
from datetime import datetime, timezone
from unittest import mock

import pytest

import tradingagents.dataflows.config as config_module
import tradingagents.default_config as default_config
from tradingagents.dataflows import interface
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.data_validation import validate_indicator_result
from tradingagents.dataflows.data_validation import normalize_indicator_result
from tradingagents.dataflows.errors import NoUsableTechnicalIndicatorError
from tradingagents.dataflows.indicator_requirements import (
    effective_indicator_lookback_days,
    minimum_indicator_lookback_days,
)
from tradingagents.dataflows.longbridge_mcp import _summarize_quant_payload


OHLCV = "Date,Open,High,Low,Close,Volume\n2026-07-10,455,465,450,460,1000\n"


@pytest.fixture(autouse=True)
def reset_config():
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("indicator", "payload", "detail"),
    [
        ("rsi", "2026-07-10: 101", "RSI"),
        ("atr", "2026-07-10: -1", "ATR"),
        ("vwma", "2026-07-09: 0\n2026-07-10: 361966.91", "zero ratio"),
        ("close_50_sma", "2026-07-11: 460", "analysis date"),
    ],
)
def test_invalid_indicator_values_are_rejected(indicator, payload, detail):
    result = validate_indicator_result(payload, indicator, "2026-07-10", reference_close=460)
    assert not result.is_valid
    assert detail in result.detail


@pytest.mark.unit
def test_indicator_output_bars_include_an_implicit_warmup_window():
    payload = (
        "Technical Indicator Report for 0700.HK\n"
        "Indicator: VWMA\nReport Date: 2026-07-10\n"
        "2026-07-10: 460\n"
        "  vwma: last=+460.00  range=[+450.00, +470.00]  bars=10"
    )
    result = validate_indicator_result(payload, "vwma", "2026-07-10", reference_close=460)
    assert result.is_valid


@pytest.mark.unit
@pytest.mark.parametrize(
    ("indicator", "minimum"),
    [
        ("close_200_sma", 307),
        ("close_50_sma", 82),
        ("macd", 60),
        ("macdh", 60),
        ("rsi", 28),
    ],
)
def test_indicator_minimum_windows_are_deterministic(indicator, minimum):
    assert minimum_indicator_lookback_days(indicator) == minimum
    assert effective_indicator_lookback_days(indicator, 30) == max(30, minimum)


@pytest.mark.unit
def test_router_expands_indicator_window_before_calling_every_vendor():
    set_config({
        "data_vendors": {
            "core_stock_apis": "prices",
            "technical_indicators": "primary",
        }
    })
    captured = []

    def indicator_vendor(*args):
        captured.append(args)
        return "2026-07-10: 460"

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_stock_data": {"prices": lambda *args: OHLCV},
            "get_indicators": {"primary": indicator_vendor},
        },
        clear=False,
    ):
        interface.route_to_vendor(
            "get_indicators", "NVDA", "close_200_sma", "2026-07-10", 30
        )

    assert captured[0][3] == 307


@pytest.mark.unit
def test_repeated_price_indicator_series_is_rejected():
    payload = "\n".join(
        f"2026-06-{day:02d}: 460" for day in range(1, 12)
    )
    result = validate_indicator_result(payload, "vwma", "2026-07-10", reference_close=460)
    assert not result.is_valid
    assert "repeated" in result.detail


@pytest.mark.unit
def test_order_of_magnitude_jump_is_rejected():
    payload = "2026-07-08: 100\n2026-07-09: 1200\n2026-07-10: 1100"
    result = validate_indicator_result(payload, "vwma", "2026-07-10", reference_close=460)
    assert not result.is_valid
    assert "order of magnitude" in result.detail


@pytest.mark.unit
def test_mcp_payload_preserves_dated_observations():
    timestamps = [
        int(datetime(2026, 7, day, tzinfo=timezone.utc).timestamp() * 1000)
        for day in (8, 9, 10)
    ]
    raw = {
        "chart_json": json.dumps({
            "series_graphs": {
                "0": {"Plot": {"title": "VWMA", "series": [455.0, 458.0, 460.0]}}
            }
        }),
        "events_json": json.dumps([
            {"BarStart": {"timestamp": timestamp}} for timestamp in timestamps
        ]),
    }
    result = _summarize_quant_payload(raw)
    assert "2026-07-08: 455.0" in result
    assert "2026-07-10: 460.0" in result
    assert "bars=3" in result


@pytest.mark.unit
def test_multi_series_summaries_do_not_corrupt_observation_pairing():
    payload = (
        "2026-07-09: 450\n2026-07-10: 455\n"
        "lower: last=+455.00  range=[+450.00, +455.00]  bars=20\n"
        "2026-07-09: 470\n2026-07-10: 475\n"
        "upper: last=+475.00  range=[+470.00, +475.00]  bars=20"
    )
    normalized = normalize_indicator_result(payload, "boll", "2026-07-10")
    assert [observation.value for observation in normalized.observations] == [450, 455, 470, 475]
    assert normalized.summary_values == (455, 450, 455, 475, 470, 475)


@pytest.mark.unit
def test_invalid_vwma_falls_back_to_next_vendor():
    set_config({
        "data_vendors": {
            "core_stock_apis": "prices",
            "technical_indicators": "primary,fallback",
        }
    })
    invalid = "2026-07-09: 0\n2026-07-10: 361966.91"
    valid = "2026-07-09: 455\n2026-07-10: 460"
    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_stock_data": {"prices": lambda *args: OHLCV},
            "get_indicators": {
                "primary": lambda *args: invalid,
                "fallback": lambda *args: valid,
            },
        },
        clear=False,
    ):
        result = interface.route_to_vendor("get_indicators", "0700.HK", "vwma", "2026-07-10", 30)
    assert result == valid


@pytest.mark.unit
def test_all_invalid_indicators_raise_hard_failure():
    set_config({"data_vendors": {"technical_indicators": "primary,fallback"}})
    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_indicators": {
                "primary": lambda *args: "2026-07-10: 101",
                "fallback": lambda *args: "2026-07-10: -1",
            },
        },
        clear=False,
    ):
        with pytest.raises(NoUsableTechnicalIndicatorError):
            interface.route_to_vendor("get_indicators", "0700.HK", "rsi", "2026-07-10", 30)
