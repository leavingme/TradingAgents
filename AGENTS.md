# AGENTS.md — TradingAgents Fork (TauricResearch/TradingAgents v0.3.0)

This file documents the day-to-day operational conventions for working with
this fork. It's the project-scoped equivalent of the Hermes workspace
AGENTS.md — read it before doing anything non-trivial.

## Repository

- **Upstream**: `https://github.com/TauricResearch/TradingAgents` (`tauric` remote)
- **Fork**: `https://github.com/leavingme/TradingAgents` (`myfork` remote, push target)
- **Mirror**: `https://github.com/leavingme/TradingAgents` (`origin` remote, fetch only)
- **Workspace root**: `/data/workspace/TradingAgents`
- **Branch**: `main`
- **Version**: v0.3.0 (`85946c2 chore: release v0.3.0`) + 7 fork-local commits

## Environment

### Python & venv

- **Python**: 3.12.3 (system binary at `/usr/bin/python3.12`)
- **venv path**: `/data/workspace/TradingAgents/venv`
- **Do NOT use `pip install -e .`** — the workspace has special handling.
  See the **venv pitfalls** section below before running any pip command.

### Console entry points

- `venv/bin/tradingagents` — Typer CLI (interactive questionary menu)
- `python -m cli.main` — alternative
- `run_smoke.py` — non-interactive smoke runner (preferred for batch/automation)
- `venv/bin/uvicorn web.backend.main:app --host 127.0.0.1 --port 8765` — minimal FastAPI Web API dev server
- After `pip install -e .`, the entry point is auto-regenerated from
  `pyproject.toml`'s `[project.scripts]` → currently points at
  `tradingagents._cli_entry:app` (not `cli.main:app` directly — see the
  PYTHONPATH section).

### Critical env vars

| Variable | Purpose | Where set |
|---|---|---|
| `OPENAI_API_KEY` | LLM (also serves as fallback for all vendors including `minimax-cn`) | `~/.zshrc` export |
| `OPENAI_BASE_URL` | LLM endpoint | `~/.zshrc` export |
| `MINIMAX_CN_API_KEY` | minimax (China region) | `~/.zshrc` export |
| `MINIMAX_API_KEY` | minimax (Global) | `~/.zshrc` export |
| `.longbridge_mcp_token.json` | Longbridge API token (data vendor) | `tradingagents/.longbridge_mcp_token.json` (gitignored) |
| `data_vendors.core_stock_apis` | Default `"longbridge_mcp, longbridge"` (Yahoo Finance fallback only) | `default_config.py` |
| `llm_provider` | Default `"minimax-cn"` | `default_config.py` |
| `quick_think_llm` / `deep_think_llm` | Default both `"MiniMax-M3"` | `default_config.py` |

## venv pitfalls (read before touching pip)

### Shebang drift (FIXED 2026-07-05)

The venv was relocated from `/home/ubuntu/.openclaw/workspace/TradingAgents/`
during the 2026-04-01 workspace migration. After relocation, all
`venv/bin/pip*` shebangs hard-coded the old `.openclaw` path, breaking
direct invocation of `pip`. **Fix applied 2026-07-05**: venv was rebuilt
from scratch with `/usr/bin/python3.12 -m venv`. All wrappers now have
correct shebangs and invoke without `python -m` indirection.

If the venv ever drifts again (e.g. moved to a new host), recreate it
rather than try to repair shebangs.

### Vendor fallback chain

`data_vendors` is a **router-level fallback chain**, not a single vendor.
The order is significant:

```
core_stock_apis    : "longbridge_mcp, longbridge"        # then yfinance fallback
technical_indicators: "longbridge_mcp, longbridge"
fundamental_data   : "longbridge_mcp, longbridge"
news_data          : "web_search, duckduckgo, alpha_vantage, yfinance"
```

`route_to_vendor()` MUST catch vendor-specific exceptions
(`MCPAuthError`, `LongbridgeCLIError`, `AlphaVantageRateLimitError`) and
silently fall through to the next entry. Vendor impls that fail to load
(return `None`) must also be skipped — never raise. Hard rule.

### Vendor method signatures (graph calls these)

When adding a new vendor, it MUST match these signatures exactly or the
graph will throw `TypeError`:

```
get_stock_data(symbol, start_date, end_date)
get_indicators(symbol, indicator, date, lookback_days)
get_fundamentals(symbol, curr_date=None)
get_income_statement(symbol, freq=None, curr_date=None)
get_balance_sheet(symbol, freq=None, curr_date=None)
get_cashflow(symbol, freq=None, curr_date=None)
```

