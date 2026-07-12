"""Westock date boundaries must include the requested/current trading day."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

import tradingagents.dataflows.stockstats_utils as su
import tradingagents.dataflows.westock as westock
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.ohlcv_cache import (
    clean_canonical_daily_bars,
    filter_completed_daily_bars,
    merge_and_write_ohlcv,
    normalize_ohlcv_dates,
    read_cached_ohlcv,
    symbol_to_cache_key,
    validate_canonical_daily_bars_for_write,
)
from tradingagents.dataflows.ohlcv_model import batch_from_frame


def _test_batch(frame, symbol="TEST", vendor="test"):
    return batch_from_frame(
        frame,
        symbol=symbol,
        vendor=vendor,
        adapter_version="test_v1",
        timezone_semantics="test_trading_date",
        raw_timestamps=[str(value) for value in frame["Date"]],
    )


@pytest.mark.unit
def test_default_ohlcv_chain_prefers_longbridge():
    assert DEFAULT_CONFIG["data_vendors"]["core_stock_apis"] == (
        "longbridge_mcp, longbridge, westock"
    )


@pytest.mark.unit
def test_get_westock_data_includes_requested_end(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
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
def test_load_ohlcv_excludes_still_forming_current_daily_bar(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    previous_completed = (pd.Timestamp.today() - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    monkeypatch.setattr(
        "tradingagents.dataflows.interface.route_to_vendor",
        lambda *a, **k: (
            "Date,Open,High,Low,Close,Volume\n"
            f"{previous_completed},99,99,99,99,1\n"
            f"{today},100,100,100,100,1\n"
        ),
    )

    out = su.load_ohlcv("AAPL", today)

    assert out["Date"].max().strftime("%Y-%m-%d") == previous_completed


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
def test_equity_cache_removes_weekend_shifted_duplicate():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2025-11-30", "2025-12-01", "2025-12-02"]),
            "Open": [174.76, 174.76, 181.76],
            "High": [180.30, 180.30, 185.66],
            "Low": [173.68, 173.68, 180.00],
            "Close": [179.92, 179.92, 181.46],
            "Volume": [188130955, 188130955, 182632230],
        }
    )

    out = clean_canonical_daily_bars(frame, "NVDA_US")

    assert out["Date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-12-01",
        "2025-12-02",
    ]


@pytest.mark.unit
def test_cache_removes_holiday_shifted_duplicate_and_persists_migration(tmp_path):
    polluted = pd.DataFrame(
        {
            "Date": ["2025-12-24", "2025-12-25", "2025-12-26"],
            "Open": [187.94, 189.92, 189.92],
            "High": [188.91, 192.69, 192.69],
            "Low": [186.59, 188.00, 188.00],
            "Close": [188.61, 190.53, 190.53],
            "Volume": [65528545, 139740292, 139740292],
        }
    )

    migrated = clean_canonical_daily_bars(
        normalize_ohlcv_dates(polluted, "NVDA_US"), "NVDA_US"
    )
    merge_and_write_ohlcv(str(tmp_path), "NVDA_US", _test_batch(migrated, "NVDA.US"))
    cached = pd.read_csv(tmp_path / "NVDA_US.csv")

    assert cached["Date"].tolist() == ["2025-12-24", "2025-12-26"]


@pytest.mark.unit
def test_cache_write_rejects_shifted_dates_without_modifying_existing_file(tmp_path):
    valid = pd.DataFrame(
        {
            "Date": ["2025-12-01"],
            "Open": [174.76],
            "High": [180.30],
            "Low": [173.68],
            "Close": [179.92],
            "Volume": [188130955],
        }
    )
    merge_and_write_ohlcv(str(tmp_path), "NVDA_US", _test_batch(valid, "NVDA.US"))
    before = (tmp_path / "NVDA_US.csv").read_bytes()
    shifted = valid.copy()
    shifted["Date"] = "2025-11-30"

    with pytest.raises(ValueError, match="shifted trading dates"):
        merge_and_write_ohlcv(
            str(tmp_path), "NVDA_US", _test_batch(shifted, "NVDA.US")
        )

    assert (tmp_path / "NVDA_US.csv").read_bytes() == before


@pytest.mark.unit
def test_cache_write_rejects_invalid_ohlc():
    invalid = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-07-10"]),
            "Open": [100.0],
            "High": [90.0],
            "Low": [95.0],
            "Close": [100.0],
            "Volume": [1],
        }
    )

    with pytest.raises(ValueError, match="OHLC"):
        validate_canonical_daily_bars_for_write(invalid, "NVDA_US")


@pytest.mark.unit
def test_cache_write_rejects_unstructured_dataframe(tmp_path):
    frame = pd.DataFrame(
        {"Date": ["2026-07-10"], "Open": [1], "High": [1], "Low": [1],
         "Close": [1], "Volume": [1]}
    )

    with pytest.raises(TypeError, match="only OHLCVBatch"):
        merge_and_write_ohlcv(str(tmp_path), "NVDA_US", frame)


@pytest.mark.unit
def test_cache_write_records_batch_provenance(tmp_path):
    frame = pd.DataFrame(
        {"Date": ["2026-07-10"], "Open": [202], "High": [211],
         "Low": [201.92], "Close": [210.96], "Volume": [148421001]}
    )
    batch = _test_batch(frame, "NVDA.US", "longbridge_mcp")

    merge_and_write_ohlcv(str(tmp_path), "NVDA_US", batch)

    records = [json.loads(line) for line in
               (tmp_path / "ohlcv_audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[0]["vendor"] == "longbridge_mcp"
    assert records[0]["batch_id"] == batch.batch_id
    assert records[0]["raw_timestamps"] == ["2026-07-10"]


@pytest.mark.unit
def test_zero_volume_identical_daily_bars_are_not_deduplicated():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2026-07-08", "2026-07-09"]),
            "Open": [10.0, 10.0],
            "High": [10.0, 10.0],
            "Low": [10.0, 10.0],
            "Close": [10.0, 10.0],
            "Volume": [0, 0],
        }
    )

    out = clean_canonical_daily_bars(frame, "ILLIQUID_US")

    assert len(out) == 2


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
    merge_and_write_ohlcv(str(tmp_path), "0700_HK", _test_batch(cached, "0700.HK"))

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


@pytest.mark.unit
def test_hk_current_daily_bar_is_excluded_before_close_and_included_after_close():
    frame = pd.DataFrame(
        {
            "Date": ["2026-07-09", "2026-07-10"],
            "Open": [479.0, 472.8],
            "High": [485.0, 473.6],
            "Low": [467.2, 458.8],
            "Close": [469.6, 460.2],
            "Volume": [42402152, 40440298],
        }
    )

    before_close = filter_completed_daily_bars(
        frame,
        "0700_HK",
        datetime(2026, 7, 10, 15, 0, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )
    after_close = filter_completed_daily_bars(
        frame,
        "0700_HK",
        datetime(2026, 7, 10, 16, 20, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )

    assert before_close["Date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-09"]
    assert after_close["Date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-07-09", "2026-07-10"]


@pytest.mark.unit
def test_cache_merge_replaces_partial_bar_and_keeps_only_canonical_ohlcv(tmp_path):
    partial = pd.DataFrame(
        {
            "Date": ["2026-07-09"],
            "Open": [479.0],
            "High": [485.0],
            "Low": [471.6],
            "Close": [472.2],
            "Volume": [9923630],
            "amount": [999999999999999],
            "exchange": [0.11],
        }
    )
    final = pd.DataFrame(
        {
            "Date": ["2026-07-09"],
            "Open": [479.0],
            "High": [485.0],
            "Low": [467.2],
            "Close": [469.6],
            "Volume": [42402152],
        }
    )

    # Historical dates are used so the wall clock cannot classify the fixture
    # as a still-forming live candle.
    merge_and_write_ohlcv(str(tmp_path), "0700_HK", _test_batch(partial, "0700.HK"))
    merge_and_write_ohlcv(str(tmp_path), "0700_HK", _test_batch(final, "0700.HK"))
    cached = pd.read_csv(tmp_path / "0700_HK.csv")

    assert cached.columns.tolist() == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert cached.to_dict("records") == [{
        "Date": "2026-07-09",
        "Open": 479.0,
        "High": 485.0,
        "Low": 467.2,
        "Close": 469.6,
        "Volume": 42402152,
    }]
