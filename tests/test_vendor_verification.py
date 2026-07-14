from unittest import mock

import pytest

from tradingagents.dataflows import interface
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.evidence_models import (
    PredictionMarket,
    PredictionMarketFeed,
    PredictionOutcome,
    prediction_source_id,
)
from tradingagents.dataflows.vendor_verification import VendorVerificationStore
from tradingagents.runtime.audit_context import bind_run_id, reset_run_id
from tradingagents.runtime.history import RunHistoryStore


VALID_OHLCV = "Date,Open,High,Low,Close,Volume\n2026-07-09,100,105,99,103,1000\n"


@pytest.mark.unit
def test_vendor_audit_db_path_only_uses_unified_environment_variable(monkeypatch, tmp_path):
    from tradingagents.dataflows import vendor_verification as verification_module

    unified = tmp_path / "unified.db"
    monkeypatch.setenv("TRADINGAGENTS_DB", str(unified))
    monkeypatch.setenv("TRADINGAGENTS_WEBUI_DB", str(tmp_path / "legacy.db"))
    assert verification_module._default_db_path() == unified

    monkeypatch.delenv("TRADINGAGENTS_DB")
    monkeypatch.setattr(verification_module.Path, "home", lambda: tmp_path)
    assert verification_module._default_db_path() == tmp_path / ".tradingagents" / "runs.db"


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


@pytest.mark.unit
def test_run_audit_preserves_every_fallback_attempt(monkeypatch, tmp_path):
    from tradingagents.runtime import history as history_module
    from tradingagents.dataflows import vendor_verification as verification_module

    run_store = RunHistoryStore(tmp_path / "runs.db")
    run_store.create_run(
        "run-audit", "NVDA", "2026-07-10", "stock", ["market"], "test", 1
    )
    monkeypatch.setattr(history_module, "history_store", run_store)
    monkeypatch.setattr(
        verification_module,
        "vendor_verification_store",
        VendorVerificationStore(tmp_path / "runs.db"),
    )
    monkeypatch.setattr(interface, "get_vendor", lambda category, method: "primary, fallback")

    def unavailable(*args):
        raise NoMarketDataError("NVDA", detail="primary has no row")

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {
            "get_stock_data": {
                "primary": unavailable,
                "fallback": lambda *args: VALID_OHLCV,
            }
        },
        clear=False,
    ):
        token = bind_run_id("run-audit")
        try:
            result = interface.route_to_vendor(
                "get_stock_data", "NVDA", "2026-07-01", "2026-07-10"
            )
        finally:
            reset_run_id(token)

    assert result == VALID_OHLCV
    calls = run_store.get_vendor_calls("run-audit")
    assert [(call["attempt"], call["vendor"], call["status"], call["selected"]) for call in calls] == [
        (1, "primary", "no_data", 0),
        (2, "fallback", "available", 1),
    ]
    assert calls[0]["call_id"] == calls[1]["call_id"]
    assert '"NVDA"' in calls[0]["arguments_json"]
    assert calls[0]["error_type"] == "NoMarketDataError"
    assert calls[1]["result_hash"]
    assert calls[1]["symbol"] == "NVDA"
    assert calls[1]["agent"] == "Market Analyst"
    assert calls[1]["calculation_start"] == "2026-07-01"
    assert calls[1]["requested_end"] == "2026-07-10"
    assert calls[1]["data_latest_date"] == "2026-07-09"


