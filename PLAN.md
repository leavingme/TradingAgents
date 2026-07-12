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
- Done (Phase 2): CLI/TUI `run_analysis()` refactored to consume `run_analysis_stream()` events.
  - `AnalysisRequest` extended with `google_thinking_level`, `openai_reasoning_effort`, `anthropic_effort`.
  - `config_builder.py` wires the new fields into the graph config.
  - Wall-time tracker driven by `agent_status` events instead of raw chunks.
  - `StatsCallbackHandler` is injectable through runtime callbacks; CLI/TUI and WebUI consume live `stats` events.
- Done: `TaskStore` upgraded from in-memory to SQLite persistence (`~/.tradingagents/runs.db`).
  - Runs and events persisted across server restarts.
  - Interrupted runs auto-recovered to `failed` on startup.
  - `list()` returns up to 100 runs from DB.
  - Past-run SSE replay reads from events table.
- Done: Premium dark-mode frontend (glassmorphism, Inter font, marked.js, animated agent status dots).
- Done: WebUI run flow now mirrors the CLI startup sequence for run-critical
  configuration: ticker/date/asset, report language, analyst selection,
  research depth, provider, backend URL, quick/deep models, and provider-specific
  reasoning/thinking knobs.
- Done: WebUI has a separate Settings page (`#settings`), URL-addressable run
  history (`#run=<run_id>`), UI language separate from report language, live SSE
  heartbeat/reconnect behavior, CLI-style Team / Agent / Status progress table,
  live report-section rendering, and report-section switching.
- Done: Settings page shows server-side provider API key status without exposing
  secret values, and report language supports the same built-in/custom language
  choices as the CLI.
- Done: Global macro routing for Hong Kong (.HK) and China (A-shares) equities, automatically mapping CPI/GDP/interest rate friendly aliases to FRED series IDs.
- Done: Automatic window expansion for lagging international macro series, ensuring a minimum of 1095 days lookback to prevent "no observations in window" exceptions.
- Done: Parameter sanitizer and robustness against tool call parameter hallucinations, guarding all core data tool signatures with **kwargs to absorb extra keys (e.g. /invoke) generated during interleaved thinking cycles.
- Done: Parallelization of basic analyst nodes (Market, Sentiment, News, Fundamentals) using sandboxed subgraphs, reducing Shallow runtimes from 11 minutes to under 5 minutes (~4.3 minutes).
- Done: Runtime agent workflow events are monotonic and deduplicated: cumulative graph snapshots no longer restart completed agents or republish unchanged report sections, and Research/Portfolio hand-offs expose complete pending → in-progress → completed lifecycles.
- Done: Added read-only Bird X/Twitter social vendor with structured `SocialFeed`/`SocialPost` adaptation, deterministic date/spam/duplicate validation, vendor routing and health UI, and Sentiment Analyst integration.

## CLI / WebUI Coverage Matrix (2026-07-11)

| CLI capability | WebUI/API coverage |
|---|---|
| Step 1 ticker input with suffix support | Covered by Run page ticker selector plus `Custom ticker...` input for arbitrary symbols. |
| Asset type detection/selection | Covered by explicit `Asset Type` selector (`stock`/`crypto`). |
| Step 2 analysis date | Covered by Run page date picker. |
| Step 3 report output language | Covered by Settings `Report Language`, including CLI's custom language input; separate `UI Language` only affects WebUI chrome. |
| Step 4 analyst selection | Covered by Run page analyst toggles. |
| Step 5 research depth | Covered by Settings `Analysis Depth` using CLI-equivalent choices: Shallow=1, Medium=3, Deep=5. |
| Step 6 LLM provider / backend URL | Covered by Settings `LLM Provider` and optional `Backend URL`. |
| Step 7 quick/deep thinking agents | Covered by Settings `Quick Model` and `Deep Model`, with provider presets. |
| Step 8 provider-specific thinking/reasoning config | Covered by Settings provider-specific controls for Google, OpenAI, and Anthropic. |
| Live Team / Agent / Status progress | Covered by Web Agent panel using CLI team grouping and animated `in_progress`. |
| Message/tool stream | Covered by SSE Live Stream panel. |
| LLM/tool/token stats | Covered by runtime `stats` events and Web header counters. |
| Incremental report sections | Covered by live report viewer; report sections are switchable from the report selector. |
| Final complete report | Covered by `/api/runs/{run_id}/report` and final report load button. |
| Run cancellation | Covered by Cancel button and `run_cancelled` events. |
| Run history / replay | Covered by SQLite-backed run history and `#run=<run_id>` deep links. |

