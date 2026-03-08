#!/usr/bin/env python3
"""
外部程序调用 TradingAgents 的示例（无需 CLI 交互）
分析港股小米 (1810.HK)

用法：
    python demo_longbridge_analysis.py
    python demo_longbridge_analysis.py 0700.HK 2024-03-01
"""
import sys
import os
import datetime
from dotenv import load_dotenv

# 加载 .env 配置（LONGBRIDGE_APP_KEY / OPENAI_API_BASE 等）
load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG


def run(symbol: str, date: str, analysts=None):
    """
    直接调用 TradingAgents 分析，无需 CLI 交互。

    Args:
        symbol: 股票代码，如 "1810.HK", "AAPL", "0700.HK"
        date:   分析日期，如 "2024-03-01"
        analysts: 分析师列表，默认全选
    """
    if analysts is None:
        analysts = ["market", "social", "news", "fundamentals"]

    # ── 配置（优先读 .env，fallback 到 default_config）──────
    config = DEFAULT_CONFIG.copy()
    # custom provider 会从 default_config 自动读取 .env 中的值，
    # 也可在这里显式覆盖：
    # config["backend_url"]    = "http://127.0.0.1:4000/v1"
    # config["quick_think_llm"] = "kimi-code"
    # config["deep_think_llm"]  = "kimi-code"

    print("=" * 60)
    print(f"  TradingAgents 分析")
    print(f"  标的: {symbol} | 日期: {date}")
    print(f"  LLM:  {config['llm_provider']} / {config['quick_think_llm']}")
    print(f"  数据: {config['data_vendors']}")
    print("=" * 60)

    # ── 初始化 ───────────────────────────────────────────────
    ta = TradingAgentsGraph(
        selected_analysts=analysts,
        config=config,
        debug=False,     # True 会在终端打印每条消息
    )

    # ── 执行分析 ─────────────────────────────────────────────
    print(f"\n⏳ 开始分析，请稍候...\n")
    try:
        final_state, decision = ta.propagate(symbol, date)

        print("\n" + "=" * 60)
        print(f"  ✅ 分析完成")
        print(f"  🎯 决策: {decision}")
        print("=" * 60)

        # 可以在这里进一步处理报告
        # final_state["market_report"]
        # final_state["fundamentals_report"]
        # final_state["news_report"]
        # final_state["sentiment_report"]
        # final_state["final_trade_decision"]

        return final_state, decision

    except Exception as e:
        import traceback
        print(f"\n❌ 分析失败: {e}")
        traceback.print_exc()
        return None, None


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "1810.HK"
    date   = sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().strftime("%Y-%m-%d")
    run(symbol, date)
