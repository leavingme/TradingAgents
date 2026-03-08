#!/usr/bin/env python3
"""
TradingAgents 完整分析 - 小米 (不减轮数)
继续之前的分析流程
"""
import sys
import os
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/TradingAgents')

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def main():
    require_env("OPENAI_API_KEY")
    require_env("OPENAI_API_BASE")
    require_env("LONGBRIDGE_APP_KEY")
    require_env("LONGBRIDGE_APP_SECRET")
    require_env("LONGBRIDGE_ACCESS_TOKEN")

    print("="*70)
    print("🚀 TradingAgents 完整分析 (不减轮数)")
    print("标的: 1810.HK (小米集团)")
    print("="*70)
    
    # 完整配置 - 不减轮数
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "openai"
    config["deep_think_llm"] = "kimi-k2-5"
    config["quick_think_llm"] = "kimi-k2-5"
    
    # 标准轮数
    config["max_debate_rounds"] = 2  # 多空辩论2轮
    config["max_risk_discuss_rounds"] = 2  # 风险讨论2轮
    
    # 长桥数据源
    config["data_vendors"] = {
        "core_stock_apis": "longbridge",
        "technical_indicators": "longbridge",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }
    
    print("\n⚙️ 配置:")
    print(f"  辩论轮数: {config['max_debate_rounds']} 轮")
    print(f"  风险讨论: {config['max_risk_discuss_rounds']} 轮")
    print(f"  数据源: 长桥(港股) + yfinance(基本面/新闻)")
    
    print("\n🔄 启动 TradingAgents...")
    print("  将依次运行:")
    print("    1. Technical Analyst (技术分析)")
    print("    2. Fundamental Analyst (基本面)")
    print("    3. Sentiment Analyst (情绪分析)")
    print("    4. News Analyst (新闻分析)")
    print("    5. Research Team - Bull vs Bear (多空辩论)")
    print("    6. Trader Agent (交易决策)")
    print("    7. Risk Manager (风险评估)")
    print("    8. Portfolio Manager (最终决策)")
    print()
    
    ta = TradingAgentsGraph(debug=True, config=config)
    
    symbol = "1810.HK"
    today = "2026-02-28"
    
    print(f"开始分析 {symbol}...")
    print("="*70)
    
    try:
        state, decision = ta.propagate(symbol, today)
        
        print("\n" + "="*70)
        print("✅ 完整分析结束!")
        print("="*70)
        print(f"\n🎯 最终决策: {decision}")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")

if __name__ == "__main__":
    main()
