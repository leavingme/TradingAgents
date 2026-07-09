"""Westock date boundaries must include the requested/current trading day."""
import json

import pandas as pd
import pytest

import tradingagents.dataflows.stockstats_utils as su
import tradingagents.dataflows.westock as westock
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.ohlcv_cache import (
    merge_and_write_ohlcv,
    normalize_ohlcv_dates,
    read_cached_ohlcv,
    symbol_to_cache_key,
)


@pytest.mark.unit
def test_get_westock_data_includes_requested_end(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.run_westock",
        lambda *a, **k: json.dumps([
            {"date": "2025-05-08", "open": 1, "high": 1, "low": 1, "last": 1, "volume": 1},
            {"date": "2025-05-09", "open": 2, "high": 2, "low": 2, "last": 2, "volume": 2},
        ]),
    )

    out = westock.get_westock_data_online("AAPL", "2025-05-01", "2025-05-09")

    assert "to 2025-05-09" in out
    assert "2025-05-09" in out


@pytest.mark.unit
def test_load_ohlcv_requests_inclusive_end(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.is_westock_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "tradingagents.dataflows.symbol_utils.run_westock",
        lambda *a, **k: json.dumps([
            {"date": today, "open": 100, "high": 100, "low": 100, "last": 100, "volume": 1},
        ]),
    )

    out = su.load_ohlcv("AAPL", today)

    assert out["Date"].max().strftime("%Y-%m-%d") == today


@pytest.mark.unit
def test_hk_utc_daily_bar_normalizes_to_local_trading_date():
    df = pd.DataFrame(
        {
            "Date": ["2026-07-07T16:00:00Z"],
            "Open": [461.2],
            "High": [482.8],
            "Low": [460.6],
            "Close": [478.8],
            "Volume": [56278627],
        }
    )

    out = normalize_ohlcv_dates(df, "0700_HK")

    assert out["Date"].iloc[0].strftime("%Y-%m-%d") == "2026-07-08"


@pytest.mark.unit
def test_recent_cache_missing_requested_business_day_is_refreshed(tmp_path):
    cached = pd.DataFrame(
        {
            "Date": ["2026-07-06"],
            "Open": [459.0],
            "High": [479.8],
            "Low": [457.0],
            "Close": [464.8],
            "Volume": [39624917],
        }
    )
    merge_and_write_ohlcv(str(tmp_path), "0700_HK", cached)

    out = read_cached_ohlcv(str(tmp_path), "0700_HK", "2026-07-06", "2026-07-09")

    assert out is None


@pytest.mark.unit
def test_hk_leading_zero_symbols_share_one_cache_key():
    assert symbol_to_cache_key("0700.HK") == "0700_HK"
    assert symbol_to_cache_key("700.HK") == "0700_HK"
    assert symbol_to_cache_key("00700.HK") == "0700_HK"
    assert symbol_to_cache_key("000001.SZ") == "000001_SZ"


@pytest.mark.unit
def test_canonical_hk_cache_reads_legacy_unpadded_file(tmp_path):
    legacy_path = tmp_path / "700_HK.csv"
    legacy_path.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2026-07-08,461.2,482.8,460.6,478.8,56278627\n"
        "2026-07-09,479.0,485.0,471.6,472.2,9923630\n",
        encoding="utf-8",
    )

    out = read_cached_ohlcv(str(tmp_path), "0700_HK", "2026-07-08", "2026-07-09")

    assert out is not None
    assert out["Date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-08", "2026-07-09"]
