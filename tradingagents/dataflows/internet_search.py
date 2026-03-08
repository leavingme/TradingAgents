"""
Internet Search Vendors - Tavily, Serper, and DuckDuckGo
提供多种互联网搜索供应商的实现。
"""

import os
import requests
import json
from .config import get_config

def search_tavily(query: str, limit: int = 5) -> str:
    """使用 Tavily API 进行搜索 (Specialized for AI Agents)"""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "Error: TAVILY_API_KEY not found in environment."
    
    url = "https://api.tavily.com/search"
    # 确保 limit 在有效范围内 (1-10)
    safe_limit = max(1, min(int(limit), 10))
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic", # basic 速度更快，消耗点数少
        "max_results": safe_limit,
        "include_answer": False
    }
    
    try:
        response = requests.post(url, json=payload, timeout=15)
        if response.status_code != 200:
            return f"Tavily API 报错 (Status {response.status_code}): {response.text}"
        
        data = response.json()
        
        results = data.get("results", [])
        if not results:
            return "No results found on Tavily."
            
        formatted = [f"Tavily Search Results for: {query}\n"]
        for i, res in enumerate(results, 1):
            formatted.append(f"[{i}] {res.get('title')}\n    URL: {res.get('url')}\n    Content: {res.get('content')[:500]}...")
            
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Tavily search failed: {e}"

def search_serper(query: str, limit: int = 5) -> str:
    """使用 Serper (Google Search API) 进行搜索"""
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return "Error: SERPER_API_KEY not found in environment."
    
    url = "https://google.serper.dev/search"
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json'
    }
    payload = json.dumps({"q": query, "num": limit})
    
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        results = data.get("organic", [])
        if not results:
            return "No organic results found on Serper."
            
        formatted = [f"Serper (Google) Search Results for: {query}\n"]
        for i, res in enumerate(results, 1):
            formatted.append(f"[{i}] {res.get('title')}\n    URL: {res.get('link')}\n    Snippet: {res.get('snippet')}")
            
        return "\n\n".join(formatted)
    except Exception as e:
        return f"Serper search failed: {e}"

def search_duckduckgo(query: str, limit: int = 5) -> str:
    """使用 DuckDuckGo 进行搜索 (完全免费)"""
    try:
        from ddgs import DDGS
                
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=limit))
            
        if not results:
            return "No results found on DuckDuckGo."
            
        formatted = [f"DuckDuckGo Search Results for: {query}\n"]
        for i, res in enumerate(results, 1):
            formatted.append(f"[{i}] {res.get('title')}\n    URL: {res.get('href')}\n    Body: {res.get('body')}")
            
        return "\n\n".join(formatted)
    except ImportError:
        return "Error: duckduckgo-search package not installed. Please run 'pip install duckduckgo-search'."
    except Exception as e:
        return f"DuckDuckGo search failed: {e}"