**Retired vendors**: keep `<name>_legacy.py.bak` files. Never delete a
vendor fully from `VENDOR_METHODS` — when a vendor-specific bug appears,
you'll need the old impl to compare against.

## The `_cli_entry.py` shim (read this before debugging CLI failures)

`venv/bin/tradingagents` (the console script) imports from
`tradingagents._cli_entry`, which **modifies `sys.path` before any
`from cli.main import app`**. This is NOT optional decoration — without
it, the CLI silently fails.

### Why

The Hermes sandbox sets `PYTHONPATH=/tmp/hermes_sandbox_xxx:/data/hermes/hermes-agent`
when launching subprocesses. `/data/hermes/hermes-agent/` contains a
`cli.py` single-file module (a Hermes internal CLI), which makes Python
resolve `cli` as a *module* (not a *package*) — `from cli.main import app`
then fails with `ModuleNotFoundError: No module named 'cli.main'; 'cli' is not a package`.

### What the shim does

1. Removes `/data/hermes/hermes-agent` from `sys.path` (just the path
   entry string, NOT the directory or its files)
2. Then `from cli.main import app` resolves to TradingAgents' `cli/`
   package via the editable finder

### What the shim does NOT do

- It does not modify any files on disk
- It does not affect other Python processes
- It does not affect the system Python or any other venv

### Diagnosis order when CLI breaks

If `tradingagents --help` fails, check in this order:

1. `echo $PYTHONPATH` — should NOT contain `/data/hermes/hermes-agent`
   when running from a clean shell
2. `head -1 venv/bin/tradingagents` — should be
   `#!/data/workspace/TradingAgents/venv/bin/python3.12`
3. `cat venv/bin/tradingagents` — should import from `tradingagents._cli_entry`,
   not `cli.main`
4. `git status` — make sure `tradingagents/_cli_entry.py` and the
   `pyproject.toml` entry-point change are committed and present
5. `venv/bin/python3.12 -c "import tradingagents; print(tradingagents.__file__)"`
   — should print `/data/workspace/TradingAgents/tradingagents/__init__.py`

**The shim is THE fix for the PYTHONPATH conflict.** Do not try to fix
this by editing pip config, upgrading pip again, or removing the `.pth`
files — those were all red herrings during the original diagnosis.

## M3 reasoning round-trip (MiniMax-M3 specifics)

The `MinimaxChatOpenAI` client (in `tradingagents/llm_clients/openai_client.py`)
needs **two hook points** to support M3's Interleaved Thinking feature:

- **Receive side** (`_create_chat_result`): pull server's
  `reasoning_details[]` and `reasoning_content` into
  `AIMessage.additional_kwargs`
- **Send side** (`_get_request_payload`): push those fields back into
  the outgoing wire message dict when the message gets round-tripped
  into the next request

This pattern mirrors `langchain-deepseek==1.1.0`. Both hooks must exist;
a one-sided fix breaks long-horizon agent tasks (the model loses its
chain-of-thought between rounds).

OpenAI SDK 2.x auto-flattens `extra_body` into top-level request fields
(`reasoning_split: true` works as-is), so the wire-format side doesn't
need a custom client. The langchain message-conversion layer is what
drops `reasoning_details` by default — that's why both hooks are needed
on the langchain side.

## Running the smoke test

Non-interactive way to validate the full pipeline:

```bash
cd /data/workspace/TradingAgents
venv/bin/python run_smoke.py NVDA 2026-07-05
```

- Background it (5–10 min runtime): use `background=true, notify_on_complete=true`
- Output goes to stdout + `results/<SYMBOL>/...` (gitignored since 2026-07-05)
- Exit code 0 means propagate reached a final decision
- Smoke run on 2026-07-05 (NVDA): FINAL DECISION = `Hold`

## Git workflow

- **Push target**: `myfork` (NOT `origin` and NOT `tauric`)
- `origin` and `tauric` are fetch-only mirrors; never push there
- `git push myfork main` for normal sync
- `results/` is gitignored — smoke output should never be committed
- API keys live in `~/.zshrc` exports and `.longbridge_mcp_token.json` —
  never in config files, never in commits (the secret-file-editing
  protocol applies)

## Things to check periodically

- **Longbridge token expiry**: token in
  `tradingagents/.longbridge_mcp_token.json` expires ~30 days from issue.
  Check the expiry field before running long smoke runs. As of
  2026-07-05: expires 2026-07-18.
- **YFinance fallback**: still wired into the fallback chain. Don't
  remove it — when Longbridge goes down, yfinance is the safety net.

## Don't ask permission to

- Run `tradingagents --help` or any non-interactive smoke
- Read files within the workspace
- Run `git status` / `git log` / `git diff` for inspection
- Update this file with new lessons learned
