"""
测试 Tavily API 连通性
"""
import os
from dotenv import load_dotenv
from tradingagents.dataflows.internet_search import search_tavily

load_dotenv()

def test_tavily():
    print("🚀 正在测试 Tavily Search...")
    query = "NVIDIA latest financial highlights 2025"
    result = search_tavily(query, limit=3)
    print("\n--- Tavily 返回结果 ---")
    print(result)

if __name__ == "__main__":
    test_tavily()
