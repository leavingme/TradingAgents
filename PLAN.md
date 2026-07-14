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
- Done: pytest run-history isolation initializes a process-unique bootstrap DB before
  collection and then gives every test one temporary SQLite shared by runtime
  `history_store`, Web `TaskStore`, and vendor audit persistence; tests cannot add
  runs to the production or workspace-fallback history databases.
- Done: deterministic unit tests retain fixed anchor dates, while live smoke and
  provider-capability checks derive exchange-aware latest-completed daily-bar
  cutoffs per symbol; cross-market probes no longer treat the natural current
  date as a universally complete market-data date.
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

## Canonical OHLCV Date Repair (2026-07-12)

- Added shared-cache cleanup for impossible weekend equity candles and positive-volume OHLCV duplicates written under adjacent shifted dates.
- Cache reads perform no cleanup; the persisted canonical dataset is the dataset consumers receive.
- Cache writes enforce date/OHLCV invariants and use an atomic temporary-file replacement so invalid input cannot corrupt an existing cache.
- Preserved legitimate zero-volume repeated bars for illiquid instruments.

## Structured OHLCV Write Contract (2026-07-12)

- Added vendor-neutral `OHLCVBar` / `OHLCVBatch` models with explicit trading dates and provenance.
- Longbridge MCP, Longbridge CLI, and Westock construct structured batches before cache persistence; unstructured DataFrames are rejected.
- Kept canonical cache CSVs unchanged and added `ohlcv_audit.jsonl` for vendor, raw timestamp, timezone semantics, adapter version, and batch ID evidence.
- Removed the source-ambiguous secondary cache write from `stockstats_utils`; the vendor adapter that fetched the data owns the audited write.

## Technical Indicator Calculation Parity (2026-07-12)

- Longbridge Pine and Westock/stockstats now share the same deterministic three-year `calculation_start`; the shorter requested window controls rendering only.
- Longbridge `quant_run` receives an exclusive end boundary one day after the analysis date, and MCP seed-history observations are removed from the LLM-facing output.
- Indicator freshness is checked against the latest verified ordinary OHLCV trading date. A stale Pine series is rejected so vendor routing can fall back instead of labeling an older value with a newer report date.
- Known upstream limitation: Longbridge ordinary OHLCV for NVDA contained 2026-07-10 while Longbridge MCP `quant_run` remained at 2026-07-09 even when its end boundary was extended through 2026-07-14.
- Same-start 2026-07-09 comparison: EMA/RSI/MACD/ATR converge within small tolerances; SMA50/SMA200 retain roughly 0.06%/0.11% source-history differences; Bollinger middle matches while upper/lower differ because Pine and stockstats use different standard-deviation definitions.

## Release-blocking Execution Integrity (2026-07-12)

- Added append-only `run_vendor_calls` provenance keyed by `run_id + call_id + attempt`; each fallback attempt records vendor, sanitized arguments, timing, status/error, selected result, result hash, calculation range, and latest returned date.
- Kept `vendor_verifications` as overwriteable current-health state only. Historical run audit is exposed separately at `/api/runs/{run_id}/vendor-calls` and is deleted only with its owning run.
- Run-scoped vendor audit is mandatory: persistence failure stops analysis rather than allowing an unauditable executable report.
- Buy/Overweight decisions require structured entry, stop, target, ATR, initial/target position, and maximum portfolio-risk fields. Reward/risk, ATR distance, and portfolio loss are calculated only by deterministic code.
- Invalid structured plans receive one correction attempt containing the validator error. A second failure, missing structured-output support, or upstream Trader `REVIEW_REQUIRED` deterministically produces `Hold / REVIEW_REQUIRED`; free-text executable fallback is prohibited.

### Follow-up execution-risk architecture

