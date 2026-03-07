#!/usr/bin/env python3
"""
使用长桥数据源的 TradingAgents 分析示例
分析港股小米 (1810.HK)
"""
import sys
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/TradingAgents')

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

def main():
    print("="*60)
    print("🚀 TradingAgents + 长桥数据源")
    print("分析标的: 1810.HK (小米集团)")
    print("="*60)
    
    # 使用长桥数据源的配置
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "openai"
    config["deep_think_llm"] = "kimi-k2-5"
    config["quick_think_llm"] = "kimi-k2-5"
    
    # 关键：设置使用长桥数据源
    config["data_vendors"] = {
        "core_stock_apis": "longbridge",       # 使用长桥获取股票数据
        "technical_indicators": "longbridge",  # 使用长桥获取技术指标
        "fundamental_data": "yfinance",        # 基本面数据仍用 yfinance
        "news_data": "yfinance",               # 新闻数据仍用 yfinance
    }
    
    print("\n📊 配置信息:")
    print(f"  数据源: {config['data_vendors']}")
    print(f"  LLM: {config['deep_think_llm']}")
    
    # 初始化 TradingAgents
    print("\n🔄 初始化 TradingAgents...")
    ta = TradingAgentsGraph(debug=True, config=config)
    
    # 分析小米
    today = "2026-02-28"
    symbol = "1810.HK"
    
    print(f"\n📈 开始分析 {symbol} ({today})...")
    print("\n" + "="*60)
    
    try:
        state, decision = ta.propagate(symbol, today)
        
        print("\n" + "="*60)
        print("✅ 分析完成!")
        print("="*60)
        print(f"\n🎯 最终决策: {decision}")
        
    except Exception as e:
        print(f"\n❌ 分析错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
