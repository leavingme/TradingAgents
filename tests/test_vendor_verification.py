from unittest import mock

import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.errors import NoMarketDataError
from tradingagents.dataflows.vendor_verification import VendorVerificationStore


VALID_OHLCV = "Date,Open,High,Low,Close,Volume\n2026-07-09,100,105,99,103,1000\n"


@pytest.mark.unit
def test_verification_store_keeps_latest_result_per_capability(tmp_path):
    store = VendorVerificationStore(tmp_path / "runs.db")

    store.record(
        vendor="westock",
        category="news_data",
        method="get_news",
        status="available",
        source="analysis",
        latency_ms=12,
    )
    latest = store.record(
        vendor="westock",
        category="news_data",
        method="get_news",
        status="no_data",
        source="manual",
        detail="no articles",
        latency_ms=18,
    )

    assert latest["status"] == "no_data"
    assert latest["source"] == "manual"
    assert latest["detail"] == "no articles"
    assert store.list_latest()["news_data"]["westock"]["latency_ms"] == 18


@pytest.mark.unit
def test_router_records_analysis_success(monkeypatch):
    recorder = mock.Mock()
    monkeypatch.setattr(interface, "_record_vendor_verification", recorder)
    monkeypatch.setattr(interface, "get_vendor", lambda category, method: "westock")

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_stock_data": {"westock": lambda *args: VALID_OHLCV}},
        clear=False,
    ):
        assert interface.route_to_vendor("get_stock_data", "AAPL", "2026-07-01", "2026-07-10") == VALID_OHLCV

    assert recorder.call_args.args[:5] == (
        "westock",
        "core_stock_apis",
        "get_stock_data",
        "available",
        "analysis",
    )


@pytest.mark.unit
def test_manual_verification_records_no_data(monkeypatch):
    recorder = mock.Mock(return_value={"status": "no_data", "source": "manual"})
    monkeypatch.setattr(interface, "_record_vendor_verification", recorder)

    def no_news(*args):
        raise NoMarketDataError("AAPL", detail="no articles")

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_news": {"westock": no_news}},
        clear=False,
    ):
        result = interface.verify_vendor("westock", "news_data")

    assert result == {"status": "no_data", "source": "manual"}
    assert recorder.call_args.args[:5] == (
        "westock",
        "news_data",
        "get_news",
        "no_data",
        "manual",
    )
