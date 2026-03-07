#!/usr/bin/env python3
"""
TradingAgents + Webhook 通知
分析完成后自动发送结果到 Discord
"""
import sys
import os
import json
import requests
from datetime import datetime
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/TradingAgents')

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Discord Webhook 配置
# 需要在 Discord 频道设置中创建 webhook，把 URL 填在这里
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

def require_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def send_to_discord(message, title="TradingAgents 分析完成", color=0x00ff00):
    """发送消息到 Discord"""
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ 未配置 Discord Webhook，跳过通知")
        print(f"消息内容:\n{message[:500]}...")
        return
    
    # Discord embed 格式
    payload = {
        "embeds": [{
            "title": title,
            "description": message[:2000],  # Discord 限制
            "color": color,
            "timestamp": datetime.now().isoformat(),
            "footer": {"text": "TradingAgents | 长桥数据源"}
        }]
    }
    
    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        if response.status_code == 204:
            print("✅ 已发送 Discord 通知")
        else:
            print(f"⚠️ 发送失败: {response.status_code}")
    except Exception as e:
        print(f"⚠️ 发送错误: {e}")

def send_simple_message(content):
    """发送简单文本消息"""
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ 未配置 Discord Webhook")
        print(f"内容:\n{content[:500]}...")
        return
    
    payload = {"content": content[:2000]}
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except:
        pass

def main():
    require_env("OPENAI_API_KEY")
    require_env("OPENAI_API_BASE")
    require_env("LONGBRIDGE_APP_KEY")
    require_env("LONGBRIDGE_APP_SECRET")
    require_env("LONGBRIDGE_ACCESS_TOKEN")

    print("="*70)
    print("🚀 TradingAgents + Discord 通知")
    print("="*70)
    
    # 检查 webhook 配置
    if not DISCORD_WEBHOOK_URL:
        print("\n⚠️ 请设置 Discord Webhook URL:")
        print("  export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'")
        print("\n或者在脚本中修改 DISCORD_WEBHOOK_URL 变量")
    else:
        print(f"\n✅ Discord Webhook 已配置")
    
    # TradingAgents 配置
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "openai"
    config["deep_think_llm"] = "kimi-k2-5"
    config["quick_think_llm"] = "kimi-k2-5"
    config["max_debate_rounds"] = 2
    config["max_risk_discuss_rounds"] = 2
    config["data_vendors"] = {
        "core_stock_apis": "longbridge",
        "technical_indicators": "longbridge",
        "fundamental_data": "yfinance",
        "news_data": "yfinance",
    }
    
    symbol = "1810.HK"
    today = "2026-02-28"
    
    print(f"\n📈 开始分析 {symbol}...")
    print(f"开始时间: {datetime.now().strftime('%H:%M:%S')}")
    print("="*70)
    
    # 发送开始通知
    send_simple_message(f"🔄 TradingAgents 开始分析 **{symbol}**...")
    
    try:
        ta = TradingAgentsGraph(debug=True, config=config)
        state, decision = ta.propagate(symbol, today)
        
        # 构建报告
        report = f"""
**分析完成** ✅
**标的**: {symbol} (小米集团)
**日期**: {today}
**最终决策**: {decision}
**完成时间**: {datetime.now().strftime('%H:%M:%S')}

---

**数据来源**: 长桥 API + yfinance
**分析流程**: 
- ✅ Technical Analyst (技术分析)
- ✅ Fundamental Analyst (基本面)
- ✅ Sentiment Analyst (情绪分析)
- ✅ News Analyst (新闻分析)
- ✅ Bull/Bear Research Team (多空辩论)
- ✅ Trader Agent (交易决策)
- ✅ Risk Manager (风险评估)
- ✅ Portfolio Manager (最终决策)

---

使用命令行工具查看详细分析:
```bash
./longbridge_quote.py {symbol}
```
"""
        
        print("\n" + "="*70)
        print("✅ 分析完成!")
        print("="*70)
        print(f"决策: {decision}")
        
        # 发送完成通知
        send_to_discord(
            message=report,
            title=f"📊 {symbol} 分析完成 | 决策: {decision}",
            color=0x00ff00 if "BUY" in decision.upper() else 0xff0000 if "SELL" in decision.upper() else 0xffff00
        )
        
    except Exception as e:
        error_msg = str(e)
        print(f"\n❌ 分析错误: {error_msg}")
        
        # 发送错误通知
        send_to_discord(
            message=f"分析失败: {error_msg[:500]}",
            title=f"❌ {symbol} 分析失败",
            color=0xff0000
        )

if __name__ == "__main__":
    main()