Known differences:

- Web does not prompt for or persist provider API keys in the browser. Instead,
  `/api/config/env-status` reports whether the server-side environment variables
  required by each provider are configured.

## Hardening Update (2026-07-11)

- Added workspace-local DB fallback: if `~/.tradingagents/runs.db` is not writable in a managed/sandboxed environment, the WebUI uses `.tradingagents/runs.db` under the current workspace. `.tradingagents/` is gitignored.
- Added `run_cancelled` runtime/Web event so cancellation is not represented as a failure event.
- Trimmed runtime-only `final_state` from Web API `run_completed` events before persistence/SSE so LangChain objects do not break JSON serialization and clients do not receive oversized graph state.
- Added a regression test covering Web-safe persistence of `run_completed` events that contain non-JSON graph state.
- Updated the static WebUI run payload to send this fork's MiniMax defaults (`minimax-cn` / `MiniMax-M3`) so browser-started runs do not fall back to unsupported placeholder OpenAI model names.
- Set WebUI/API run defaults to `minimax-cn` / `MiniMax-M3`, default report language to Chinese, and changed the frontend ticker field from free text to a dropdown of common symbols.
- Added global macro routing for HK/CN equities (mapping to FRED inflation and GDP indices) with dynamic lookback extension to accommodate reporting delays.
- Resolved tool-call argument pollution issues (such as `"/invoke"` generated by MiniMax-M3 Reasoning CoT leak) by reinforcing all tool signatures with `**kwargs` catch-all.
- Created `tests/test_global_macro_routing.py` to cover global macro routing and tool-arg parameter sanitization.

## Social Sentiment Classification Update (2026-07-12)

- Split the Providers UI labels into News Data and Social Sentiment instead of presenting news as a combined news/social category.
- Classified X/Twitter, Reddit, and StockTwits under Social Sentiment while preserving the backend `news_data` and `social_data` routing boundary.
- Clarified that Bird is the configurable X/Twitter vendor and that Reddit/StockTwits are built-in Sentiment Analyst sources.

## Local Refresh Performance Update (2026-07-12)

- Vendored Marked 15.0.12 and its license so initial rendering never blocks on jsDelivr.
- Removed the Google Fonts network dependency and retained the existing system-font fallback stack.
- Restricted CLI Web development reload watching to `cli/`, `tradingagents/`, and `web/`, excluding the virtual environment, results, and Git metadata.

## Reddit Social Source Configuration (2026-07-12)

- Added Reddit to the visible `social_data` source settings alongside Bird/X.
- Preserved historical behavior by migrating existing browser settings with Reddit enabled.
- Wired the Reddit toggle to Sentiment Analyst prefetch so disabling it prevents Reddit network requests.

## Server-side Web Configuration (2026-07-12)

- Added `/api/config/web` GET/PUT/DELETE endpoints backed by atomic JSON persistence at `~/.tradingagents/web_config.json`.
- Moved report language, research depth, LLM/model/reasoning settings, backend URL, and all data-vendor ordering/enabled state out of browser storage.
- Retained only UI language in localStorage; legacy settings/provider keys are read once, migrated to the server, and removed.
- Server persistence allowlists known fields and vendors so credentials and unknown values cannot be stored accidentally.

## Tool Argument Recovery (2026-07-12)

- Added a narrow ToolNode recovery wrapper for model-generated argument schema errors.
- The first `ToolInvocationError` is returned to the active Analyst as a structured error `ToolMessage`, allowing one corrected tool call.
- A repeated invalid call fails the run, while vendor authentication, transport, no-data, and deterministic validation errors continue to propagate unchanged.

## Deterministic Indicator Windows (2026-07-12)

- Centralized per-indicator warm-up requirements and calendar-day conversion before vendor routing.
- Prevented LLM-selected lookback values from under-fetching SMA, MACD, RSI, ATR, Bollinger, and VWMA inputs.
- Corrected validation to distinguish source K-line history from the non-null indicator values emitted after warm-up.

Next recommended work:

1. **Indicator Batching**: Create a batch technical indicators fetcher to reduce the overhead of 12 sequential indicator requests.
2. **SSE/Report Section Throttling**: Throttle the write/push rate of `report_section` updates to prevent SQLite database lock congestion and smooth browser UI updates.
3. Complete deterministic validation and runtime vendor-attempt persistence for news, macro, and prediction-market data.
4. Add basic auth / API key protection for the Web API before exposing it beyond localhost.
5. Consider replacing CDN-loaded Markdown rendering with a vendored/bundled asset for offline/local deployments.
