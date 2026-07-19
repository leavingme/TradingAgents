"""Headless TradingAgents analysis runner.

The runner owns graph construction, graph streaming, event conversion, and
report writing. It deliberately has no terminal, FastAPI, MongoDB, or Redis
dependency so multiple frontends can consume the same execution stream.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.evaluation import LONGITUDINAL_CONTEXT_SCHEMA
from tradingagents.graph.checkpointer import get_checkpointer, thread_id
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.reporting import write_report_tree
from tradingagents.architecture import (
    architecture_experiment_input_identity,
    architecture_fingerprint,
    build_architecture_manifest,
)

from .config_builder import build_runtime_config
from .events import (
    AnalysisEvent,
    AnalysisRequest,
    AnalysisResult,
    runtime_error_status,
    utc_timestamp,
)
from .report_throttle import ReportSectionThrottler
from .stats_handler import StatsCallbackHandler

ANALYST_ORDER = ("market", "social", "news", "fundamentals")
ANALYST_AGENT_NAMES = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
ANALYST_REPORT_MAP = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}
def _longitudinal_context_status(
    context: str,
    *,
    mode: str,
    information_cutoff: str | None,
) -> dict[str, Any]:
    """Return safe counts proving which audited outcomes entered this run."""
    base = {
        "mode": mode,
        "information_cutoff": information_cutoff,
        "schema": None,
        "same_symbol_scanned_count": 0,
        "same_symbol_included_count": 0,
        "cross_symbol_scanned_count": 0,
        "cross_symbol_included_count": 0,
        "same_symbol_architecture_rollup_count": 0,
    }
    if mode not in {"portfolio_only", "research_and_portfolio"}:
        return {**base, "status": "disabled"}
    if not context:
        return {**base, "status": "empty"}
    try:
        payload = json.loads(context)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("longitudinal context must be canonical JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema") != LONGITUDINAL_CONTEXT_SCHEMA:
        raise ValueError("longitudinal context has an unsupported schema")
    selection = payload.get("selection")
    rollups = payload.get("same_symbol_architecture_rollups")
    if not isinstance(selection, dict) or not isinstance(rollups, list):
        raise ValueError("longitudinal context lacks selection metadata")
    counts: dict[str, int] = {}
    for key in (
        "same_symbol_scanned_count",
        "same_symbol_included_count",
        "cross_symbol_scanned_count",
        "cross_symbol_included_count",
    ):
        value = selection.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"longitudinal context {key} must be a nonnegative integer")
        counts[key] = value
    if counts["same_symbol_included_count"] > counts["same_symbol_scanned_count"]:
        raise ValueError("longitudinal same-symbol included count exceeds scanned count")
    if counts["cross_symbol_included_count"] > counts["cross_symbol_scanned_count"]:
        raise ValueError("longitudinal cross-symbol included count exceeds scanned count")
    return {
        **base,
        **counts,
        "status": "loaded",
        "schema": LONGITUDINAL_CONTEXT_SCHEMA,
        "same_symbol_architecture_rollup_count": len(rollups),
    }


def run_analysis_stream(request: AnalysisRequest) -> Iterator[AnalysisEvent]:
    """Run a TradingAgents analysis, yield structured events, and persist history."""
    from .history import history_store
    from .audit_context import (
        bind_analysis_date,
        bind_analysis_mode,
        bind_information_cutoff,
        bind_run_id,
        bind_vendor_attempt_sink,
        reset_analysis_date,
        reset_analysis_mode,
        reset_information_cutoff,
        reset_run_id,
        reset_vendor_attempt_sink,
    )

    # 1. Register the run in SQLite history
    architecture_manifest = build_architecture_manifest(
        version=request.architecture_version,
        selected_analysts=request.selected_analysts,
        research_depth=request.research_depth,
        llm_provider=request.llm_provider,
        quick_think_llm=request.quick_think_llm,
        deep_think_llm=request.deep_think_llm,
        longitudinal_context_mode=request.longitudinal_context_mode,
    )
    history_store.create_run(
        run_id=request.run_id,
        ticker=request.ticker,
        analysis_date=str(request.analysis_date),
        asset_type=request.asset_type,
        selected_analysts=request.selected_analysts,
        llm_provider=request.llm_provider,
        research_depth=request.research_depth,
        architecture_version=request.architecture_version,
        architecture_fingerprint=architecture_fingerprint(architecture_manifest),
        architecture_manifest_json=__import__("json").dumps(
            architecture_manifest, ensure_ascii=False, sort_keys=True
        ),
    )
    # Mark the run as started in the database
    history_store.mark_started(request.run_id)
    audit_token = bind_run_id(request.run_id)
    analysis_date_token = bind_analysis_date(str(request.analysis_date))
    analysis_mode_token = bind_analysis_mode(request.analysis_mode)
    information_cutoff_token = bind_information_cutoff(request.information_cutoff)
    vendor_events: deque[AnalysisEvent] = deque()

    def collect_vendor_attempt(record: dict[str, Any]) -> None:
        vendor_events.append(_vendor_attempt_event(request.run_id, record))

    vendor_sink_token = bind_vendor_attempt_sink(collect_vendor_attempt)
    report_throttler = ReportSectionThrottler()

    has_error = False
    last_event = None
    try:
        for raw_event in _run_analysis_stream_impl(request):
            while vendor_events:
                vendor_event = vendor_events.popleft()
                history_store.add_event(request.run_id, vendor_event)
                yield vendor_event
            for event in report_throttler.push(raw_event):
                event = _with_vendor_summary(event, history_store)
                last_event = event
                # Persist the canonical, coalesced event sequence once.
                history_store.add_event(request.run_id, event)
                yield event
        for event in report_throttler.flush():
            last_event = event
            history_store.add_event(request.run_id, event)
            yield event
        while vendor_events:
            vendor_event = vendor_events.popleft()
            history_store.add_event(request.run_id, vendor_event)
            yield vendor_event
    except Exception as exc:
        has_error = True
        err_event = AnalysisEvent(
            type="error",
            run_id=request.run_id,
            content={"error": str(exc), "error_type": type(exc).__name__},
        )
        err_event = _with_vendor_summary(err_event, history_store)
        history_store.add_event(request.run_id, err_event)
        history_store.mark_finished(
            request.run_id, runtime_error_status(type(exc).__name__)
        )
        raise exc
    finally:
        if not has_error:
            status = "completed"
            if last_event and last_event.type == "error":
                error_content = (
                    last_event.content
                    if isinstance(last_event.content, dict)
                    else {}
                )
                status = runtime_error_status(error_content.get("error_type"))
            elif last_event and last_event.type == "run_cancelled":
                status = "cancelled"
            elif (
                last_event
                and last_event.type == "market_data_status"
                and isinstance(last_event.content, dict)
                and last_event.content.get("status") == "pending_provider_settlement"
            ):
                status = "market_data_pending"
            elif (
                last_event
                and last_event.type == "run_completed"
                and isinstance(last_event.content, dict)
                and last_event.content.get("decision_status") in {"review_required", "unavailable"}
            ):
                status = last_event.content["decision_status"]
            history_store.mark_finished(request.run_id, status)
        reset_information_cutoff(information_cutoff_token)
        reset_analysis_mode(analysis_mode_token)
        reset_analysis_date(analysis_date_token)
        reset_run_id(audit_token)
        reset_vendor_attempt_sink(vendor_sink_token)


def _vendor_attempt_event(run_id: str, record: dict[str, Any]) -> AnalysisEvent:
    """Expose a safe subset of an already-persisted vendor ledger row."""
    content = {
        key: record.get(key)
        for key in (
            "call_id", "attempt", "category", "method", "vendor", "agent",
            "symbol", "purpose", "status", "selected", "latency_ms", "error_type",
            "error_detail", "result_hash", "calculation_start", "requested_end",
            "data_latest_date", "started_at", "finished_at",
        )
    }
    return AnalysisEvent(
        type="vendor_attempt",
        run_id=run_id,
        timestamp=str(record.get("finished_at") or utc_timestamp()),
        agent=record.get("agent"),
        content=content,
    )


def _with_vendor_summary(event: AnalysisEvent, store: Any) -> AnalysisEvent:
    if event.type not in {"run_completed", "error"}:
        return event
    content = dict(event.content) if isinstance(event.content, dict) else {}
    summary = store.get_vendor_summary(event.run_id)
    content["data_status"] = summary["data_status"]
    content["vendor_summary"] = summary
    return AnalysisEvent(
        type=event.type,
        run_id=event.run_id,
        timestamp=event.timestamp,
        agent=event.agent,
        content=content,
    )


def _run_analysis_stream_impl(request: AnalysisRequest) -> Iterator[AnalysisEvent]:
    """Internal implementation of TradingAgents analysis streaming."""
    from .history import history_store

    config = build_runtime_config(request)
    selected_analysts = _ordered_analysts(request.selected_analysts)
    effective_manifest = build_architecture_manifest(
        version=request.architecture_version,
        selected_analysts=selected_analysts,
        research_depth=config.get("max_debate_rounds"),
        llm_provider=config.get("llm_provider"),
        quick_think_llm=config.get("quick_think_llm"),
        deep_think_llm=config.get("deep_think_llm"),
        longitudinal_context_mode=request.longitudinal_context_mode,
        effective_config=config,
    )
    history_store.update_run_architecture(
        request.run_id,
        architecture_version=request.architecture_version,
        architecture_fingerprint=architecture_fingerprint(effective_manifest),
        architecture_manifest_json=__import__("json").dumps(
            effective_manifest, ensure_ascii=False, sort_keys=True
        ),
    )
    callbacks = list(request.callbacks)
    # Runtime observability is a canonical invariant, not a frontend concern.
    # CLI/Web callers may supply their own stats handler so they can render live
    # counters; unattended timer and skill runs still need an audited snapshot.
    if not any(callable(getattr(callback, "get_stats", None)) for callback in callbacks):
        callbacks.append(StatsCallbackHandler())
    last_stats: dict[str, Any] | None = None

    yield AnalysisEvent(
        type="run_started",
        run_id=request.run_id,
        content={
            "ticker": request.ticker,
            "analysis_date": request.analysis_date,
            "market_data_date": None,
            "market_data_status": "pending_verification",
            "analysis_mode": request.analysis_mode,
            "information_cutoff": (
                request.information_cutoff
                if request.analysis_mode == "point_in_time"
                else "live_at_call_time"
            ),
            "asset_type": request.asset_type,
            "selected_analysts": selected_analysts,
        },
    )

    trace: list[dict[str, Any]] = []
    report_sections: dict[str, Any] = {}
    agent_status: dict[str, str] = {}
    processed_message_ids: set[str] = set()
    graph = None
    checkpointer_ctx = None

    try:
        # Apply the effective runtime vendor configuration before the readiness
        # probe.  Daily runs must be able to defer on a late final candle
        # without constructing LLM clients or resolving older reflections.
        from tradingagents.dataflows.config import set_config
        from tradingagents.dataflows.market_data_validator import verified_snapshot_dict

        set_config(config)
        verified_market_snapshot = verified_snapshot_dict(
            request.ticker, request.analysis_date
        )
        market_data_date = str(verified_market_snapshot["market_date"])
        history_store.update_run_market_data_date(
            request.run_id,
            market_data_date,
        )
        yield AnalysisEvent(
            type="market_data_status",
            run_id=request.run_id,
            content={
                "status": "verified",
                "requested_analysis_date": request.analysis_date,
                "market_data_date": market_data_date,
            },
        )
        if (
            request.require_exact_market_data_date
            and market_data_date < str(request.analysis_date)
        ):
            stats_event, last_stats = _stats_event(
                request.run_id, callbacks, last_stats, force=True
            )
            if stats_event is not None:
                yield stats_event
            yield AnalysisEvent(
                type="market_data_status",
                run_id=request.run_id,
                content={
                    "status": "pending_provider_settlement",
                    "requested_analysis_date": request.analysis_date,
                    "market_data_date": market_data_date,
                    "message": (
                        "verified daily bar is older than the required cutoff; "
                        "analysis deferred before LLM/graph construction"
                    ),
                },
            )
            return

        graph = TradingAgentsGraph(
            selected_analysts,
            config=config,
            debug=request.debug,
            callbacks=callbacks,
        )
        graph.ticker = request.ticker
        if request.analysis_mode == "live":
            graph._resolve_pending_entries(
                request.ticker,
                as_of_date=str(request.analysis_date),
            )

        if config.get("checkpoint_enabled"):
            checkpointer_ctx = get_checkpointer(config["data_cache_dir"], request.ticker)
            saver = checkpointer_ctx.__enter__()
            graph.graph = graph.workflow.compile(checkpointer=saver)

        instrument_context = graph.resolve_instrument_context(request.ticker, request.asset_type)
        longitudinal_context = ""
        if request.longitudinal_context_mode in {
            "portfolio_only", "research_and_portfolio"
        }:
            longitudinal_context = history_store.get_longitudinal_context(
                request.ticker,
                information_cutoff=(
                    request.information_cutoff
                    if request.analysis_mode == "point_in_time"
                    else None
                ),
            )
        yield AnalysisEvent(
            type="longitudinal_context_status",
            run_id=request.run_id,
            content=_longitudinal_context_status(
                longitudinal_context,
                mode=request.longitudinal_context_mode,
                information_cutoff=(
                    request.information_cutoff
                    if request.analysis_mode == "point_in_time"
                    else None
                ),
            ),
        )
        init_agent_state = graph.propagator.create_initial_state(
            request.ticker,
            request.analysis_date,
            asset_type=request.asset_type,
            past_context=longitudinal_context,
            instrument_context=instrument_context,
        )
        init_agent_state["verified_market_snapshot"] = verified_market_snapshot
        init_agent_state["trade_risk_policy"] = dict(config["trade_risk_policy"])
        init_agent_state["longitudinal_context_mode"] = request.longitudinal_context_mode
        args = graph.propagator.get_graph_args(callbacks=callbacks)
        if config.get("checkpoint_enabled"):
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = thread_id(
                request.ticker,
                str(request.analysis_date),
                request.run_id,
            )

        initial_analysts = {ANALYST_AGENT_NAMES[key] for key in selected_analysts}
        for agent in _initial_agents(selected_analysts):
            status = "in_progress" if agent in initial_analysts else "pending"
            agent_status[agent] = status
            yield AnalysisEvent(
                type="agent_status",
                run_id=request.run_id,
                agent=agent,
                content={"status": status},
            )

        for chunk in graph.graph.stream(init_agent_state, **args):
            trace.append(chunk)

            yield from _message_events(
                request.run_id,
                chunk.get("messages", []),
                processed_message_ids,
            )
            yield from _analyst_events(
                request.run_id,
                selected_analysts,
                chunk,
                report_sections,
                agent_status,
            )
            yield from _team_events(
                request.run_id,
                chunk,
                report_sections,
                agent_status,
            )
            stats_event, last_stats = _stats_event(request.run_id, callbacks, last_stats)
            if stats_event is not None:
                yield stats_event

        final_state: dict[str, Any] = {}
        for chunk in trace:
            final_state.update(chunk)

        graph.curr_state = final_state
        graph._log_state(request.analysis_date, final_state)
        if (
            final_state.get("final_trade_decision")
            and final_state.get("decision_status") == "validated"
        ):
            graph.memory_log.store_decision(
                ticker=request.ticker,
                trade_date=request.analysis_date,
                final_trade_decision=final_state["final_trade_decision"],
            )

        for agent, status in list(agent_status.items()):
            if status != "completed":
                agent_status[agent] = "completed"
                yield AnalysisEvent(
                    type="agent_status",
                    run_id=request.run_id,
                    agent=agent,
                    content={"status": "completed"},
                )

        report_path = write_report_tree(final_state, request.ticker, _report_dir(request, config))
        stats_event, last_stats = _stats_event(request.run_id, callbacks, last_stats, force=True)
        if stats_event is not None:
            yield stats_event
        decision_as_of = utc_timestamp()
        experiment_input = architecture_experiment_input_identity({
            **init_agent_state,
            **final_state,
        })
        yield AnalysisEvent(
            type="run_completed",
            run_id=request.run_id,
            timestamp=decision_as_of,
            content={
                "final_state": final_state,
                "decision": final_state.get("final_trade_decision"),
                "decision_status": final_state.get("decision_status", "unavailable"),
                "decision_as_of": decision_as_of,
                "market_data_date": market_data_date,
                "architecture_input_schema": experiment_input["schema"],
                "architecture_input_fingerprint": experiment_input["fingerprint"],
                "architecture_input_complete": experiment_input["complete"],
                "report_path": str(report_path),
            },
        )
    except Exception as exc:
        stats_event, last_stats = _stats_event(request.run_id, callbacks, last_stats, force=True)
        if stats_event is not None:
            yield stats_event
        yield AnalysisEvent(
            type="error",
            run_id=request.run_id,
            content={"error": str(exc), "error_type": type(exc).__name__},
        )
    finally:
        if checkpointer_ctx is not None:
            checkpointer_ctx.__exit__(None, None, None)
            if graph is not None:
                graph.graph = graph.workflow.compile()


def run_analysis_once(request: AnalysisRequest) -> AnalysisResult:
    """Run an analysis to completion and return the final result."""
    events = tuple(run_analysis_stream(request))
    error = next((event for event in events if event.type == "error"), None)
    if error is not None:
        content = error.content if isinstance(error.content, dict) else {}
        from .events import AnalysisExecutionError

        raise AnalysisExecutionError(str(content.get("error_type") or "RuntimeError"))

    completed = next((event for event in reversed(events) if event.type == "run_completed"), None)
    content = completed.content if completed and isinstance(completed.content, dict) else {}
    pending_market_data = next(
        (
            event
            for event in reversed(events)
            if event.type == "market_data_status"
            and isinstance(event.content, dict)
            and event.content.get("status") == "pending_provider_settlement"
        ),
        None,
    )
    decision_status = (
        "market_data_pending"
        if completed is None and pending_market_data is not None
        else content.get("decision_status", "unavailable")
    )
    decision = content.get("decision") if decision_status == "validated" else None
    return AnalysisResult(
        run_id=request.run_id,
        final_state=content.get("final_state") or {"final_trade_decision": content.get("decision")},
        decision=decision,
        decision_status=decision_status,
        report_path=Path(content["report_path"]) if content.get("report_path") else None,
        events=events,
    )


def _stats_event(
    run_id: str,
    callbacks: list[Any],
    last_stats: dict[str, Any] | None,
    force: bool = False,
) -> tuple[AnalysisEvent | None, dict[str, Any] | None]:
    for callback in callbacks:
        get_stats = getattr(callback, "get_stats", None)
        if not callable(get_stats):
            continue
        stats = get_stats()
        if force or stats != last_stats:
            return (
                AnalysisEvent(type="stats", run_id=run_id, content=stats),
                dict(stats),
            )
        return None, last_stats
    return None, last_stats


def _ordered_analysts(selected_analysts: tuple[str, ...]) -> list[str]:
    selected = {analyst.lower() for analyst in selected_analysts}
    ordered = [analyst for analyst in ANALYST_ORDER if analyst in selected]
    return ordered or ["market", "social", "news", "fundamentals"]


def _initial_agents(selected_analysts: list[str]) -> list[str]:
    agents = [ANALYST_AGENT_NAMES[key] for key in selected_analysts]
    agents.extend(
        [
            "Bull Researcher",
            "Bear Researcher",
            "Research Manager",
            "Trader",
            "Aggressive Analyst",
            "Neutral Analyst",
            "Conservative Analyst",
            "Portfolio Manager",
        ]
    )
    return agents


def _message_events(
    run_id: str,
    messages: list[Any],
    processed_message_ids: set[str],
) -> Iterator[AnalysisEvent]:
    for message in messages:
        msg_id = getattr(message, "id", None)
        if msg_id is not None:
            if msg_id in processed_message_ids:
                continue
            processed_message_ids.add(msg_id)

        message_type, content = _classify_message(message)
        if content:
            yield AnalysisEvent(
                type="message",
                run_id=run_id,
                agent=None,
                content={"message_type": message_type, "text": content},
            )

        for tool_call in getattr(message, "tool_calls", []) or []:
            if isinstance(tool_call, dict):
                name = tool_call.get("name")
                args = tool_call.get("args")
            else:
                name = getattr(tool_call, "name", None)
                args = getattr(tool_call, "args", None)
            yield AnalysisEvent(
                type="tool_call",
                run_id=run_id,
                content={"name": name, "args": args},
            )


def _analyst_events(
    run_id: str,
    selected_analysts: list[str],
    chunk: dict[str, Any],
    report_sections: dict[str, Any],
    agent_status: dict[str, str],
) -> Iterator[AnalysisEvent]:
    for analyst_key in selected_analysts:
        agent = ANALYST_AGENT_NAMES[analyst_key]
        report_key = ANALYST_REPORT_MAP[analyst_key]
        if chunk.get(report_key):
            yield from _report_section_event(
                run_id, report_sections, agent, report_key, chunk[report_key]
            )

        if report_sections.get(report_key):
            status = "completed"
        else:
            status = "in_progress"

        if agent_status.get(agent) != status:
            agent_status[agent] = status
            yield AnalysisEvent(
                type="agent_status",
                run_id=run_id,
                agent=agent,
                content={"status": status},
            )

    all_completed = all(
        report_sections.get(ANALYST_REPORT_MAP[key]) is not None
        for key in selected_analysts
    )
    if all_completed and selected_analysts:
        yield from _set_status(run_id, agent_status, "Bull Researcher", "in_progress")


def _team_events(
    run_id: str,
    chunk: dict[str, Any],
    report_sections: dict[str, Any],
    agent_status: dict[str, str],
) -> Iterator[AnalysisEvent]:
    debate = chunk.get("investment_debate_state") or {}
    if debate:
        bull = (debate.get("bull_history") or "").strip()
        bear = (debate.get("bear_history") or "").strip()
        judge = (debate.get("judge_decision") or "").strip()

        if bull:
            yield from _set_status(run_id, agent_status, "Bull Researcher", "in_progress")
            yield from _report_section_event(
                run_id, report_sections, "Bull Researcher", "bull_researcher", bull
            )
        if bear:
            yield from _set_status(run_id, agent_status, "Bear Researcher", "in_progress")
            yield from _report_section_event(
                run_id, report_sections, "Bear Researcher", "bear_researcher", bear
            )
        if judge:
            yield from _set_status(run_id, agent_status, "Bull Researcher", "completed")
            yield from _set_status(run_id, agent_status, "Bear Researcher", "completed")
            yield from _set_status(run_id, agent_status, "Research Manager", "in_progress")
            yield from _set_status(run_id, agent_status, "Research Manager", "completed")
            yield from _set_status(run_id, agent_status, "Trader", "in_progress")
            yield from _report_section_event(
                run_id, report_sections, "Research Manager", "investment_plan", judge
            )

    if chunk.get("trader_investment_plan"):
        yield from _set_status(run_id, agent_status, "Trader", "completed")
        yield from _set_status(run_id, agent_status, "Aggressive Analyst", "in_progress")
        yield from _report_section_event(
            run_id,
            report_sections,
            "Trader",
            "trader_investment_plan",
            chunk["trader_investment_plan"],
        )

    risk = chunk.get("risk_debate_state") or {}
    if risk:
        for key, agent, section in (
            ("aggressive_history", "Aggressive Analyst", "aggressive_analyst"),
            ("conservative_history", "Conservative Analyst", "conservative_analyst"),
            ("neutral_history", "Neutral Analyst", "neutral_analyst"),
        ):
            text = (risk.get(key) or "").strip()
            if text:
                yield from _set_status(run_id, agent_status, agent, "in_progress")
                yield from _report_section_event(
                    run_id, report_sections, agent, section, text
                )

        judge = (risk.get("judge_decision") or "").strip()
        if judge:
            yield from _set_status(run_id, agent_status, "Portfolio Manager", "in_progress")
            for agent in (
                "Aggressive Analyst",
                "Conservative Analyst",
                "Neutral Analyst",
                "Portfolio Manager",
            ):
                yield from _set_status(run_id, agent_status, agent, "completed")
            yield from _report_section_event(
                run_id, report_sections, "Portfolio Manager", "final_trade_decision", judge
            )


def _report_section_event(
    run_id: str,
    report_sections: dict[str, Any],
    agent: str,
    section: str,
    text: str,
) -> Iterator[AnalysisEvent]:
    """Emit a report update only when its cumulative graph value changed."""
    if report_sections.get(section) == text:
        return
    report_sections[section] = text
    yield AnalysisEvent(
        type="report_section",
        run_id=run_id,
        agent=agent,
        content={"section": section, "text": text},
    )


def _set_status(
    run_id: str,
    agent_status: dict[str, str],
    agent: str,
    status: str,
) -> Iterator[AnalysisEvent]:
    current = agent_status.get(agent)
    if current == status:
        return
    # Graph chunks contain cumulative state. Once an agent is completed, stale
    # fields in later chunks must never make it appear to run again.
    if current == "completed" and status != "completed":
        return
    agent_status[agent] = status
    yield AnalysisEvent(
        type="agent_status",
        run_id=run_id,
        agent=agent,
        content={"status": status},
    )


def _classify_message(message: Any) -> tuple[str, str | None]:
    content = _extract_content(getattr(message, "content", None))
    if isinstance(message, HumanMessage):
        return ("Control" if content == "Continue" else "User", content)
    if isinstance(message, ToolMessage):
        return ("Data", content)
    if isinstance(message, AIMessage):
        return ("Agent", content)
    return ("System", content)


def _extract_content(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, dict):
        text = str(content.get("text", "")).strip()
        return text or None
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")).strip())
            elif isinstance(item, str):
                parts.append(item.strip())
        text = " ".join(part for part in parts if part)
        return text or None
    text = str(content).strip()
    return text or None


def _report_dir(request: AnalysisRequest, config: dict[str, Any]) -> Path:
    if request.report_dir is not None:
        return Path(request.report_dir)
    return (
        Path(config["results_dir"])
        / safe_ticker_component(request.ticker)
        / str(request.analysis_date)
        / "reports"
    )
