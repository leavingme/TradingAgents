# TradingAgents WebUI Implementation Plan

## Goal

Add a WebUI to TradingAgents while preserving the current CLI/TUI. The WebUI should reuse the same core analysis pipeline instead of duplicating CLI logic or importing the TradingAgents-CN backend wholesale.

## Current Architecture

The current TUI flow lives mainly in `cli/main.py`.

- User input is collected through the CLI.
- `TradingAgentsGraph` is constructed directly in `run_analysis()`.
- The CLI streams LangGraph chunks through `graph.graph.stream(...)`.
- Messages, tool calls, agent states, and report sections are pushed into the Node TUI renderer.
- Reports are written through the shared report writer in `tradingagents/reporting.py`.

The useful boundary is already visible: the TUI is just one renderer for a stream of analysis events. A WebUI should consume the same kind of stream.

## Design Principles

- Keep `tradingagents/` as the core library.
- Keep CLI/TUI working.
- Do not copy the full TradingAgents-CN backend; it is heavily coupled to its own MongoDB, Redis, auth, CN market data, and configuration model.
- Extract shared execution logic first, then build API/UI on top.
- Prefer simple infrastructure for the first version: FastAPI, Server-Sent Events, SQLite or file-backed task metadata.

## Phase 1: Extract Headless Analysis Runtime

Create a small runtime layer:

```text
tradingagents/runtime/
  __init__.py
  analysis_runner.py
  config_builder.py
  events.py
```

### `events.py`

Define structured event models:

```python
AnalysisEvent = {
    "type": "message | tool_call | agent_status | report_section | final | error",
    "run_id": str,
    "timestamp": str,
    "agent": str | None,
    "content": str | dict | None,
}
```

### `config_builder.py`

Move reusable config-building logic out of `cli/main.py` where possible.

Inputs should include:

- ticker
- analysis date
- asset type
- selected analysts
- LLM provider
- shallow/deep model
- research depth
- checkpoint settings
- result directory

### `analysis_runner.py`

Expose two APIs:

```python
def run_analysis_stream(request: AnalysisRequest) -> Iterator[AnalysisEvent]:
    ...

def run_analysis_once(request: AnalysisRequest) -> AnalysisResult:
    ...
```

Implementation should reuse the current CLI graph streaming logic:

- create `TradingAgentsGraph`
- resolve instrument context
- create initial state
- call `graph.graph.stream(...)`
- convert messages/tool calls/report updates into structured events
- write reports using `TradingAgentsGraph.save_reports()` or `tradingagents.reporting.write_report_tree`
- emit a final event containing decision and report path

## Phase 2: Update CLI/TUI to Use Runtime

Refactor `cli/main.py` so the TUI consumes `AnalysisEvent` objects from `run_analysis_stream()`.

The CLI should keep responsibility for:

- interactive prompts
- terminal rendering
- TUI-specific keyboard handling
- local display choices

The runtime should own:

- graph construction
- graph streaming
- event generation
- report writing

This reduces future drift between CLI and WebUI.

## Phase 3: Add Web API

Create:

```text
web/backend/
  main.py
  models.py
  task_store.py
  runner_worker.py
```

Recommended backend: FastAPI.

### API Shape

```text
POST /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/events
GET  /api/runs/{run_id}/report
POST /api/runs/{run_id}/cancel
```

### Behavior

- `POST /api/runs` validates input, creates a run record, starts background execution, and returns `run_id`.
- `GET /api/runs/{run_id}` returns status, progress, timestamps, selected config, and result paths.
- `GET /api/runs/{run_id}/events` streams events using Server-Sent Events.
- `GET /api/runs/{run_id}/report` returns the complete markdown report or a structured report object.
- `POST /api/runs/{run_id}/cancel` requests cancellation.

### Storage

For the first version, use SQLite or a local JSON/file-backed store.

Store:

- run id
- ticker
- analysis date
- asset type
- config snapshot
- status: `pending`, `running`, `completed`, `failed`, `cancelled`
- progress
- event log
- report path
- error message
- started/finished timestamps

Use Redis or a process queue only after the API surface is stable.

## Phase 4: Add Frontend

Create:

```text
web/frontend/
```

Recommended stack: Vite + React or Vite + Vue.

Core views:

- Run form
- Live run dashboard
- Agent timeline
- Message/tool-call log
- Report viewer
- Run history

The frontend should connect to:

```text
GET /api/runs/{run_id}/events
```

and update the UI from streamed events.

## Phase 5: Packaging and Commands

Add convenient commands:

```text
tradingagents analyze      # existing CLI/TUI
tradingagents web          # start WebUI backend
```

For development:

```text
uvicorn web.backend.main:app --reload
npm run dev
```

For production:

- serve the built frontend from FastAPI static files, or
- provide a Docker Compose setup with backend and frontend services.

## Testing Plan

Add tests for:

- config builder output
- event conversion from graph chunks
- report writing path
- API run creation
- SSE event streaming
- failed run status
- cancellation behavior

Keep at least one smoke test that runs a tiny or mocked graph end-to-end through the Web API.

## Risks

- The current CLI mixes execution, rendering, and persistence. Refactoring must be incremental.
- Long-running LLM/tool calls need cancellation and timeout handling.
- Streaming events should avoid exposing API keys or raw sensitive config.
- TUI and WebUI can drift unless both consume the same runtime event model.
- A full TradingAgents-CN backend copy would introduce unnecessary coupling and should be avoided.

## Recommended First Milestone

Build the smallest vertical slice:

1. Add `tradingagents/runtime/events.py`.
2. Add `tradingagents/runtime/analysis_runner.py` with `run_analysis_stream()`.
3. Add a FastAPI backend with `POST /api/runs` and `GET /api/runs/{run_id}/events`.
4. Add a minimal frontend page that starts one analysis and streams messages.
5. Keep reports on disk and link to `complete_report.md`.

After this works, refactor the existing TUI to consume the same runtime stream.

## Progress

- Done: headless runtime event/request/result models.
- Done: `run_analysis_stream()` / `run_analysis_once()` using the existing graph stream and shared report writer.
- Done: minimal FastAPI backend with run creation, status, SSE events, cancellation, and markdown report retrieval.
- Done: minimal static WebUI served by FastAPI; it starts one analysis, consumes SSE events, shows agent status, logs, run history, and loads the final report.
- Done: package metadata includes the `web` package, frontend static assets, and FastAPI/Uvicorn runtime dependencies.
- Done: `tradingagents web` starts the WebUI backend.
- Next: refactor CLI/TUI to consume runtime events, then add persisted run storage/history.
