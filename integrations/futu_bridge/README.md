# Futu MCP → TradingAgents Bridge

This optional integration reads positions from the `futu-mcp` MCP server already
configured in Codex, then passes a currency-aware portfolio snapshot to the
existing `TradingAgentsGraph.propagate(..., portfolio=...)` API. It is outside
the core package and does not change analyst tools, data vendors, or project
configuration.

## Requirements

- Run from this TradingAgents checkout with its Python dependencies installed.
- `codex` CLI installed and signed in.
- `futu-mcp` configured and authorized in the Codex App Server configuration.
- The Futu connection exposes `account_authorized_trd_accs` and
  `account_positions`.

## Run

From the repository root:

```sh
PYTHONPATH=integrations/futu_bridge/src:integrations/market_data_fallback/src${PYTHONPATH:+:$PYTHONPATH} \
  python -m tradingagents_futu_bridge --ticker 0700.HK
```

US example:

```sh
PYTHONPATH=integrations/futu_bridge/src:integrations/market_data_fallback/src${PYTHONPATH:+:$PYTHONPATH} \
  python -m tradingagents_futu_bridge --ticker AAPL --date 2026-11-07
```

Positions from all accounts returned by Futu's authorized trading-account
tool are combined by symbol and currency. If the response includes an explicit
trade environment, only `REAL` accounts are used.

Futu codes such as `HK.00700` and `US.AAPL` are normalized to `0700.HK` and
`AAPL`. Average cost is weighted when the same symbol/currency appears in more
than one selected account. Cash balances are not read or passed through.

The App Server thread is ephemeral and the bridge only calls read-only account
and positions tools. It does not submit, modify, or cancel orders. Position
values are current when fetched; setting an earlier `--date` does not turn a
current holdings snapshot into historical holdings.

## Scope

This wires holdings context into one TradingAgents run. It does not add Futu
quote tools to every analyst or replace the project's existing market data
providers. Those require a separate optional graph-tool integration.

For market-data and indicator fallback, the bridge also uses the optional
Longbridge MCP and Westock adapters under
`integrations/market_data_fallback/`. See that integration's README for setup.

The project `.env` can enable model token streaming for this bridge with
`FUTU_BRIDGE_LLM_STREAMING=true`. The bridge temporarily enables the MiniMax
streaming client while building/running the graph and restores the original
provider registry afterward. It reports request start, first response,
periodic chunk progress, and completion without printing model text. Ordinary
TradingAgents entry points keep their existing behavior.

For MiniMax and DeepSeek runs, the bridge also prepends a neutral, evidence-led analysis
instruction to each model request. This behavior is enabled by default and can
be disabled with `FUTU_BRIDGE_OBJECTIVE_PROMPTS=false`. It asks the model to
separate facts from estimates, represent supporting and contradicting evidence
fairly, state uncertainty, and avoid sensational or emotionally loaded wording.
It does not remove required rating labels or bypass provider moderation. This
overlay is implemented only in the optional bridge and does not alter
TradingAgents prompt files or default provider behavior.

## Per-symbol workspace

Each bridge run uses `~/.tradingagents/workspaces/<SYMBOL>` by default. Set
`TRADINGAGENTS_WORKSPACES_DIR` in the project `.env` to choose another root.
The workspace contains `data/market/ohlcv.csv`,
`data/market/ohlcv.metadata.json`, `data/fundamentals`, `data/news`, `runs`,
`memory`, and `config`. Routed OHLCV from Yahoo, Westock, or Longbridge MCP is
merged into that same canonical file; its sidecar records contributing
providers and the latest source. SEC EDGAR caches remain in `data/fundamentals`.
Successful company-profile and statement responses are saved as request-keyed
JSON snapshots under `data/fundamentals/`; ticker/global news and
insider-transaction responses are saved under `data/news/`. Snapshots include
the provider, request parameters, fetch time, and returned content. They are
saved for workspace history and inspection; later analysis calls still fetch
fresh data. Run state files are stored in `runs/TradingAgentsStrategy_logs/`
without another ticker subdirectory. TradingAgents memory is scoped to the
symbol. `config/` is reserved for future
symbol-specific overrides; model/provider settings and credentials continue to
come from the shared project `.env` and existing credential locations.
