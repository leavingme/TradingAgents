# TradingAgents/graph/trading_graph.py

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from langgraph.prebuilt import ToolNode

# Import the abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_stock_data,
    get_verified_market_snapshot,
    resolve_instrument_identity,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.architecture import (
    AGENT_ARCHITECTURE_VERSION,
    architecture_fingerprint,
    build_architecture_manifest,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.evaluation import DEFAULT_OUTCOME_HORIZON_SESSIONS
from tradingagents.llm_clients import create_llm_client
from tradingagents.reporting import write_report_tree

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .reflection import Reflector
from .setup import GraphSetup
from .signal_processing import SignalProcessor
from .tool_error_handling import recover_invalid_tool_arguments

logger = logging.getLogger(__name__)


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []
        self.selected_analysts = tuple(selected_analysts)

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()

        self.memory_log = TradingMemoryLog(self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        # Sampling temperature is cross-provider: forward it whenever set.
        # float() here so a value coming from a TRADINGAGENTS_TEMPERATURE env
        # string ("0.2") works the same as a programmatic float.
        temperature = self.config.get("temperature")
        if temperature is not None and temperature != "":
            kwargs["temperature"] = float(temperature)

        return kwargs

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                    # Deterministic verification snapshot (bound to the analyst
                    # LLM and required by its prompt; must be executable here or
                    # the call fails and the model reports it "unavailable").
                    get_verified_market_snapshot,
                ],
                handle_tool_errors=False,
                wrap_tool_call=recover_invalid_tool_arguments,
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ],
                handle_tool_errors=False,
                wrap_tool_call=recover_invalid_tool_arguments,
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                    get_macro_indicators,
                    get_prediction_markets,
                ],
                handle_tool_errors=False,
                wrap_tool_call=recover_invalid_tool_arguments,
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ],
                handle_tool_errors=False,
                wrap_tool_call=recover_invalid_tool_arguments,
            ),
        }

    def _resolve_benchmark(self, ticker: str) -> str:
        """Pick the benchmark ticker for alpha calculation against ``ticker``.

        ``config["benchmark_ticker"]`` overrides everything when set; otherwise
        the suffix map matches the ticker's exchange suffix (e.g. ``.T`` for
        Tokyo). US-listed tickers without a dotted suffix fall through to the
        empty-suffix entry (SPY by default). Unrecognised suffixes (including
        US tickers with dots like ``BRK.B``) also fall back to the empty-suffix
        entry, which is the right default because the alpha calculation works
        in USD.
        """
        explicit = self.config.get("benchmark_ticker")
        if explicit:
            return explicit
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = ticker.upper()
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                return benchmark
        return benchmark_map.get("", "SPY")

    def _fetch_returns(
        self, ticker: str, trade_date: str,
        holding_days: int = DEFAULT_OUTCOME_HORIZON_SESSIONS,
        benchmark: str = "SPY", as_of_date: str | None = None,
        return_details: bool = False, decision_as_of: str | None = None,
    ):
        """Fetch an information-safe raw/alpha return after the decision day.

        ``benchmark`` is the index used as the alpha baseline (resolved by the
        caller via ``_resolve_benchmark``). Returns ``(raw_return, alpha_return,
        actual_holding_days)`` or ``(None, None, None)`` if price data is
        unavailable (too recent, delisted, or network error).
        """
        from tradingagents.dataflows.stockstats_utils import load_ohlcv
        from tradingagents.dataflows.config import get_config
        from tradingagents.dataflows.ohlcv_cache import (
            market_timezone_for_cache_key,
            symbol_to_cache_key,
        )
        from tradingagents.dataflows.ohlcv_model import resolve_ohlcv_source_id
        from tradingagents.dataflows.symbol_utils import normalize_symbol
        from tradingagents.evaluation import OutcomeMeasurement
        import pandas as pd
        from zoneinfo import ZoneInfo

        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            canonical_ticker = normalize_symbol(ticker)
            ticker_cache_key = symbol_to_cache_key(
                safe_ticker_component(canonical_ticker)
            )
            decision_timezone = market_timezone_for_cache_key(ticker_cache_key)
            if decision_as_of is None:
                if return_details:
                    raise ValueError("audited outcome requires decision_as_of")
                entry_cutoff_date = start.date()
                canonical_decision_as_of = None
            else:
                parsed_decision = datetime.fromisoformat(
                    str(decision_as_of).replace("Z", "+00:00")
                )
                if parsed_decision.tzinfo is None or parsed_decision.utcoffset() is None:
                    raise ValueError("decision_as_of must include a timezone")
                entry_cutoff_date = max(
                    start.date(),
                    parsed_decision.astimezone(ZoneInfo(decision_timezone)).date(),
                )
                canonical_decision_as_of = parsed_decision.astimezone(
                    ZoneInfo("UTC")
                ).isoformat()
            end = datetime.combine(entry_cutoff_date, datetime.min.time()) + timedelta(
                days=holding_days + 7
            )
            end_str = as_of_date or end.strftime("%Y-%m-%d")

            # Use the canonical configured OHLCV route/cache for both legs.
            # Evaluation must not silently hard-code Westock while the analysis
            # itself is configured Longbridge-first.
            stock = load_ohlcv(ticker, end_str)
            bench = load_ohlcv(benchmark, end_str)
            if stock.empty or bench.empty:
                return None if return_details else (None, None, None)

            def closes(frame: pd.DataFrame, label: str) -> pd.DataFrame:
                required = {"Date", "Close"}
                if not required.issubset(frame.columns):
                    raise ValueError(f"{label} OHLCV lacks Date/Close")
                out = frame[["Date", "Close"]].copy()
                out["Date"] = pd.to_datetime(out["Date"], errors="coerce", utc=True)
                out["Date"] = out["Date"].dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
                out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
                return out.dropna().drop_duplicates("Date", keep="last")

            stock_closes = closes(stock, ticker).rename(columns={"Close": "stock_close"})
            bench_closes = closes(bench, benchmark).rename(columns={"Close": "benchmark_close"})
            common = stock_closes.merge(bench_closes, on="Date", how="inner").sort_values("Date")
            cutoff_date = pd.Timestamp(entry_cutoff_date)
            end_date = pd.Timestamp(end_str)
            common = common[(common["Date"] > cutoff_date) & (common["Date"] <= end_date)]
            # A daily close on the decision's local market date may already
            # precede a live recommendation, so it is never an executable
            # entry. Require the first later common close plus five subsequent
            # common closes; never relabel a shorter outcome as 5d.
            if len(common) < holding_days + 1:
                return None if return_details else (None, None, None)
            entry = common.iloc[0]
            exit_row = common.iloc[holding_days]
            raw = float((exit_row["stock_close"] - entry["stock_close"]) / entry["stock_close"])
            bench_ret = float(
                (exit_row["benchmark_close"] - entry["benchmark_close"])
                / entry["benchmark_close"]
            )
            alpha = raw - bench_ret
            if return_details:
                entry_date = entry["Date"].strftime("%Y-%m-%d")
                exit_date = exit_row["Date"].strftime("%Y-%m-%d")
                cache_dir = str(get_config()["data_cache_dir"])

                def source_id(symbol: str, trading_date: str) -> str:
                    canonical = normalize_symbol(symbol)
                    cache_key = symbol_to_cache_key(safe_ticker_component(canonical))
                    resolved = resolve_ohlcv_source_id(
                        cache_dir, cache_key, trading_date
                    )
                    if resolved is None:
                        raise ValueError(
                            f"missing exact OHLCV provenance for {symbol} on {trading_date}"
                        )
                    return resolved

                return OutcomeMeasurement(
                    raw_return=raw,
                    benchmark_return=bench_ret,
                    alpha_return=alpha,
                    horizon_sessions=holding_days,
                    entry_date=entry_date,
                    exit_date=exit_date,
                    stock_entry_close=float(entry["stock_close"]),
                    stock_exit_close=float(exit_row["stock_close"]),
                    benchmark_entry_close=float(entry["benchmark_close"]),
                    benchmark_exit_close=float(exit_row["benchmark_close"]),
                    stock_entry_source_id=source_id(ticker, entry_date),
                    stock_exit_source_id=source_id(ticker, exit_date),
                    benchmark_entry_source_id=source_id(benchmark, entry_date),
                    benchmark_exit_source_id=source_id(benchmark, exit_date),
                    decision_as_of=str(canonical_decision_as_of),
                    decision_timezone=decision_timezone,
                    entry_cutoff_date=entry_cutoff_date.isoformat(),
                )
            return raw, alpha, holding_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s vs %s (will retry next run): %s",
                ticker, trade_date, benchmark, e,
            )
            return None if return_details else (None, None, None)

    def _resolve_pending_entries(self, ticker: str, as_of_date: str | None = None) -> None:
        """Resolve every unevaluated validated SQLite run for ``ticker``.

        SQLite, not the compatibility Markdown log, is the pending-work source.
        Each run is measured from its own persisted decision timestamp so two
        runs sharing an analysis date cannot inherit an earlier run's entry.
        """
        from tradingagents.agents.utils.rating import parse_rating
        from tradingagents.evaluation import OutcomeMeasurement, score_outcome
        from tradingagents.runtime.audit_context import current_run_id
        from tradingagents.runtime.audit_context import (
            bind_vendor_call_purpose,
            reset_vendor_call_purpose,
        )
        from tradingagents.runtime.history import history_store

        prior_runs = history_store.list_unevaluated_validated_runs(ticker=ticker)
        if not prior_runs:
            return
        benchmark = self._resolve_benchmark(ticker)
        resolved_by_date: dict[str, OutcomeMeasurement] = {}
        for prior_run in prior_runs:
            run_record = history_store.get_run(prior_run["run_id"])
            terminal = next(
                (
                    event
                    for event in reversed((run_record or {}).get("events", []))
                    if event.get("type") == "run_completed"
                    and isinstance(event.get("content"), dict)
                ),
                None,
            )
            decision = terminal["content"].get("decision") if terminal else None
            decision_as_of = (
                terminal["content"].get("decision_as_of") if terminal else None
            ) or (terminal.get("timestamp") if terminal else None)
            if not isinstance(decision, str) or not decision.strip():
                raise RuntimeError(
                    "validated historical run lacks its own persisted decision: "
                    f"{prior_run['run_id']}"
                )
            if not isinstance(decision_as_of, str) or not decision_as_of.strip():
                raise RuntimeError(
                    "validated historical run lacks decision_as_of: "
                    f"{prior_run['run_id']}"
                )
            purpose_token = bind_vendor_call_purpose("outcome_evaluation")
            try:
                measurement = self._fetch_returns(
                    ticker,
                    prior_run["analysis_date"],
                    benchmark=benchmark,
                    as_of_date=as_of_date,
                    return_details=True,
                    decision_as_of=decision_as_of,
                )
            finally:
                reset_vendor_call_purpose(purpose_token)
            if measurement is None:
                continue
            if not isinstance(measurement, OutcomeMeasurement):
                raise RuntimeError("audited outcome resolver returned no provenance")
            rating = parse_rating(decision)
            scored = score_outcome(rating, measurement.alpha_return)
            history_store.add_decision_evaluation({
                "run_id": prior_run["run_id"],
                "horizon_sessions": measurement.horizon_sessions,
                "evaluated_by_run_id": current_run_id(),
                "ticker": ticker,
                "analysis_date": prior_run["analysis_date"],
                "rating": rating,
                "benchmark": benchmark,
                "raw_return": measurement.raw_return,
                "benchmark_return": measurement.benchmark_return,
                "alpha_return": measurement.alpha_return,
                "exposure": scored["exposure"],
                "directional_hit": scored["directional_hit"],
                "score": scored["score"],
                "scoring_version": scored["scoring_version"],
                "hold_band": scored["hold_band"],
                "architecture_version": prior_run.get(
                    "architecture_version", "legacy"
                ),
                "architecture_fingerprint": prior_run.get(
                    "architecture_fingerprint", "legacy-unspecified"
                ),
                **measurement.__dict__,
            })
            resolved_by_date.setdefault(prior_run["analysis_date"], measurement)

        # Markdown reflection remains a best-effort compatibility view. It is
        # updated only after canonical SQLite persistence succeeds and never
        # controls whether a run is eligible for future settlement.
        markdown_updates = []
        for entry in self.memory_log.get_pending_entries():
            if entry.get("ticker") != ticker:
                continue
            measurement = resolved_by_date.get(str(entry.get("date")))
            if measurement is None:
                continue
            try:
                reflection = self.reflector.reflect_on_final_decision(
                    final_decision=entry.get("decision", ""),
                    raw_return=measurement.raw_return,
                    alpha_return=measurement.alpha_return,
                    benchmark_name=benchmark,
                )
            except Exception as exc:
                logger.warning("Could not write compatibility reflection: %s", exc)
                continue
            markdown_updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": measurement.raw_return,
                "alpha_return": measurement.alpha_return,
                "holding_days": measurement.horizon_sessions,
                "reflection": reflection,
            })
        if markdown_updates:
            self.memory_log.batch_update_with_outcomes(markdown_updates)

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
        """Resolve ticker identity once and return the full instrument context.

        Deterministic westock lookup (cached, fail-open) injected into a
        context string so every agent anchors to the real company instead of
        hallucinating one from the price chart (#814). Both the propagate()
        path and the CLI call this so the resolved identity reaches the whole
        graph regardless of entry point.
        """
        identity = resolve_instrument_identity(ticker)
        return build_instrument_context(ticker, asset_type, identity)

    def propagate(
        self,
        company_name,
        trade_date,
        asset_type: str = "stock",
        *,
        run_id: str | None = None,
        analysis_mode: str = "live",
        information_cutoff: str | None = None,
    ):
        """Run the trading agents graph for a company on a specific date.

        ``asset_type`` selects between the stock pipeline (default) and the
        crypto pipeline (``"crypto"``) shipped in #567 — the CLI auto-detects
        from the ticker; programmatic callers pass it explicitly. When
        ``checkpoint_enabled`` is set in config, the graph is recompiled with
        a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.
        """
        from uuid import uuid4

        from tradingagents.runtime.audit_context import (
            bind_analysis_date,
            bind_analysis_mode,
            bind_information_cutoff,
            bind_run_id,
            reset_analysis_date,
            reset_analysis_mode,
            reset_information_cutoff,
            reset_run_id,
            validate_temporal_context,
        )
        from tradingagents.runtime.events import AnalysisEvent
        from tradingagents.runtime.history import history_store

        self.ticker = company_name
        validate_temporal_context(str(trade_date), analysis_mode, information_cutoff)
        if self.config.get("checkpoint_enabled") and not run_id:
            raise ValueError(
                "checkpoint resume requires explicit run_id; use the original run ID"
            )
        run_id = run_id or f"{safe_ticker_component(company_name)}-{uuid4().hex[:12]}"

        longitudinal_context_mode = self.config.get(
            "longitudinal_context_mode", "research_and_portfolio"
        )
        architecture_manifest = build_architecture_manifest(
            version=AGENT_ARCHITECTURE_VERSION,
            selected_analysts=tuple(self.selected_analysts),
            research_depth=self.config.get("max_debate_rounds"),
            llm_provider=self.config.get("llm_provider"),
            quick_think_llm=self.config.get("quick_think_llm"),
            deep_think_llm=self.config.get("deep_think_llm"),
            longitudinal_context_mode=longitudinal_context_mode,
            effective_config=self.config,
        )
        history_store.create_run(
            run_id=run_id,
            ticker=company_name,
            analysis_date=str(trade_date),
            asset_type=asset_type,
            selected_analysts=tuple(self.selected_analysts),
            llm_provider=self.config.get("llm_provider"),
            research_depth=self.config.get("max_debate_rounds"),
            architecture_version=AGENT_ARCHITECTURE_VERSION,
            architecture_fingerprint=architecture_fingerprint(architecture_manifest),
            architecture_manifest_json=json.dumps(
                architecture_manifest, ensure_ascii=False, sort_keys=True
            ),
        )
        history_store.mark_started(run_id)
        audit_token = bind_run_id(run_id)
        analysis_date_token = bind_analysis_date(str(trade_date))
        analysis_mode_token = bind_analysis_mode(analysis_mode)
        information_cutoff_token = bind_information_cutoff(information_cutoff)

        def record_failure(exc: Exception) -> None:
            history_store.add_event(run_id, AnalysisEvent(
                type="error",
                run_id=run_id,
                content={"error": str(exc), "error_type": type(exc).__name__},
            ))
            history_store.mark_finished(run_id, "failed")

        try:
            # Resolve pending outcomes only after the audited run context exists.
            if analysis_mode == "live":
                self._resolve_pending_entries(company_name, as_of_date=str(trade_date))

            if self.config.get("checkpoint_enabled"):
                self._checkpointer_ctx = get_checkpointer(
                    self.config["data_cache_dir"], company_name
                )
                saver = self._checkpointer_ctx.__enter__()
                self.graph = self.workflow.compile(checkpointer=saver)

                step = checkpoint_step(
                    self.config["data_cache_dir"], company_name, str(trade_date), run_id
                )
                if step is not None:
                    logger.info(
                        "Resuming from step %d for %s on %s",
                        step, company_name, trade_date,
                    )
                else:
                    logger.info("Starting fresh for %s on %s", company_name, trade_date)
        except Exception as exc:
            record_failure(exc)
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()
            reset_information_cutoff(information_cutoff_token)
            reset_analysis_mode(analysis_mode_token)
            reset_analysis_date(analysis_date_token)
            reset_run_id(audit_token)
            raise

        try:
            result = self._run_graph(
                company_name, trade_date, asset_type=asset_type, run_id=run_id
            )
            final_state = result[0]
            decision_status = final_state.get("decision_status", "unavailable")
            history_store.add_event(run_id, AnalysisEvent(
                type="run_completed",
                run_id=run_id,
                content={
                    "decision": (
                        final_state.get("final_trade_decision")
                        if decision_status == "validated" else None
                    ),
                    "decision_status": decision_status,
                },
            ))
            history_store.mark_finished(
                run_id,
                "completed" if decision_status == "validated" else decision_status,
            )
            return result
        except Exception as exc:
            record_failure(exc)
            raise
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()
            reset_information_cutoff(information_cutoff_token)
            reset_analysis_mode(analysis_mode_token)
            reset_analysis_date(analysis_date_token)
            reset_run_id(audit_token)

    def save_reports(self, final_state, ticker, save_path=None) -> Path:
        """Write the markdown report tree for a completed run, like the CLI does.

        Programmatic callers get the same on-disk reports the CLI produces. Pass
        an explicit ``save_path`` or let it default under ``results_dir``.
        """
        if save_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = (
                Path(self.config["results_dir"])
                / "reports"
                / f"{safe_ticker_component(ticker)}_{stamp}"
            )
        return write_report_tree(final_state, ticker, save_path)

    def _run_graph(
        self, company_name, trade_date, asset_type: str = "stock", *, run_id: str | None = None
    ):
        """Execute the graph and write the resulting state to disk and memory log."""
        # Initialize state with canonical SQLite outcome evidence. The
        # compatibility Markdown log is not trusted as decision context because
        # its reflection prose is LLM-generated and lacks structured provenance.
        from tradingagents.runtime.audit_context import (
            current_analysis_mode,
            current_information_cutoff,
        )
        from tradingagents.runtime.history import history_store

        past_context = history_store.get_longitudinal_context(
            company_name,
            information_cutoff=(
                current_information_cutoff()
                if current_analysis_mode() == "point_in_time"
                else None
            ),
        )
        instrument_context = self.resolve_instrument_context(company_name, asset_type)
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            instrument_context=instrument_context,
            longitudinal_context_mode=self.config.get(
                "longitudinal_context_mode", "research_and_portfolio"
            ),
        )
        from tradingagents.dataflows.market_data_validator import verified_snapshot_dict

        init_agent_state["verified_market_snapshot"] = verified_snapshot_dict(
            company_name, str(trade_date)
        )
        init_agent_state["trade_risk_policy"] = dict(self.config["trade_risk_policy"])
        args = self.propagator.get_graph_args()

        # Inject thread_id so same ticker+date resumes, different date starts fresh.
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date), run_id)
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        if self.debug:
            trace = []
            last_printed = None
            for chunk in self.graph.stream(init_agent_state, **args):
                if chunk["messages"]:
                    msg = chunk["messages"][-1]
                    # Nodes after the trader don't append to messages, so the
                    # same trailing message repeats across chunks. Print it only
                    # when it changes (#1027); the trace/state merge is unchanged.
                    signature = (type(msg).__name__, getattr(msg, "content", None))
                    if signature != last_printed:
                        msg.pretty_print()
                        last_printed = signature
                    trace.append(chunk)
            # Streamed chunks are per-node deltas. Merge them so the returned
            # state matches what graph.invoke() yields in the non-debug path.
            final_state = {}
            for chunk in trace:
                final_state.update(chunk)
        else:
            final_state = self.graph.invoke(init_agent_state, **args)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        if final_state.get("decision_status") == "validated":
            self.memory_log.store_decision(
                ticker=company_name,
                trade_date=trade_date,
                final_trade_decision=final_state["final_trade_decision"],
            )

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date), run_id
            )

        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
