import functools
import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import get_stock_data
from tradingagents.agents.utils.fundamental_data_tools import (
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
)
from tradingagents.agents.utils.macro_data_tools import get_macro_indicators
from tradingagents.agents.utils.market_data_validation_tools import get_verified_market_snapshot
from tradingagents.agents.utils.news_data_tools import (
    get_global_news,
    get_insider_transactions,
    get_news,
)
from tradingagents.agents.utils.prediction_markets_tools import get_prediction_markets
from tradingagents.agents.utils.technical_indicators_tools import get_indicators

# Public surface: the data tools are imported here so agents and the graph
# import them from one place, plus the instrument/language helpers defined below.
__all__ = [
    "get_stock_data",
    "get_indicators",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_news",
    "get_global_news",
    "get_insider_transactions",
    "get_macro_indicators",
    "get_prediction_markets",
    "get_verified_market_snapshot",
    "build_instrument_context",
    "resolve_instrument_identity",
    "get_instrument_context_from_state",
    "get_language_instruction",
    "get_no_preamble_instruction",
    "create_msg_delete",
]

logger = logging.getLogger(__name__)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English is explicitly configured, so no extra
    tokens are used for English reports.
    Applied to every agent whose output reaches the saved report —
    analysts, researchers, debaters, research manager, trader, and
    portfolio manager — so a non-English run produces a fully localized
    report rather than a mix of languages.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "Chinese")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def get_no_preamble_instruction() -> str:
    """Return a prompt instruction that forbids reasoning preamble in report output.

    LLMs sometimes include internal chain-of-thought text (e.g.
    'I have all the data I need', 'Note one discrepancy...') at the start of
    their final report output, breaking professional report formatting.
    This instruction is added to every analyst system message to prevent it.
    """
    return (
        " IMPORTANT OUTPUT FORMAT: Do NOT include any internal reasoning,"
        " meta-commentary, scratchpad text, or status statements"
        " (such as 'I have all the data I need', 'I was able to gather',"
        " 'Note one discrepancy', 'I\'ll now write', 'Based on the data I gathered',"
        " 'Let me now', 'After gathering') in your report."
        " Begin your response DIRECTLY with the report content,"
        " starting with a proper markdown heading (e.g. '# Market Analysis Report')."
        " Do not add any introductory sentence before the first heading."
    )


