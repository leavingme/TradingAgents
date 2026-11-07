"""CLI: sync a read-only Futu portfolio snapshot into one TradingAgents run."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import sys

from .appserver import AppServerError, CodexAppServer
from .portfolio import holdings_from_positions, real_accounts, unwrap_mcp_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tradingagents_futu_bridge",
        description="从 Codex 配置的 Futu MCP 读取持仓，并作为上下文运行 TradingAgents。",
    )
    parser.add_argument("--ticker", required=True, help="分析标的，例如 AAPL 或 0700.HK")
    parser.add_argument("--date", default=date.today().isoformat(), help="分析日期，默认本地今日")
    parser.add_argument("--asset-type", choices=("stock", "crypto"), default="stock")
    parser.add_argument("--codex", default="codex", help="Codex CLI 可执行文件名或路径")
    return parser


def _account_id(account: dict) -> str:
    return str(account.get("acc_id", account.get("account_id")))


def run(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[4]
    try:
        with CodexAppServer(str(repo_root), executable=args.codex) as app:
            app.start()
            account_response = app.call_futu("account_authorized_trd_accs", {})
            accounts = real_accounts(account_response)
            if not accounts:
                raise AppServerError("Futu 没有返回已授权的真实交易账号。")
            selected = accounts
            position_results = [
                app.call_futu("account_positions", {"acc_id": _account_id(account)})
                for account in selected
            ]

        captured_at = datetime.now().astimezone().isoformat(timespec="minutes")
        snapshot = holdings_from_positions(position_results, captured_at)

        # Import only after the Futu read succeeds. This keeps the bridge's
        # account-only diagnostics usable even if optional model dependencies
        # are not configured yet.
        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph()
        _final_state, signal = graph.propagate(
            args.ticker,
            args.date,
            asset_type=args.asset_type,
            portfolio=snapshot,
        )
        print(f"分析完成：{args.ticker} | {args.date} | 信号：{signal}")
        print(f"本次读取 {len(selected)} 个真实账号、{len(snapshot.holdings)} 个标的持仓。")
        print("报告位置请查看 TradingAgents 的 results_dir。")
        return 0
    except (AppServerError, ValueError, OSError) as exc:
        print(f"Futu 桥接失败：{exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    return run(_parser().parse_args(argv))
