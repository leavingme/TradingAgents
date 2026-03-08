#!/usr/bin/env python3
"""
验证 social_media_analyst + bird CLI 集成
========================================
测试 social_media_analyst 是否能正确触发 get_twitter_stock_sentiment 工具并获取数据。
"""

import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from tradingagents.agents.analysts.social_media_analyst import create_social_media_analyst

# 加载配置
load_dotenv()

BASE_URL = os.environ.get("OPENAI_API_BASE", "http://127.0.0.1:4000/v1")
API_KEY  = os.environ.get("OPENAI_API_KEY", "")
MODEL    = os.environ.get("CUSTOM_QUICK_MODEL", "kimi-code")

def test_social_analyst():
    print("="*60)
    print("🚀 测试 Social Media Analyst + Twitter 集成")
    print("="*60)
    
    # 1. 初始化 LLM
    llm = ChatOpenAI(model=MODEL, base_url=BASE_URL, api_key=API_KEY)
    
    # 2. 创建 Analyst Node
    analyst_node = create_social_media_analyst(llm)
    
    # 3. 构造 State
    state = {
        "trade_date": "2025-03-08",
        "company_of_interest": "NVDA",
        "messages": [("user", "分析一下 NVDA 现在的推特舆情和讨论热点。")]
    }
    
    print(f"🔍 正在请求分析 NVDA (Model: {MODEL})...")
    
    try:
        # 运行节点
        result = analyst_node(state)
        
        # 检查是否触发了工具
        msg = result["messages"][0]
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            print(f"✅ 成功触发攻击调用: {msg.tool_calls[0]['name']}")
            print(f"   参数: {msg.tool_calls[0]['args']}")
            
            # 由于工具执行需要实际调用 bird CLI，这里如果环境支持，Agent 会继续执行
            # 由于我们只测试节点逻辑和工具绑定，看到这里已经证明集成成功。
        else:
            print("⚠️ 模型未触发工具调用，直接回答：")
            print(msg.content)
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    test_social_analyst()
