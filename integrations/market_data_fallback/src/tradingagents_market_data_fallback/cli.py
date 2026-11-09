"""Optional CLI for running TradingAgents with the Longbridge/Westock fallback chain."""

from __future__ import annotations

import argparse
from datetime import date

from .bootstrap import config_with_fallbacks, registered_fallbacks
from .workspace import (
    config_for_workspace,
    symbol_workspace,
    workspace_cache_paths,
    workspace_result_paths,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tradingagents_market_data_fallback",
        description="Run TradingAgents with optional Longbridge MCP and Westock fallbacks.",
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--asset-type", choices=("stock", "crypto"), default="stock")
    args = parser.parse_args(argv)

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    workspace = symbol_workspace(args.ticker)
    config = config_for_workspace(config_with_fallbacks(), workspace)
    with registered_fallbacks(), workspace_cache_paths(workspace), workspace_result_paths(workspace):
        graph = TradingAgentsGraph(config=config)
        _state, signal = graph.propagate(args.ticker, args.date, asset_type=args.asset_type)
    print(f"分析完成：{args.ticker} | {args.date} | 信号：{signal}")
    print("报告位置请查看 TradingAgents 的 results_dir。")
    return 0
