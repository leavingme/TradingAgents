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


def analyst_prompt_payload() -> dict[str, list[dict[str, object]]]:
    return {
        "analysts": [
            {
                "key": "market",
                "title": "Market Analyst",
                "description": "Technical market analysis using OHLCV data, indicators, and a verified market snapshot.",
                "tools": ["get_stock_data", "get_indicators", "get_verified_market_snapshot"],
                "prompt": render_full_prompt(
                    TOOL_CALLING_COLLABORATION_PROMPT,
                    build_market_analyst_system_message(),
                    ["get_stock_data", "get_indicators", "get_verified_market_snapshot"],
                ),
            },
            {
                "key": "social",
                "title": "Sentiment Analyst",
                "description": "Sentiment analysis from pre-fetched news headlines, StockTwits messages, and Reddit posts.",
                "tools": ["get_news", "fetch_stocktwits_messages", "fetch_reddit_posts"],
                "prompt": render_full_prompt(
                    PREFETCHED_DATA_COLLABORATION_PROMPT,
                    build_sentiment_analyst_system_message(
                        ticker="{ticker}",
                        start_date="{start_date}",
                        end_date="{end_date}",
                        news_block="{news_block}",
                        stocktwits_block="{stocktwits_block}",
                        reddit_block="{reddit_block}",
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
                "description": "Company fundamentals, profile, financial statements, and historical financial context.",
                "tools": ["get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"],
                "prompt": render_full_prompt(
                    TOOL_CALLING_COLLABORATION_PROMPT,
                    build_fundamentals_analyst_system_message(),
                    ["get_fundamentals", "get_balance_sheet", "get_cashflow", "get_income_statement"],
                ),
            },
        ]
    }