- Add an explicit trade side (`long`, `short`, `flat`). A future short-equity validator must enforce `price_target < entry_price < stop_loss`; `Sell` and `Underweight` remain position-reduction ratings and must never implicitly open a short.
- Model options separately from short stock. Long puts require premium, strike, expiry, contract multiplier, implied volatility, and Greeks-aware payoff/risk validation rather than linear short-equity arithmetic.
- Split position generation from validation. `PositionSizingEngine` may implement fixed-risk, ATR-risk, volatility-target, fractional-Kelly, account-equity, and max-notional policies; `TradePlanValidator` must independently recompute and enforce portfolio loss, concentration, and account limits.
- Bind authoritative market inputs (`verified_atr`, latest Close, market date, and vendor `call_id`) from the verified snapshot directly into validation. LLMs should propose trade levels but must not supply or transcribe trusted risk inputs.

## P0 Safety and Integrity Audit Backlog (2026-07-13)

### Confirmed P0

1. **Trusted market inputs and server risk policy**
   - Rebuild the verified market snapshot on the same canonical calculation horizon used by indicator routing.
   - Inject verified ATR, latest Close, market date, and vendor call ID directly into trade validation.
   - Move maximum trade risk, concentration, notional exposure, and account constraints into server-owned policy. LLM output must not be able to raise those limits.
   - Acceptance: a fabricated ATR, stale Close, out-of-range entry, or model-selected permissive risk limit cannot produce a validated decision.
2. **First-class no-decision semantics**
   - Add `decision_status = validated | review_required | unavailable` instead of representing operational/validation failure as Hold.
   - `review_required` must not produce a market signal, enter performance memory, or appear as a normally completed investment decision.
   - Acceptance: structured-output outage and trade-plan validation failure remain distinguishable from a genuine investment Hold through runtime, SQLite, API, UI, reports, and memory.
3. **Untrusted external-content isolation**
   - News and social content must be transported as explicitly untrusted data, never interpolated into system instructions.
   - Add prompt-injection detection/marking and extract structured facts before downstream debate.
   - Acceptance: instructions embedded in a post/article cannot alter tool calls, agent control flow, or decision schema fields.
4. **Web API trust boundary**
   - Allowlist LLM backend endpoints; reject client-provided arbitrary filesystem paths and arbitrary configuration keys.
   - Require authentication/authorization outside loopback and protect run creation, deletion, verification, and config mutation with rate/concurrency limits.
   - Acceptance: an API caller cannot redirect server credentials, write reports outside approved roots, mutate hidden runtime settings, or launch unbounded costly jobs.
5. **Structured news/macro evidence and claim provenance**
   - Normalize vendor responses into source/date/URL/symbol-aware models, then validate freshness, relevance, duplicates, and error payloads before rendering.
   - Bind material report claims to auditable source IDs.
   - Acceptance: every decision-material event can be traced to a validated source record whose timestamp does not exceed the analysis cutoff.

### Conditional P0 when enabled or concurrently deployed

6. **Checkpoint run isolation**
   - Include run ID in checkpoint identity; concurrent runs for the same symbol/date must not share, resume, or delete each other's state.
7. **Audit-store concurrency and entry-point completeness**
   - Enable SQLite WAL, busy timeout, foreign keys, and bounded retry for multi-process writers.
   - Route all production CLI/Web/Python execution through the audited runtime; direct graph propagation must be explicitly non-production or create its own run context.
   - Acceptance: concurrent Web/CLI runs preserve complete append-only provenance without lock-induced false failures or unaudited execution paths.

The following remain P1 rather than P0: duplicate report-section events, excessive report/token size, missing per-LLM-call detail, Longbridge Pine lag, small cross-engine SMA/Bollinger differences, and UI/history performance.

### P0 implementation status (2026-07-13)

All seven items above are implemented. The acceptance suite covers trusted snapshot call binding and calculation horizon, server-owned account/risk limits, no-decision persistence and UI semantics, prompt-injection redaction and role separation, Web allowlist/auth/rate/concurrency boundaries, structured news/macro evidence with source-ID citation gates, run-isolated checkpoints, and WAL/busy-timeout/foreign-key storage settings. Production examples now use `tradingagents.runtime`; the compatibility `propagate()` path creates its own audited run context.

