from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from dotenv import load_dotenv
import os
import json

# Load environment variables from .env file
load_dotenv()

# Create a FAST config - minimal rounds for quick results
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "kimi-k2-5"  # Use local fast model
config["quick_think_llm"] = "kimi-k2-5"  # Use local fast model
config["max_debate_rounds"] = 1  # Minimal debate
config["max_risk_discuss_rounds"] = 1  # Minimal risk discussion

# Configure data vendors
config["data_vendors"] = {
    "core_stock_apis": "yfinance",
    "technical_indicators": "yfinance",
    "fundamental_data": "yfinance",
    "news_data": "yfinance",
}

print("="*60)
print("🚀 TradingAgents 快速分析: BIDU (百度)")
print("="*60)

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate for TODAY
today_str = "2026-02-28"
print(f"\n📊 正在分析 {today_str} 的 BIDU...\n")

try:
    state, decision = ta.propagate("BIDU", today_str)
    
    print("\n" + "="*60)
    print("📈 分析完成!")
    print("="*60)
    print(f"\n🎯 最终决策: {decision}")
    
    # Save results
    results_dir = "./results"
    os.makedirs(results_dir, exist_ok=True)
    result_file = f"{results_dir}/BIDU_{today_str}_quick.json"
    
    with open(result_file, 'w') as f:
        json.dump({
            "ticker": "BIDU",
            "date": today_str,
            "decision": decision,
            "state": str(state)
        }, f, indent=2)
    
    print(f"\n💾 结果已保存: {result_file}")
    
except Exception as e:
    print(f"\n❌ 错误: {e}")
    import traceback
    traceback.print_exc()
