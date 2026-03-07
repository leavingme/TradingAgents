#!/home/ubuntu/.openclaw/workspace/TradingAgents/venv/bin/python3
"""
长桥 API 港股行情工具
"""
import os
import json
from longport.openapi import QuoteContext, Config, AdjustType, Period

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def main(symbols=None):
    if symbols is None:
        symbols = ["1810.HK"]
    
    # 创建配置
    config = Config(
        app_key=require_env("LONGBRIDGE_APP_KEY"),
        app_secret=require_env("LONGBRIDGE_APP_SECRET"),
        access_token=require_env("LONGBRIDGE_ACCESS_TOKEN"),
    )
    
    # 创建行情上下文
    ctx = QuoteContext(config)
    
    # 获取行情
    print(f"正在获取行情: {symbols}\n")
    resp = ctx.quote(symbols)
    
    for quote in resp:
        print("="*50)
        print(f"📊 {quote.symbol}")
        print("="*50)
        print(f"  最新价: {quote.last_done}")
        print(f"  涨跌额: {float(quote.last_done) - float(quote.prev_close):.3f}")
        print(f"  涨跌幅: {(float(quote.last_done) / float(quote.prev_close) - 1) * 100:.2f}%")
        print(f"  开盘: {quote.open}")
        print(f"  最高: {quote.high}")
        print(f"  最低: {quote.low}")
        print(f"  昨收: {quote.prev_close}")
        print(f"  成交量: {quote.volume:,}")
        print(f"  成交额: {float(quote.turnover):,.0f}")
        print()
        
        # 如果是港股，获取K线
        if ".HK" in quote.symbol:
            print(f"  获取 {quote.symbol} K线数据...")
            try:
                klines = ctx.candlesticks(quote.symbol, Period.Day, 20, AdjustType.NoAdjust)
                closes = [k.close for k in klines]
                
                if len(closes) >= 5:
                    sma5 = sum(closes[-5:]) / 5
                    print(f"    5日均线: {sma5:.2f}")
                    current = closes[-1]
                    if current > sma5:
                        print(f"    → 价格在5日均线上方，短期偏强")
                    else:
                        print(f"    → 价格在5日均线下方，短期偏弱")
                        
                print(f"    最近5日: {[f'{c:.2f}' for c in closes[-5:]]}")
            except Exception as e:
                print(f"    K线获取失败: {e}")
            print()

if __name__ == "__main__":
    import sys
    
    # 支持命令行参数
    if len(sys.argv) > 1:
        symbols = sys.argv[1:]
    else:
        symbols = ["1810.HK"]  # 默认小米
    
    main(symbols)