def _clean_identity_value(value: Any) -> str | None:
    """Return a trimmed string, or None for empty / placeholder-ish values."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"none", "n/a", "nan", "null"}:
        return None
    return cleaned


@functools.lru_cache(maxsize=256)
def resolve_instrument_identity(ticker: str) -> dict:
    """Resolve deterministic identity metadata (company name, sector, …) for a ticker.

    This exists to stop the pipeline from hallucinating a *different* company
    when a chart pattern suggests a different industry than the real one
    (#814): without a ground-truth name, the market analyst would pattern-match
    the price action to a narrative and invent an identity that then cascaded
    through every downstream agent.

    Best-effort by design: we try westock-data profile first, and fall back to
    Longbridge MCP/CLI static_info.
    """
    from tradingagents.dataflows.symbol_utils import is_westock_available, to_westock_code, run_westock

    info = {}
    
    # Try westock-data profile first
    if is_westock_available():
        w_code = to_westock_code(ticker)
        logger.info("westock-data available; resolving instrument identity for %s (mapped to %s)", ticker, w_code)
        try:
            raw = run_westock(["profile", w_code], raw=True)
            import json
            res = json.loads(raw)
            if res and res.get("success") and isinstance(res.get("data"), dict):
                data = res["data"]
                info = {
                    "longName": data.get("name"),
                    "sector": data.get("industry"),  # westock has industry as top sector
                    "industry": data.get("industry"),
                    "exchange": data.get("exchange"),
                    "quoteType": "EQUITY",
                }
        except Exception as exc:
            logger.warning("westock-data identity lookup failed for %s: %s; trying Longbridge", ticker, exc)

    # Try Longbridge MCP if westock is unavailable or failed
    if not info:
        try:
            from tradingagents.dataflows.longbridge_mcp import normalize_symbol as mcp_normalize, _client, _first_item
            mcp_sym = mcp_normalize(ticker)
            client = _client()
            s = client.call_tool("static_info", {"symbols": [mcp_sym]})
            s_item = _first_item(s)
            if s_item and isinstance(s_item, dict):
                info = {
                    "longName": s_item.get("name"),
                    "exchange": s_item.get("exchange"),
                    "quoteType": "EQUITY",
                }
        except Exception as mcp_exc:
            logger.debug("Longbridge MCP identity fallback failed: %s; trying CLI", mcp_exc)
            # Try Longbridge CLI
            try:
                from tradingagents.dataflows.longbridge import normalize_symbol as cli_normalize, _run_cli_json_list
                cli_sym = cli_normalize(ticker)
                static_raw = _run_cli_json_list(["static", cli_sym])
                if static_raw and isinstance(static_raw, list) and isinstance(static_raw[0], dict):
                    s_item = static_raw[0]
                    info = {
                        "longName": s_item.get("name"),
                        "exchange": s_item.get("exchange"),
                        "quoteType": "EQUITY",
                    }
            except Exception as cli_exc:
                logger.debug("Longbridge CLI identity fallback failed: %s", cli_exc)

    identity: dict[str, str] = {}
    company_name = _clean_identity_value(info.get("longName")) or _clean_identity_value(
        info.get("shortName")
    )
    if company_name:
        identity["company_name"] = company_name
    for source_key, target_key in (
        ("sector", "sector"),
        ("industry", "industry"),
        ("exchange", "exchange"),
        ("quoteType", "quote_type"),
    ):
        value = _clean_identity_value(info.get(source_key))
        if value:
            identity[target_key] = value
    return identity


def build_instrument_context(
    ticker: str,
    asset_type: str = "stock",
    identity: Mapping[str, str] | None = None,
) -> str:
    """Describe the exact instrument so agents preserve identity and ticker.

    When ``identity`` is provided (resolved deterministically via
    :func:`resolve_instrument_identity`), the company name and business
    classification are injected so agents anchor to the real company rather
    than pattern-matching the price chart to a wrong one (#814).
    """
    is_crypto = asset_type == "crypto"
    instrument_label = "asset" if is_crypto else "instrument"
    context = (
        f"The {instrument_label} to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`, `-USD`)."
    )

    details = []
    if identity:
        name = identity.get("company_name") or identity.get("name")
        if name:
            details.append(f"{'Name' if is_crypto else 'Company'}: {name}")
        sector, industry = identity.get("sector"), identity.get("industry")
        if sector and industry:
            details.append(f"Business classification: {sector} / {industry}")
        elif sector:
            details.append(f"Sector: {sector}")
        elif industry:
            details.append(f"Industry: {industry}")
        if identity.get("exchange"):
            details.append(f"Exchange: {identity['exchange']}")

    if details:
        context += (
            f" Resolved identity: {'; '.join(details)}. "
            "Do not substitute a different company or ticker unless a tool "
            "result explicitly disproves this resolved identity."
        )

    if is_crypto:
        context += (
            " Treat it as a crypto asset rather than a company, and do not "
            "assume company fundamentals are available."
        )
    return context


def get_instrument_context_from_state(state: Mapping[str, Any]) -> str:
    """Return the instrument context for the current run.

    Prefers the identity-resolved context computed once at run start and
    stored on the state (see ``TradingAgentsGraph.resolve_instrument_context``).
    Falls back to a ticker-only context — with no network lookup — when the
    state was constructed without it (bare programmatic states, tests), so a
    consumer is never forced to make a westock call mid-graph.
    """
    context = state.get("instrument_context")
    if isinstance(context, str) and context.strip():
        return context
    return build_instrument_context(
        str(state["company_of_interest"]),
        state.get("asset_type", "stock"),
    )


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add a context-anchored placeholder.

        The placeholder must not be a bare ``"Continue"``: some
        OpenAI-compatible providers interpret that literally as the user task
        and produce output about the word "continue" instead of analysing the
        instrument (#888). Anchoring it to the resolved instrument context and
        date keeps the next analyst on-task even if the provider treats the
        placeholder as a standalone request.
        """
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        instrument_context = get_instrument_context_from_state(state)
        trade_date = state.get("trade_date", "the requested date")
        placeholder = HumanMessage(
            content=(
                f"Proceed with your assigned analysis for this workflow. "
                f"{instrument_context} The analysis date is {trade_date}."
            )
        )
        return {"messages": removal_operations + [placeholder]}

    return delete_messages


