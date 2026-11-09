# Optional Longbridge MCP + Westock fallback

This add-on keeps the TradingAgents mainline files and defaults unchanged. Its
launcher temporarily registers the optional providers with the existing vendor router
and passes a copied config with these chains:

```text
OHLCV:                         westock → longbridge MCP → yfinance
Technical indicators:          westock → longbridge MCP → yfinance
Company profile:               westock → longbridge MCP → yfinance
Financial statements:          longbridge MCP → sec_edgar → yfinance
Ticker news:                   westock → longbridge MCP → yfinance
Global news:                  westock → yfinance
```

For data Westock does not provide, such as financial statements, the router
skips it and continues to the next configured provider. If a configured vendor
reports a failure or no usable data, the router tries the next adapter.
Longbridge MCP provides OHLCV, company reference, financial statements,
indicators and ticker news. The WeStock 1.0.38 skill documents profile, dated
OHLCV, indicators (calculated locally), ticker news and global hot news.
Westock has no statement adapter. Insider transactions and prediction-market
data remain on the project's existing providers. The ordinary TradingAgents
CLI is unchanged.

## Configure Longbridge MCP

Generate a one-time authorization code from Longbridge MCP, then redeem it with
the included helper:

```sh
python integrations/market_data_fallback/activate_longbridge_mcp.py
```

The helper prompts for the code without echoing it.

The helper writes the token under `~/.config/tradingagents/` with owner-only
permissions. Alternatively, set `LONGBRIDGE_MCP_ACCESS_TOKEN`, or point
`LONGBRIDGE_MCP_TOKEN_FILE` at a JSON token file containing `access_token` and
optional ISO `expiry`.
The endpoint defaults to `https://mcp.longbridge.com`; override it with
`LONGBRIDGE_MCP_URL` if needed. The adapter discovers the MCP tool list and
uses the standard MCP initialize/initialized handshake before discovering
tools such as `history_candlesticks_by_date`, `quant_run`, and
`financial_report`. This project is configured for the Hong Kong/AP endpoint
`https://mcp.longbridge.cn`; use the global endpoint for US-account data.

## Configure Westock

This integration targets the Go `westock` CLI used by the WeStock Data 1.0.38
skill package. It does not use the separate, older npm `westock-data-clawhub`
1.0.4 package. The supplied installer verifies the downloaded binary against
the package's pinned SHA256 manifest. To keep the executable project-local,
install it into the optional integration directory:

```sh
export WESTOCK_SKILL_DIR=/path/to/unpacked/westock-data
WESTOCK_INSTALL_DIR="$PWD/integrations/market_data_fallback/bin" \
PATH="$PWD/integrations/market_data_fallback/bin:$PATH" \
  bash "$WESTOCK_SKILL_DIR/scripts/setup.sh"
```

Set `WESTOCK_CLI=integrations/market_data_fallback/bin/westock` in the project
`.env`, or install `westock` on `PATH`. The adapter requests dated daily K-lines
using `--start`/`--end`, and normalizes the CLI's documented Markdown table
output (as well as JSON output if enabled by a future CLI build). The CLI itself
must be installed separately; no npm dependency or mainline source change is
required.

## Run

From the repository root, with the TradingAgents dependencies installed:

```sh
PYTHONPATH=integrations/market_data_fallback/src${PYTHONPATH:+:$PYTHONPATH} \
  python -m tradingagents_market_data_fallback --ticker 0700.HK
```

The Futu bridge can use the same adapters by including both source directories
in `PYTHONPATH`; see `integrations/futu_bridge/README.md`.

Both optional launchers scope mutable state to a per-symbol workspace at
`~/.tradingagents/workspaces/<SYMBOL>`. Set `TRADINGAGENTS_WORKSPACES_DIR` in
the project `.env` to change the root. Each workspace has
`data/market/ohlcv.csv`, `data/market/ohlcv.metadata.json`,
`data/fundamentals`, `data/news`, `runs`, `memory`, and `config`. OHLCV returned
through the configured router is merged into the same canonical CSV regardless
of whether Yahoo, Westock, or Longbridge MCP supplied it; the sidecar records
contributing providers and the latest source. SEC EDGAR caches remain under
`data/fundamentals`. Successful routed company-profile and financial-statement
responses are saved as request-keyed JSON snapshots in `data/fundamentals/`;
successful ticker/global news and insider-transaction responses are saved in
`data/news/`. Each snapshot includes its provider, request parameters, fetch
time, and returned content. These snapshots are for workspace history and
inspection; the adapters still fetch fresh data on subsequent calls.
Analysis state files are stored directly under
`runs/TradingAgentsStrategy_logs/`, without repeating the ticker directory.
`config/` is reserved for symbol-specific overrides; model/provider settings
and credentials continue to come from the shared project `.env` and existing
credential locations.
