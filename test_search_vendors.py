"""
验证 Tavily, Serper, DuckDuckGo 搜索集成
========================================
测试 search_internet_news 工具是否能正确路由到不同的搜索引擎。
"""

import os
from tradingagents.agents.utils.news_data_tools import search_internet_news

def test_search_vendors():
    print("="*60)
    print("🚀 测试 Internet Search Vendors 集成")
    print("="*60)
    
    query = "NVDA stock price forecast 2025"
    
    # 1. 测试 DuckDuckGo (无需 Key)
    print(f"\n[1] 正在测试 DuckDuckGo: '{query}'...")
    try:
        res_ddg = search_internet_news.invoke({"query": query, "vendor": "duckduckgo"})
        print(f"--- DDG 结果预览 ---\n{res_ddg[:500]}...")
    except Exception as e:
        print(f"❌ DDG 失败: {e}")

    # 2. 验证路由逻辑 (不实际调用 API，因为没 Key)
    print("\n[2] 验证路由逻辑 (Tavily/Serper)...")
    
    # 模拟环境变量缺失的情况
    os.environ["TAVILY_API_KEY"] = ""
    res_tavily = search_internet_news.invoke({"query": query, "vendor": "tavily"})
    print(f"Tavily (无 Key) 返回: {res_tavily}")
    
    res_invalid = search_internet_news.invoke({"query": query, "vendor": "unknown"})
    print(f"无效供应商返回: {res_invalid}")

if __name__ == "__main__":
    test_search_vendors()