Next recommended work:

1. **Completed — OpenAI-compatible test secret isolation**: the keyless-local regression test clears both the provider-specific key and `OPENAI_API_KEY` fallback within `monkeypatch`, and validates the placeholder through a boolean helper that cannot render credential material in assertion diffs.
2. **Indicator Batching**: Create a batch technical indicators fetcher to reduce the overhead of 12 sequential indicator requests.
3. **SSE/Report Section Throttling**: Throttle the write/push rate of `report_section` updates to prevent SQLite database lock congestion and smooth browser UI updates.
4. Complete deterministic validation and runtime vendor-attempt persistence for prediction-market data.

## Repeatable NVDA engineering cycle (2026-07-13)

Implemented `scripts/engineering_cycle.py` and `tradingagents.engineering_cycle` as the canonical run-review-remediate workflow. Every cycle owns a unique run ID and persists baseline inputs, SQLite execution/vendor evidence, deterministic and human findings, a P0 plan, implementation/verification evidence, and a final completion gate. The gate rejects unresolved P0s, unacknowledged reviews, missing evidence, failed verification, and verification performed before the latest P0 resolution.

The first real cycle closed on run `827ade0962dc42f0a7f16a5ee1cd9064` after resolving three P0 classes: engineering-entry LLM/database configuration drift, unverified executable numbers in non-long decisions, and hallucinated news `source_id` values without a bounded correction path. Codex performed the semantic execution review and remediation as the external engineering agent; the repository does not yet invoke Codex or another reviewer model automatically. Deterministic validators and `gate`, not the reviewing LLM, retain completion authority.

A subsequent cycle baseline `052de71e5dcc42468ea16f98f3b10895` initially classified current Polymarket probabilities as historical look-ahead because its `analysis_date` was the prior completed US trading day. Follow-up semantic review corrected that classification: this was a live pre-market decision, so `analysis_date=2026-07-10` identified the latest complete daily bar while information available by the 2026-07-13 decision time remained valid. Runtime now models this explicitly with `analysis_mode=live|point_in_time`: live runs use call-time information and persist `market_data_date` plus final `decision_as_of`; point-in-time runs require a timezone-aware `information_cutoff`, and current-only Polymarket snapshots fail closed only in that explicit mode. The same cycle legitimately narrowed an engineering-review false positive where the phrase `Hold with Triggers` was incorrectly joined to a later calendar number. Full structured prediction-market models, stable source IDs, expiry/probability validation, and historical snapshots remain separate follow-up work.

Next evolution: add an optional independent `review-model` job that consumes immutable execution evidence and emits schema-validated findings with event/vendor/source references. It must remain advisory, must not edit history, and must still require review acknowledgement, deterministic verification, and the existing gate.

## Longbridge structured news routing (2026-07-13)

Longbridge news is now part of the default validated news chain. Per-symbol news prefers MCP's structured `news` response and falls back to the CLI's structured `news` JSON before Westock, DuckDuckGo, and Alpha Vantage. Global macro headlines use the CLI's structured `news search` response; the hosted MCP `news_search` tool is deliberately not registered for global news because its live response currently reports epoch timestamps, which cannot satisfy deterministic publication-time validation. Both adapters map raw JSON directly to `NewsFeed`; router-level validation remains responsible for source IDs, requested-window enforcement, URLs, symbol binding, and deduplication.

Existing Web provider configurations matching the former untouched default are migrated to enable the two Longbridge news vendors. Explicitly customized news-provider lists retain their chosen ordering and enabled state.

## Westock-first technical indicators (2026-07-13)

