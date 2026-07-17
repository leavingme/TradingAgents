import json

import pytest

from tradingagents.dataflows import longbridge, longbridge_mcp
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.ohlcv_model import resolve_ohlcv_source_id


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