@pytest.mark.unit
def test_analysis_stops_if_run_audit_cannot_be_written(monkeypatch, tmp_path):
    from tradingagents.runtime import history as history_module
    from tradingagents.dataflows import vendor_verification as verification_module

    run_store = RunHistoryStore(tmp_path / "runs.db")
    run_store.create_run("run-hard-gate", "NVDA", "2026-07-10", "stock", ["market"], "test", 1)
    monkeypatch.setattr(history_module, "history_store", run_store)
    monkeypatch.setattr(
        verification_module,
        "vendor_verification_store",
        VendorVerificationStore(tmp_path / "runs.db"),
    )
    monkeypatch.setattr(interface, "get_vendor", lambda category, method: "westock")
    monkeypatch.setattr(
        run_store,
        "add_vendor_call",
        mock.Mock(side_effect=RuntimeError("audit disk unavailable")),
    )

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_stock_data": {"westock": lambda *args: VALID_OHLCV}},
        clear=False,
    ):
        token = bind_run_id("run-hard-gate")
        try:
            with pytest.raises(RuntimeError, match="audit disk unavailable"):
                interface.route_to_vendor(
                    "get_stock_data", "NVDA", "2026-07-01", "2026-07-10"
                )
        finally:
            reset_run_id(token)


@pytest.mark.unit
def test_prediction_router_persists_invalid_and_selected_attempts(monkeypatch, tmp_path):
    from tradingagents.runtime import history as history_module
    from tradingagents.dataflows import vendor_verification as verification_module

    run_store = RunHistoryStore(tmp_path / "runs.db")
    run_store.create_run(
        "run-prediction-audit", "NVDA", "2026-07-14", "stock",
        ["news"], "test", 1,
    )
    monkeypatch.setattr(history_module, "history_store", run_store)
    monkeypatch.setattr(
        verification_module,
        "vendor_verification_store",
        VendorVerificationStore(tmp_path / "runs.db"),
    )
    monkeypatch.setattr(
        interface,
        "get_vendor",
        lambda category, method: "transport, invalid, polymarket",
    )

    def feed(vendor: str, probability: float) -> PredictionMarketFeed:
        event_id, market_id = "event-fed", "market-fed"
        observed_at = "2026-07-14T04:00:00+00:00"
        return PredictionMarketFeed(
            topic="Fed rate cut",
            observed_at=observed_at,
            requested_limit=3,
            markets=(PredictionMarket(
                source_id=prediction_source_id(
                    vendor=vendor, event_id=event_id, market_id=market_id
                ),
                event_id=event_id,
                event_title="Federal Reserve decision",
                market_id=market_id,
                condition_id="condition-fed",
                question="Will the Fed cut rates?",
                slug="will-the-fed-cut-rates",
                url="https://polymarket.com/event/will-the-fed-cut-rates",
                expires_at="2030-12-31T00:00:00+00:00",
                observed_at=observed_at,
                outcomes=(
                    PredictionOutcome("Yes", probability),
                    PredictionOutcome("No", 1 - probability),
                ),
                volume=50_000,
                one_week_probability_change=0.01,
                vendor=vendor,
            ),),
        )

    def transport_failure(*args):
        raise VendorUnavailableError("prediction transport failed")

    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_prediction_markets": {
            "transport": transport_failure,
            "invalid": lambda *args: feed("invalid", 1.2),
            "polymarket": lambda *args: feed("polymarket", 0.65),
        }},
        clear=False,
    ):
        token = bind_run_id("run-prediction-audit")
        try:
            result = interface.route_to_vendor(
                "get_prediction_markets", "Fed rate cut", 3
            )
        finally:
            reset_run_id(token)

    calls = run_store.get_vendor_calls("run-prediction-audit")
    assert [
        (call["attempt"], call["vendor"], call["status"], call["selected"])
        for call in calls
    ] == [
        (1, "transport", "unavailable", 0),
        (2, "invalid", "invalid", 0),
        (3, "polymarket", "available", 1),
    ]
    assert len({call["call_id"] for call in calls}) == 1
    assert result.markets[0].vendor_call_id == calls[2]["call_id"]
    assert result.markets[0].source_id.startswith("prediction_")
    assert calls[0]["error_type"] == "VendorUnavailableError"
    assert calls[1]["error_type"] == "NoMarketDataError"
    assert calls[2]["result_hash"]
