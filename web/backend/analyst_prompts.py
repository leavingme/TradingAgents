"""Read-only analyst prompt metadata exposed to the WebUI."""

from __future__ import annotations

from tradingagents.agents.analysts.prompts import (
    PREFETCHED_DATA_COLLABORATION_PROMPT,
    TOOL_CALLING_COLLABORATION_PROMPT,
    build_fundamentals_analyst_system_message,
    build_market_analyst_system_message,
    build_news_analyst_system_message,
    build_sentiment_analyst_system_message,
    render_full_prompt,
)
from tradingagents.agents import (
    FUNDAMENTALS_ANALYST_TOOL_NAMES,
    MARKET_ANALYST_TOOL_NAMES,
)


def analyst_prompt_payload() -> dict[str, list[dict[str, object]]]:
    return {
        "analysts": [
            {
                "key": "market",
                "title": "Market Analyst",
                "description": "Technical market analysis using batch indicators and a compact verified market snapshot.",
                "tools": list(MARKET_ANALYST_TOOL_NAMES),
                "prompt": render_full_prompt(
                    TOOL_CALLING_COLLABORATION_PROMPT,
                    build_market_analyst_system_message(),
                    MARKET_ANALYST_TOOL_NAMES,
                ),
            },
            {
                "key": "social",
                "title": "Sentiment Analyst",
                "description": "Sentiment analysis from pre-fetched news, X/Twitter, StockTwits, and Reddit posts.",
                "tools": ["get_news", "get_social_posts", "fetch_stocktwits_messages", "fetch_reddit_posts"],
                "prompt": render_full_prompt(
                    PREFETCHED_DATA_COLLABORATION_PROMPT,
                    build_sentiment_analyst_system_message(
                        ticker="{ticker}",
                        start_date="{start_date}",
                        end_date="{end_date}",
                    ),
                    [],
                ),
            },
            {
                "key": "news",
                "title": "News Analyst",
                "description": "Recent company or asset news plus macro and prediction-market context.",
                "tools": ["get_news", "get_global_news", "get_macro_indicators", "get_prediction_markets"],
                "prompt": render_full_prompt(
                    TOOL_CALLING_COLLABORATION_PROMPT,
                    build_news_analyst_system_message("{company_or_asset}"),
                    ["get_news", "get_global_news", "get_macro_indicators", "get_prediction_markets"],
                ),
            },
            {
                "key": "fundamentals",
                "title": "Fundamentals Analyst",
                "description": "Reconciled company statements and derived metrics in one compact verified evidence payload.",
                "tools": list(FUNDAMENTALS_ANALYST_TOOL_NAMES),
                "prompt": render_full_prompt(
                    TOOL_CALLING_COLLABORATION_PROMPT,
                    build_fundamentals_analyst_system_message(),
                    FUNDAMENTALS_ANALYST_TOOL_NAMES,
                ),
            },
        ]
    }
