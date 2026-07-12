import pytest
from pathlib import Path
from tradingagents.runtime import AnalysisRequest, run_analysis_once, history_store, RunHistoryStore
from tradingagents.runtime.events import AnalysisEvent
from unittest import mock

def test_history_store_crud(tmp_path: Path):
    db_file = tmp_path / "test_history.db"
    store = RunHistoryStore(db_path=db_file)

    # 1. Test create_run
    store.create_run(
        run_id="test_run_1",
        ticker="AAPL",
        analysis_date="2026-07-07",
        asset_type="stock",
        selected_analysts=("market", "news"),
        llm_provider="openai",
        research_depth=1,
    )

    run = store.get_run("test_run_1")
    assert run is not None
    assert run["run_id"] == "test_run_1"
    assert run["ticker"] == "AAPL"
    assert run["status"] == "pending"

    # 2. Test mark_started
    store.mark_started("test_run_1")
    run = store.get_run("test_run_1")
    assert run["status"] == "running"
    assert run["started_at"] is not None

    # 3. Test add_event and deduplication
    ev1 = AnalysisEvent(type="message", run_id="test_run_1", agent="Market Analyst", content="Ev1 content")
    store.add_event("test_run_1", ev1)
    
    # Try duplicate event
    store.add_event("test_run_1", ev1)

    run = store.get_run("test_run_1")
    assert len(run["events"]) == 1
    assert run["events"][0]["content"] == "Ev1 content"

    # 4. Test mark_finished
    store.mark_finished("test_run_1", "completed")
    run = store.get_run("test_run_1")
    assert run["status"] == "completed"
    assert run["finished_at"] is not None

    # 5. Test list_runs
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "test_run_1"


def test_analysis_runner_binds_run_id_to_vendor_audit(monkeypatch, tmp_path: Path):
    from tradingagents.runtime import analysis_runner, history as history_module
    from tradingagents.dataflows import interface
    from tradingagents.dataflows import vendor_verification as verification_module
    from tradingagents.dataflows.vendor_verification import VendorVerificationStore

    store = RunHistoryStore(tmp_path / "runner.db")
    monkeypatch.setattr(history_module, "history_store", store)
    monkeypatch.setattr(
        verification_module,
        "vendor_verification_store",
        VendorVerificationStore(tmp_path / "runner.db"),
    )
    monkeypatch.setattr(interface, "get_vendor", lambda category, method: "test_vendor")
    payload = "Date,Open,High,Low,Close,Volume\n2026-07-10,100,105,99,103,1000\n"

    def fake_impl(request):
        interface.route_to_vendor(
            "get_stock_data", "NVDA", "2026-07-01", "2026-07-10"
        )
        yield AnalysisEvent(
            type="run_completed",
            run_id=request.run_id,
            content={"decision": "Hold"},
        )

    monkeypatch.setattr(analysis_runner, "_run_analysis_stream_impl", fake_impl)
    with mock.patch.dict(
        interface.VENDOR_METHODS,
        {"get_stock_data": {"test_vendor": lambda *args: payload}},
        clear=False,
    ):
        request = AnalysisRequest(
            ticker="NVDA",
            analysis_date="2026-07-10",
            selected_analysts=("market",),
            run_id="runner-audit",
        )
        list(analysis_runner.run_analysis_stream(request))

    calls = store.get_vendor_calls("runner-audit")
    assert len(calls) == 1
    assert calls[0]["run_id"] == "runner-audit"
    assert calls[0]["selected"] == 1
