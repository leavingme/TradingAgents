from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor

@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    return route_to_vendor("get_news", ticker, start_date, end_date)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor.
    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back (default 7)
        limit (int): Maximum number of articles to return (default 5)
    Returns:
        str: A formatted string containing global news data
    """
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)


@tool
def search_internet_news(
    query: Annotated[str, "搜索查询词，例如 'NVDA 最新财报深度解析' 或 '美联储利率决议对科技股的影响'"],
    vendor: Annotated[str, "选择搜索供应商: 'web_search' (Kimi), 'tavily', 'serper', 'duckduckgo'。默认为 'web_search'"] = "web_search",
) -> str:
    """
    通过互联网实时搜索获取最新的新闻、分析或针对性信息。
    支持多种搜索引擎：
    - 'web_search': Kimi 内置搜索 (默认)
    - 'tavily': 专业 AI 搜索 (需 TAVILY_API_KEY)
    - 'serper': Google 搜索镜像 (需 SERPER_API_KEY)
    - 'duckduckgo': 完全免费的匿名搜索
    
    Args:
        query (str): 搜索关键词
        vendor (str): 指定供应商
    Returns:
        str: 搜索到的网页内容摘要和来源
    """
    from tradingagents.dataflows.interface import VENDOR_METHODS
    
    available_vendors = VENDOR_METHODS["get_news"]
    if vendor not in available_vendors:
        return f"错误: 不支持的供应商 '{vendor}'。可选: {list(available_vendors.keys())}"
        
    func = available_vendors[vendor]
    
    # Kimi 的 web_search 接口需要 3 个参数，其他 search 接口只需要 query
    if vendor == "web_search":
        return func(query, "latest", "latest")
    else:
        return func(query)
