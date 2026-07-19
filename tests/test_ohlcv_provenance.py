import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from tradingagents.dataflows import longbridge, longbridge_mcp
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.ohlcv_cache import merge_and_write_ohlcv, read_cached_ohlcv
from tradingagents.dataflows.ohlcv_model import (
    batch_from_frame,
    resolve_ohlcv_provenance,
    resolve_ohlcv_source_id,
)


BAR = {
    "timestamp": "2026-07-10T04:00:00Z",
    "time": "2026-07-10T04:00:00Z",
    "open": "202.00",
    "high": "211.00",
    "low": "201.92",
    "close": "210.96",
    "volume": 148421001,
}


def _audit(tmp_path):
    return json.loads(
        (tmp_path / "ohlcv_audit.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )


@pytest.mark.unit
def test_longbridge_cli_writes_structured_provenance(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    monkeypatch.setattr(longbridge, "_run_cli_json_list", lambda *args, **kwargs: [BAR])

    result = longbridge.get_stock_data("NVDA", "2026-07-10", "2026-07-10")

    record = _audit(tmp_path)
    assert "2026-07-10" in result
    assert record["vendor"] == "longbridge"
    assert record["adapter_version"] == "longbridge_cli_ohlcv_v1"
    assert record["raw_timestamps"] == ["2026-07-10T04:00:00Z"]
    assert record["trading_dates"] == ["2026-07-10"]
    assert resolve_ohlcv_source_id(
        str(tmp_path), record["cache_key"], "2026-07-10"
    ) == (
        f"ohlcv:longbridge:{record['batch_id']}:2026-07-10"
    )


@pytest.mark.unit
def test_longbridge_mcp_writes_structured_provenance(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})

    class Client:
        tools = {"history_candlesticks_by_date"}

        def call_tool(self, name, args):
            return [BAR]

    monkeypatch.setattr(longbridge_mcp, "_client", Client)
    monkeypatch.setattr(
        longbridge_mcp, "_resolve_tool", lambda client, capability: "history_candlesticks_by_date"
    )

    result = longbridge_mcp.get_stock_data("NVDA", "2026-07-10", "2026-07-10")

    record = _audit(tmp_path)
    assert "2026-07-10" in result
    assert record["vendor"] == "longbridge_mcp"
    assert record["adapter_version"] == "longbridge_mcp_ohlcv_v1"
    assert record["raw_timestamps"] == ["2026-07-10T04:00:00Z"]


def test_range_only_legacy_audit_cannot_claim_exact_bar_provenance(tmp_path):
    (tmp_path / "ohlcv_audit.jsonl").write_text(
        json.dumps({
            "cache_key": "NVDA",
            "vendor": "legacy",
            "batch_id": "old-batch",
            "first_trading_date": "2026-07-01",
            "last_trading_date": "2026-07-10",
        }) + "\n",
        encoding="utf-8",
    )
    assert resolve_ohlcv_source_id(str(tmp_path), "NVDA", "2026-07-10") is None


def _cached_batch(vendor: str):
    frame = pd.DataFrame({
        "Date": pd.to_datetime(["2026-07-09", "2026-07-10"]),
        "Open": [200.0, 202.0],
        "High": [205.0, 211.0],
        "Low": [199.0, 201.92],
        "Close": [203.0, 210.96],
        "Volume": [1000, 2000],
    })
    return batch_from_frame(
        frame,
        symbol="NVDA.US",
        vendor=vendor,
        adapter_version=f"{vendor}_test_v1",
        timezone_semantics="exchange_trading_date",
        raw_timestamps=["2026-07-09", "2026-07-10"],
    )


@pytest.mark.unit
def test_shared_cache_requires_exact_vendor_provenance(tmp_path):
    merge_and_write_ohlcv(str(tmp_path), "NVDA_US", _cached_batch("longbridge"))

    matching = read_cached_ohlcv(
        str(tmp_path), "NVDA_US", "2026-07-09", "2026-07-10",
        expected_vendor="longbridge",
    )
    mismatched = read_cached_ohlcv(
        str(tmp_path), "NVDA_US", "2026-07-09", "2026-07-10",
        expected_vendor="longbridge_mcp",
    )

    assert matching is not None and len(matching) == 2
    assert mismatched is None
    assert resolve_ohlcv_provenance(
        str(tmp_path), "NVDA_US", ["2026-07-09", "2026-07-10"]
    ) == {
        "2026-07-09": {
            "vendor": "longbridge",
            "batch_id": _audit(tmp_path)["batch_id"],
        },
        "2026-07-10": {
            "vendor": "longbridge",
            "batch_id": _audit(tmp_path)["batch_id"],
        },
    }

    mixed_batch = _cached_batch("longbridge_mcp")
    merge_and_write_ohlcv(
        str(tmp_path),
        "NVDA_US",
        replace(mixed_batch, bars=(mixed_batch.bars[-1],)),
    )
    assert read_cached_ohlcv(
        str(tmp_path), "NVDA_US", "2026-07-09", "2026-07-10",
        expected_vendor="longbridge",
    ) is None
    assert read_cached_ohlcv(
        str(tmp_path), "NVDA_US", "2026-07-09", "2026-07-10",
        expected_vendor="longbridge_mcp",
    ) is None


@pytest.mark.unit
def test_vendor_cache_rejects_rows_without_exact_audit(tmp_path):
    frame = pd.DataFrame({
        "Date": ["2026-07-10"],
        "Open": [202.0],
        "High": [211.0],
        "Low": [201.92],
        "Close": [210.96],
        "Volume": [2000],
    })
    frame.to_csv(tmp_path / "NVDA_US.csv", index=False)

    assert read_cached_ohlcv(
        str(tmp_path), "NVDA_US", "2026-07-10", "2026-07-10",
        expected_vendor="longbridge",
    ) is None


@pytest.mark.unit
def test_expired_mcp_cannot_claim_cli_cache(monkeypatch, tmp_path):
    set_config({"data_cache_dir": str(tmp_path)})
    merge_and_write_ohlcv(str(tmp_path), "NVDA_US", _cached_batch("longbridge"))
    monkeypatch.setattr(
        longbridge_mcp,
        "_load_token",
        lambda: {
            "access_token": "sentinel-not-logged",
            "expiry": (
                datetime.now(timezone.utc) - timedelta(minutes=5)
            ).isoformat(),
        },
    )

    with pytest.raises(longbridge_mcp.MCPAuthError, match="expired"):
        longbridge_mcp.get_stock_data("NVDA", "2026-07-09", "2026-07-10")
