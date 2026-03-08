#!/usr/bin/env python3
"""
TradingAgents 快速分析 - 小米 (使用长桥数据源)
优化配置：最小轮数、快速模型
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
    print("🚀 TradingAgents 快速分析")
    print("标的: 1810.HK (小米集团)")
    print("数据源: 长桥 API")
    print("="*70)
    
    # 极速配置
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "openai"
    
    # 使用轻量级模型加速
    config["deep_think_llm"] = "kimi-k2-5"  
    config["quick_think_llm"] = "kimi-k2-5"
    
    # 最小化轮数 - 极速模式
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["max_recur_limit"] = 50
    
    # 使用长桥数据源
    config["data_vendors"] = {
        "core_stock_apis": "longbridge",
        "technical_indicators": "longbridge",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }
    
    # 后端配置
    config["backend_url"] = "http://127.0.0.1:18789/v1"
    
    print("\n⚙️ 配置:")
    print(f"  LLM: {config['deep_think_llm']}")
    print(f"  辩论轮数: {config['max_debate_rounds']}")
    print(f"  数据源: {config['data_vendors']}")
    
    # 初始化
    print("\n🔄 初始化 TradingAgents...")
    try:
        ta = TradingAgentsGraph(debug=True, config=config)
        print("  ✓ 初始化成功")
    except Exception as e:
        print(f"  ✗ 初始化失败: {e}")
        return
    
    # 执行分析
    symbol = "1810.HK"
    today = "2026-02-28"
    
    print(f"\n📈 分析 {symbol} ({today})...")
    print("="*70)
    
    try:
        state, decision = ta.propagate(symbol, today)
        
        print("\n" + "="*70)
        print("✅ 分析完成!")
        print("="*70)
        print(f"\n🎯 最终决策: {decision}")
        
        # 打印关键信息
        if hasattr(state, 'get'):
            print(f"\n📊 关键指标:")
            for key in ['technical_analysis', 'fundamental_analysis', 'sentiment_analysis']:
                if key in state:
                    print(f"  {key}: {state.get(key, 'N/A')[:100]}...")
        
    except Exception as e:
        print(f"\n❌ 分析错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
