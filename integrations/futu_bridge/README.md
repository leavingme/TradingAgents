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
PYTHONPATH=integrations/futu_bridge/src${PYTHONPATH:+:$PYTHONPATH} \
  python -m tradingagents_futu_bridge --ticker 0700.HK
```

US example:

```sh
PYTHONPATH=integrations/futu_bridge/src${PYTHONPATH:+:$PYTHONPATH} \
  python -m tradingagents_futu_bridge --ticker AAPL --date 2026-11-07
```

Positions from every authorized **real** trading account are combined by
symbol and currency. Simulated accounts are excluded.

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
