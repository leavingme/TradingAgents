"""
测试 Serper (Google Search) API 连通性
"""
import os
from dotenv import load_dotenv
from tradingagents.dataflows.internet_search import search_serper

load_dotenv()

def test_serper():
    print("🚀 正在测试 Serper Search (Google Results)...")
    query = "NVIDIA AI chips competitors 2025"
    result = search_serper(query, limit=3)
    print("\n--- Serper 返回结果 ---")
    print(result)

if __name__ == "__main__":
    test_serper()
