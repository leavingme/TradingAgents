from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news,
    search_internet_news
)
from tradingagents.agents.utils.social_media_tools import (
    get_twitter_stock_sentiment,
    get_twitter_trending_finance
)

# 语言输出控制：所有 agent prompt 末尾追加此常量即可切换输出语言
CHINESE_OUTPUT = "\n\n**重要：请将你所有的分析、报告和回答都用简体中文（Simplified Chinese）撰写，不要使用英文输出。**"


def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        