- The default indicator route is `westock → longbridge_mcp`. Westock/stockstats computes indicators deterministically from the shared canonical OHLCV series, while MCP remains a validated fallback.
- Longbridge CLI stays registered for explicit opt-in and diagnostics, but is disabled in the default indicator chain because its summary response cannot satisfy the same dated-series validation contract.
- Existing Web configurations matching the former untouched indicator default are migrated; custom provider ordering and enablement are preserved.

## Longbridge capability expansion roadmap (2026-07-13)

Live inventory evidence:

- Longbridge CLI v0.24.0 is authenticated; both CN and global OpenAPI endpoints passed connectivity checks.
- The hosted MCP currently exposes 147 tools, while `longbridge_mcp.py` explicitly resolves only eight capabilities: OHLCV history/recent bars, static reference data, valuation indexes, financial reports, Pine indicators, symbol news, and quotes.
- Read-only NVDA probes confirmed structured extended-hours quotes, 11 consensus periods, 50 filing records with publication/file metadata, short-interest observations including days-to-cover, business-segment fields, market temperature, and future finance-calendar events.
- Tool discovery is not sufficient evidence of adapter safety: a live `top_movers` probe exposed a parameter-type mismatch between its description and server behavior. Every addition therefore requires inspection of the live schema and representative raw responses.

Delivery order:

1. **P1 — Forward-looking research evidence**: add consensus/EPS forecasts, finance calendar, institution ratings, filings, and short-interest/short-volume data. Route these through new structured evidence models and deterministic cutoff, currency, fiscal-period, symbol, source-ID, and freshness validation before rendering them to Fundamentals, News, Bull/Bear, or Risk agents.
2. **P1 — Verified market context and cross-market Session Engine**: enrich the trusted market snapshot with quote, extended-hours quote, market status, and authoritative trading days. Model exchange timezone, DST, holidays, half days, and `pre|regular|post` sessions dynamically rather than hard-coding Beijing-time windows. Preserve `market_date`, `observed_at`, `published_at`, and `available_at` separately; intraday and extended-hours observations must never overwrite canonical daily bars or be reused as historical snapshots without an auditable point-in-time timestamp.
   - Add A/H/ADR, FX, conversion-ratio, and supply-chain mappings for two evidence windows: China/HK close to US pre-market, and US close/after-hours to the next China/HK open.
   - Produce read-only gap, premium/discount, sector read-through, and anomaly evidence. Treat pre/post-market prices as indicative and validate liquidity, spreads, transaction costs, settlement/conversion constraints, and historical lead-lag stability before promoting any relationship to a signal; never label the time-zone gap as risk-free arbitrage.
   - Support a close-confirmed deep-analysis snapshot followed by an opening-time incremental refresh. Historical runs may consume only evidence with `available_at <= analysis_cutoff`, preventing earnings, quotes, calendars, or cross-market closes that were not yet observable from leaking into the run.
3. **P2 — Fundamental, ownership, and microstructure enrichment**: add business segments, valuation history/peers, institutional/fund holders, insider activity, capital flow, trade statistics, market temperature, and anomaly evidence only after each response has a domain model and validator.
4. **P2 — Read-only account risk**: use account balance, positions, margin, buying-power estimation, and FX as server-owned portfolio constraints under least-privilege OAuth. Keep all order, DCA, alert, and watchlist mutations outside the analysis graph.
5. **P2 — Macro vendor**: register Longbridge macro observations and event calendar as an independent vendor mapped to `MacroSeries`; do not hide cross-vendor fallback inside FRED or another adapter.
6. **P3 — Derivatives and universe selection**: defer option-chain/IV/Greeks integration until the separate derivative payoff and risk validator exists. Defer screeners, rankings, and movers to a future universe-selection stage rather than expanding the current single-symbol prompt surface.

All new integrations retain the mandatory pipeline `raw Longbridge JSON → Longbridge adapter → unified domain model → deterministic validator → LLM renderer`. Current-only consensus, rating, flow, sentiment, and account snapshots must be explicitly marked as such; they cannot be used for historical runs without point-in-time evidence because doing so would introduce look-ahead bias.
