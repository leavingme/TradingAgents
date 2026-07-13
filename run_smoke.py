"""Non-interactive smoke runner for TradingAgents.

Bypasses CLI questionary prompts; runs through the audited headless runtime.
Use this for verification, not production.
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from tradingagents.runtime import AnalysisRequest, run_analysis_once
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.config import set_config

# Build config: LLM via direct minimax (no :8642 gateway), Alpha Vantage + DuckDuckGo for data
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = os.getenv("CUSTOM_LLM_PROVIDER", "minimax-cn")
config["backend_url"] = os.getenv(
    "OPENAI_BASE_URL", os.getenv("OPENAI_API_BASE", "https://api.minimaxi.com/v1")
)
config["deep_think_llm"] = os.getenv("DEEP_MODEL", os.getenv("CUSTOM_DEEP_MODEL", "MiniMax-M3"))
config["quick_think_llm"] = os.getenv("QUICK_MODEL", os.getenv("CUSTOM_QUICK_MODEL", "MiniMax-M3"))
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1
config["llm_timeout"] = 120
config["data_vendors"] = {
    "core_stock_apis": "longbridge_mcp, longbridge, westock",
    "technical_indicators": "westock, longbridge_mcp, longbridge",
    "fundamental_data": "westock, longbridge_mcp, longbridge",
    "news_data": "web_search, duckduckgo, alpha_vantage, westock",
}

# Analyst subset: skip social + news to reduce LLM calls in smoke run
analysts = ["market", "fundamentals"]

# Propagate config to the global config used by routing layer
set_config(config)

symbol = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
date = sys.argv[2] if len(sys.argv) > 2 else "2026-02-27"

print(f"=== Smoke run: symbol={symbol} date={date} ===")
print(f"  backend = {config['backend_url']}")
print(f"  quick   = {config['quick_think_llm']}")
print(f"  deep    = {config['deep_think_llm']}")
print(f"  vendors = {config['data_vendors']}")
print()

try:
    result = run_analysis_once(AnalysisRequest(
        ticker=symbol,
        analysis_date=date,
        selected_analysts=tuple(analysts),
        llm_provider=config["llm_provider"],
        backend_url=config["backend_url"],
        deep_think_llm=config["deep_think_llm"],
        quick_think_llm=config["quick_think_llm"],
        research_depth=1,
        config_overrides={
            "llm_timeout": config["llm_timeout"],
            "data_vendors": config["data_vendors"],
        },
    ))
    print("\n=== FINAL DECISION ===")
    print(result.decision if result.decision is not None else "NO_DECISION")
    print(f"decision_status={result.decision_status} run_id={result.run_id}")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"\nFAILED: {type(e).__name__}: {e}")
    sys.exit(1)
