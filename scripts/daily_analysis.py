#!/usr/bin/env python3
"""Run or inspect configured post-close TradingAgents analyses."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from tradingagents.automation.daily import (  # noqa: E402
    load_daily_schedule,
    load_runtime_preferences,
    load_scheduled_architecture_inventory,
    run_due_analyses,
    scheduler_exit_code,
)
from tradingagents.evaluation import (  # noqa: E402
    DEFAULT_OUTCOME_HORIZON_SESSIONS,
    architecture_rollups,
    active_architecture_inventory_payload,
    architecture_run_cost_rollups,
    attach_operator_cost_metrics,
    compare_architectures,
    load_operator_run_costs,
)
from tradingagents.runtime.history import history_store  # noqa: E402


def _pending_evaluation_summary(
    row: dict,
    horizon_sessions: int = DEFAULT_OUTCOME_HORIZON_SESSIONS,
) -> dict:
    return {
        "run_id": row.get("run_id"),
        "ticker": row.get("ticker"),
        "analysis_date": row.get("analysis_date"),
        "market_data_date": row.get("market_data_date"),
        "decision_as_of": row.get("decision_as_of"),
        "architecture_version": row.get("architecture_version"),
        "architecture_fingerprint": row.get("architecture_fingerprint"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "horizon_sessions": horizon_sessions,
        "status": "awaiting_fixed_horizon_outcome",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradingAgents post-close daily automation")
    parser.add_argument("command", choices=("run", "status", "evaluate"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--web-config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ticker")
    parser.add_argument("--baseline")
    parser.add_argument("--challenger")
    parser.add_argument("--baseline-fingerprint")
    parser.add_argument("--challenger-fingerprint")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "evaluate":
        evaluations = attach_operator_cost_metrics(
            history_store.list_decision_evaluations(ticker=args.ticker),
            store=history_store,
        )
        pending = history_store.list_unevaluated_validated_runs(ticker=args.ticker)
        run_cost_rows = load_operator_run_costs(
            store=history_store,
            ticker=args.ticker,
        )
        payload = {
            "evaluation_count": len(evaluations),
            "pending_evaluation_count": len(pending),
            "pending_evaluations": [
                _pending_evaluation_summary(row) for row in pending
            ],
            "rollups": architecture_rollups(evaluations),
            "run_cost_sample_count": len(run_cost_rows),
            "run_cost_rollups": architecture_run_cost_rollups(run_cost_rows),
            "active_architecture_inventory": active_architecture_inventory_payload(
                load_scheduled_architecture_inventory(
                    args.config,
                    args.web_config,
                ),
                evaluations=evaluations,
                terminal_runs=run_cost_rows,
                ticker=args.ticker,
            ),
        }
        if args.baseline and args.challenger:
            if args.baseline == args.challenger:
                raise SystemExit("--baseline and --challenger must be distinct")
            if bool(args.baseline_fingerprint) != bool(args.challenger_fingerprint):
                raise SystemExit(
                    "--baseline-fingerprint and --challenger-fingerprint "
                    "must be provided together"
                )
            try:
                payload["comparison"] = compare_architectures(
                    evaluations,
                    baseline=args.baseline,
                    challenger=args.challenger,
                    baseline_fingerprint=args.baseline_fingerprint,
                    challenger_fingerprint=args.challenger_fingerprint,
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from None
        elif args.baseline or args.challenger:
            raise SystemExit("--baseline and --challenger must be provided together")
        elif args.baseline_fingerprint or args.challenger_fingerprint:
            raise SystemExit(
                "fingerprint selection requires --baseline and --challenger"
            )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    schedule = load_daily_schedule(args.config)
    if args.command == "status":
        payload = {
            "enabled": schedule.enabled,
            "paired_shadow_authorized": schedule.paired_shadow_authorized,
            "max_attempts_per_date": schedule.max_attempts_per_date,
            "retry_after_minutes": schedule.retry_after_minutes,
            "stale_active_after_minutes": schedule.stale_active_after_minutes,
            "market_data_retry_after_minutes": schedule.market_data_retry_after_minutes,
            "market_data_max_wait_minutes": schedule.market_data_max_wait_minutes,
            "targets": [
                {
                    "symbol": item.symbol,
                    "timezone": item.timezone,
                    "run_after": item.run_after.strftime("%H:%M"),
                    "weekdays": list(item.weekdays),
                    "asset_type": item.asset_type,
                    "architecture_version": item.architecture_version,
                    "longitudinal_context_mode": item.longitudinal_context_mode,
                }
                for item in schedule.targets
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    preferences = load_runtime_preferences(args.web_config)
    outcomes = run_due_analyses(
        schedule,
        preferences=preferences,
        dry_run=args.dry_run,
    )
    print(json.dumps(outcomes, ensure_ascii=False, indent=2))
    return scheduler_exit_code(outcomes)


if __name__ == "__main__":
    raise SystemExit(main())
