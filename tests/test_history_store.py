import pytest
from pathlib import Path
from tradingagents.runtime import AnalysisRequest, run_analysis_once, history_store, RunHistoryStore
from tradingagents.runtime.events import AnalysisEvent

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
