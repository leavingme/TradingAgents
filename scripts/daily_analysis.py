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
    run_due_analyses,
    scheduler_exit_code,
)
from tradingagents.evaluation import architecture_rollups, compare_architectures  # noqa: E402
from tradingagents.runtime.history import history_store  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradingAgents post-close daily automation")
    parser.add_argument("command", choices=("run", "status", "evaluate"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--web-config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--ticker")
    parser.add_argument("--baseline")
    parser.add_argument("--challenger")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "evaluate":
        evaluations = history_store.list_decision_evaluations(ticker=args.ticker)
        payload = {
            "evaluation_count": len(evaluations),
            "rollups": architecture_rollups(evaluations),
        }
        if args.baseline and args.challenger:
            payload["comparison"] = compare_architectures(
                evaluations,
                baseline=args.baseline,
                challenger=args.challenger,
            )
        elif args.baseline or args.challenger:
            raise SystemExit("--baseline and --challenger must be provided together")
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
