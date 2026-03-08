from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import time
import json
from tradingagents.agents.utils.agent_utils import get_news, get_twitter_stock_sentiment, CHINESE_OUTPUT
from tradingagents.dataflows.config import get_config


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        ticker = state["company_of_interest"]
        company_name = state["company_of_interest"]

        tools = [
            get_twitter_stock_sentiment,
            get_news,
        ]

        system_message = (
            "You are a social media analyst tasked with analyzing real-time sentiment and discussions on Twitter/X for a specific company over the past week. "
            "Use get_twitter_stock_sentiment(ticker, company_name) to fetch live tweets, opinions from KOLs, and retail sentiment. "
            "Your objective is to write a comprehensive report detailing public sentiment, key discussion topics, and technical market vibes. "
            "Analyze engagement (likes/retweets) to identify influential opinions. Use get_news as a secondary source for company announcements."
            "Do not simply state the trends are mixed; provide fine-grained analysis of the bullish and bearish sentiment depth."
            + """ Make sure to append a Markdown table at the end of the report to organize key sentiment points."""
            + CHINESE_OUTPUT,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. The current company we want to analyze is {ticker}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(ticker=ticker)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "sentiment_report": report,
        }

    return social_media_analyst_node
