"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Westock news — which led LLMs to fabricate
Reddit/X/StockTwits content under prompt pressure (verified live).

The redesigned agent pre-fetches four complementary data sources before
the LLM is invoked and transports them in a separate untrusted-data message:

  1. News headlines     — Westock (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                           user-labeled Bullish/Bearish sentiment tags
  3. Reddit posts        — r/wallstreetbets, r/stocks, r/investing
  4. X/Twitter posts     — validated read-only bird search results

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern (json_schema for
OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic), falling
back to free-text generation for providers that lack native support, so
the sentiment header (band + score + confidence) is deterministic across
runs and providers instead of free-form per-model prose.

See: https://github.com/TauricResearch/TradingAgents/issues/557
See: https://github.com/TauricResearch/TradingAgents/issues/796
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.analysts.prompts import (
    PREFETCHED_DATA_COLLABORATION_PROMPT,
    build_sentiment_analyst_system_message,
)
from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_news,
    get_social_posts,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.reddit import fetch_reddit_posts
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages
from tradingagents.dataflows.untrusted_content import (
    isolate_untrusted_content,
    render_untrusted_payload,
)


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def _social_source_enabled(source: str) -> bool:
    configured = get_config().get("data_vendors", {}).get("social_data", "")
    return source in {item.strip() for item in configured.split(",") if item.strip()}


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits + Reddit data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output (with a free-text fallback for providers
    that do not support it).
    """
    from tradingagents.agents.utils.agent_utils import get_no_preamble_instruction
    from tradingagents.dataflows.symbol_utils import resolve_social_query

    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Resolve social-media specific tickers/queries to prevent empty feeds
        # on foreign tickers (e.g. 0700.HK -> TCEHY / Tencent)
        sq = resolve_social_query(ticker)

        # Pre-fetch all four sources. Each fetcher degrades gracefully and
        # returns a string (no exceptions surface from here), so the LLM
        # always sees something — either real data or a clear placeholder.
        news_block = get_news.func(ticker, start_date, end_date)
        stocktwits_block = fetch_stocktwits_messages(sq["stocktwits"], limit=30)
        reddit_block = (
            fetch_reddit_posts(sq["reddit"])
            if _social_source_enabled("reddit")
            else "<Reddit disabled in social_data settings>"
        )
        try:
            twitter_block = get_social_posts.func(ticker, start_date, end_date)
        except Exception as exc:
            twitter_block = f"<X/Twitter unavailable: {type(exc).__name__}>"

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
        ) + get_no_preamble_instruction()

        untrusted_payload = render_untrusted_payload({
            "news": news_block,
            "stocktwits": stocktwits_block,
            "reddit": reddit_block,
            "twitter": twitter_block,
        })

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    PREFETCHED_DATA_COLLABORATION_PROMPT,
                ),
                ("human", "UNTRUSTED_DATA_JSON:\n{untrusted_payload}"),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)
        prompt = prompt.partial(untrusted_payload=untrusted_payload)

        # Format the template into a concrete message list so the structured
        # and free-text paths receive the same input. No bind_tools — the
        # data is already in the prompt.
        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )
        report_text = isolate_untrusted_content(
            "sentiment_report", report_text
        ).content

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """Assemble instructions only; external content is a separate data message."""
    return build_sentiment_analyst_system_message(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
    )


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`.

    Kept so existing code that imports ``create_social_media_analyst``
    continues to work.

    .. deprecated::
        Import :func:`create_sentiment_analyst` directly instead.
    """
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
