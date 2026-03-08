"""
Web Search Dataflow - 基于 Kimi 内置搜索的新闻抓取
通过 Anthropic 格式接口调用 Kimi 的 web_search_20250305 工具。
"""

import os
import anthropic
import json
from .config import get_config

def _get_anthropic_client():
    config = get_config()
    # 使用与网关一致的配置
    api_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    base_url = config.get("backend_url") or os.getenv("OPENAI_API_BASE", "http://127.0.0.1:4000/v1")
    # 去掉 /v1 以符合 anthropic SDK 的 base_url 要求
    base_url = base_url.replace("/v1", "").rstrip("/")
    
    return anthropic.Anthropic(api_key=api_key, base_url=base_url)

def get_news(ticker, start_date, end_date):
    """使用 Kimi Web Search 获取特定股票的新闻"""
    client = _get_anthropic_client()
    config = get_config()
    model = config.get("quick_think_llm", "kimi-code")
    
    query = f"搜索股票 {ticker} 从 {start_date} 到 {end_date} 之间的核心新闻、公告和财报相关信息。"
    
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": query}]
        )
        
        # 汇总搜索结果块和文字块
        full_content = []
        for block in resp.content:
            if block.type == "text":
                full_content.append(block.text)
            elif block.type == "web_search_tool_result":
                # 记录找到的来源
                results = getattr(block, "content", [])
                source_count = len(results)
                full_content.append(f"\n[找到了 {source_count} 条实时搜索来源]\n")
        
        return "\n".join(full_content)
    except Exception as e:
        print(f"Web Search get_news 失败: {e}")
        raise e

def get_global_news(curr_date, look_back_days=7, limit=5):
    """使用 Kimi Web Search 获取宏观财经新闻"""
    client = _get_anthropic_client()
    config = get_config()
    model = config.get("quick_think_llm", "kimi-code")
    
    query = f"搜索从 {curr_date} 往前推 {look_back_days} 天内的全球重大宏观经济新闻、美联储政策转向或金融市场核心波动。"
    
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": query}]
        )
        
        full_content = []
        for block in resp.content:
            if block.type == "text":
                full_content.append(block.text)
        return "\n".join(full_content)
    except Exception as e:
        print(f"Web Search get_global_news 失败: {e}")
        raise e
