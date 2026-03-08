"""
TradingAgents 搜索矩阵全能验证脚本
==================================
一次性验证以下搜索供应商的连通性和结果：
1. Kimi Web Search (web_search)
2. Twitter/X (bird CLI)
3. Tavily (Specialized AI Search)
4. Serper (Google Search Results)
5. DuckDuckGo (Global Free Search)
"""

import os
import json
from dotenv import load_dotenv
from tradingagents.agents.utils.news_data_tools import search_internet_news
from tradingagents.agents.utils.social_media_tools import get_twitter_stock_sentiment

# 初始化
load_dotenv()

def print_separator(title):
    print("\n" + "="*60)
    print(f"🚀 {title}")
    print("="*60)

def verify_all():
    query = "NVDA stock market performance 2025"
    ticker = "NVDA"
    company = "NVIDIA"
    
    # --- 1. Kimi Web Search ---
    print_separator("方案 1: Kimi 内置搜索 (web_search)")
    try:
        # 使用 search_internet_news 工具调用，默认就是 web_search
        res = search_internet_news.invoke({"query": query, "vendor": "web_search"})
        print(f"状态: ✅ 成功\n预览: {res[:400]}...")
    except Exception as e:
        print(f"状态: ❌ 失败 - {e}")

    # --- 2. Twitter / Bird CLI ---
    print_separator("方案 2: Twitter 舆情 (bird CLI)")
    try:
        res = get_twitter_stock_sentiment.invoke({"ticker": ticker, "company_name": company, "limit": 5})
        print(f"状态: ✅ 成功\n预览: {res[:400]}...")
    except Exception as e:
        print(f"状态: ❌ 失败 - {e}")

    # --- 3. Tavily ---
    print_separator("方案 3: Tavily (AI 优化搜索)")
    try:
        res = search_internet_news.invoke({"query": query, "vendor": "tavily"})
        print(f"状态: ✅ 成功\n预览: {res[:400]}...")
    except Exception as e:
        print(f"状态: ❌ 失败 - {e}")

    # --- 4. Serper ---
    print_separator("方案 4: Serper (Google 搜索镜像)")
    try:
        res = search_internet_news.invoke({"query": query, "vendor": "serper"})
        print(f"状态: ✅ 成功\n预览: {res[:400]}...")
    except Exception as e:
        print(f"状态: ❌ 失败 - {e}")

    # --- 5. DuckDuckGo ---
    print_separator("方案 5: DuckDuckGo (全免费搜索)")
    try:
        res = search_internet_news.invoke({"query": query, "vendor": "duckduckgo"})
        print(f"状态: ✅ 成功\n预览: {res[:400]}...")
    except Exception as e:
        print(f"状态: ❌ 失败 - {e}")

if __name__ == "__main__":
    verify_all()
