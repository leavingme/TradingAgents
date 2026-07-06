import asyncio

from tradingagents.runtime import AnalysisEvent


def test_create_run_and_get_status(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(type="run_started", run_id=run_id, content={"ticker": request.ticker}),
        )
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="run_completed",
                run_id=run_id,
                content={"decision": "Hold", "report_path": "/tmp/report.md"},
            ),
        )
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(
                ticker="NVDA",
                analysis_date="2026-07-05",
                selected_analysts=["market"],
            )
        )
        status = await main.get_run(created["run_id"])
        return created, status

    created, status = asyncio.run(exercise())

    assert created["ticker"] == "NVDA"
    assert created["status"] == "completed"
    assert created["report_path"] == "/tmp/report.md"
    assert status["event_count"] == 2


def test_stream_run_events_replays_stored_events(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(type="message", run_id=run_id, content={"text": "hello"}),
        )
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="MSFT", analysis_date="2026-07-05")
        )
        response = await main.stream_run_events(created["run_id"])
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    body = asyncio.run(exercise())

    assert "event: message" in body
    assert '"text": "hello"' in body


def test_get_run_report_returns_markdown(monkeypatch, tmp_path):
    from web.backend import main

    report_path = tmp_path / "complete_report.md"
    report_path.write_text("# Report\n\nHold", encoding="utf-8")

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="run_completed",
                run_id=run_id,
                content={"decision": "Hold", "report_path": str(report_path)},
            ),
        )
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="AAPL", analysis_date="2026-07-05")
        )
        return await main.get_run_report(created["run_id"])

    response = asyncio.run(exercise())

    assert response.media_type == "text/markdown"
    assert response.body.decode("utf-8") == "# Report\n\nHold"


def test_web_index_serves_frontend_file():
    from web.backend import main

    response = asyncio.run(main.web_index())

    assert str(response.path).endswith("web/frontend/index.html")


def test_failed_run_status_is_recorded(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.add_event(
            run_id,
            AnalysisEvent(
                type="error",
                run_id=run_id,
                content={"error": "boom", "error_type": "RuntimeError"},
            ),
        )
        task_store.mark_finished(run_id, "failed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="TSLA", analysis_date="2026-07-05")
        )
        return await main.get_run(created["run_id"])

    status = asyncio.run(exercise())

    assert status["status"] == "failed"
    assert status["error"] == "boom"


def test_cancel_run_marks_record_cancelled(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        created = await main.create_run(
            main.RunCreateRequest(ticker="AMD", analysis_date="2026-07-05")
        )
        return await main.cancel_run(created["run_id"])

    cancelled = asyncio.run(exercise())

    assert cancelled["status"] == "cancelled"


def test_list_runs_returns_created_records(monkeypatch):
    from web.backend import main

    def fake_start_background_run(run_id, request, task_store):
        task_store.mark_started(run_id)
        task_store.mark_finished(run_id, "completed")

    monkeypatch.setattr(main, "start_background_run", fake_start_background_run)

    async def exercise():
        first = await main.create_run(
            main.RunCreateRequest(ticker="IBM", analysis_date="2026-07-05")
        )
        second = await main.create_run(
            main.RunCreateRequest(ticker="ORCL", analysis_date="2026-07-05")
        )
        runs = await main.list_runs()
        return first, second, runs

    first, second, runs = asyncio.run(exercise())
    ids = [run["run_id"] for run in runs]

    assert second["run_id"] in ids
    assert first["run_id"] in ids
    assert ids.index(second["run_id"]) < ids.index(first["run_id"])
